"""Client HTTP partagé : cache SQLite, réessais avec attente exponentielle, bascule entre serveurs.

Les API publiques (Overpass, Nominatim, BRouter, IGN) sont gratuites mais limitées :
on s'identifie avec un User-Agent explicite, on met en cache et on ne martèle pas.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from . import __version__

USER_AGENT = f"RandoForge/{__version__} (+https://github.com/LaMachiiine/randoforge)"
RETRYABLE = {429, 500, 502, 503, 504}
# Limites des services publics gratuits : (requêtes simultanées max, intervalle min. entre deux requêtes en s).
# IGN annonce « ratelimit-limit: 5 » (≈ 5 req/s) ; BRouter répond 403 quand on l'inonde ; Nominatim : 1 req/s.
HOST_LIMITS: dict[str, tuple[int, float]] = {
    "nominatim.openstreetmap.org": (1, 1.1),
    "data.geopf.fr": (3, 0.25),
    "brouter.de": (2, 0.2),
}
# Blocage temporaire signalé avec un code « définitif » par certains serveurs publics (BRouter : 403).
RETRYABLE_BY_HOST = {"brouter.de": {403}}
MAX_RETRY_AFTER_S = 30.0
MAX_BACKOFF_S = 8.0

DAY = 86_400.0
# BRouter public coupe tout calcul de plus de 2 s : surcharge passagère OU itinéraire trop complexe / points loin des
# chemins. On réessaie une fois, puis on renvoie un message qui aide à corriger la demande.
TOO_SLOW_TEXT = ("thread-priority-watchdog", "operation killed")
TOO_SLOW_HINT = (
    "calcul interrompu par le serveur (trop long). Points peut-être loin des chemins ou itinéraire trop long : "
    "rapprocher les points d'un sentier, ajouter un point intermédiaire ou découper l'itinéraire."
)
DOWN_S = 300.0  # un miroir injoignable est écarté 5 min (évite d'attendre son délai à chaque appel)


class HttpError(Exception):
    """Échec d'un appel externe, avec un message compréhensible par Claude."""


class CachedHttp:
    def __init__(
        self,
        cache_path: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        retries: int = 3,
        host_limits: dict[str, tuple[int, float]] | None = None,
    ):
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(90, connect=8),
            transport=transport,
            follow_redirects=True,
        )
        self.sleep = sleep
        self.retries = retries
        self.host_limits = HOST_LIMITS if host_limits is None else host_limits
        self._last_call: dict[str, float] = {}
        self._slots = {h: threading.BoundedSemaphore(n) for h, (n, _) in self.host_limits.items()}
        self._down_until: dict[str, float] = {}
        self._lock = threading.Lock()
        self.db: sqlite3.Connection | None = None
        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(cache_path, check_same_thread=False)
            self.db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, created REAL, body TEXT)")

    def _cache_key(self, method: str, url: str, payload: Any) -> str:
        raw = json.dumps([method, url, payload], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _cache_get(self, key: str, ttl_s: float | None) -> Any | None:
        if not self.db:
            return None
        with self._lock:
            row = self.db.execute("SELECT created, body FROM cache WHERE key = ?", (key,)).fetchone()
        if row and (ttl_s is None or time.time() - row[0] < ttl_s):
            return json.loads(row[1])
        return None

    def _cache_put(self, key: str, value: Any) -> None:
        if not self.db:
            return
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (key, time.time(), json.dumps(value)))
            self.db.commit()

    def _throttle(self, host: str) -> None:
        """Intervalle minimal entre deux départs de requête vers un même hôte (sûr entre threads)."""
        interval = self.host_limits.get(host, (0, 0.0))[1]
        if not interval:
            return
        with self._lock:
            start = max(time.time(), self._last_call.get(host, 0) + interval)
            self._last_call[host] = start  # réserve le créneau avant de dormir
        if (wait := start - time.time()) > 0:
            self.sleep(wait)

    def _set_aside(self, host: str, mirrors: list[str]) -> bool:
        """Vrai si `host` est écarté et qu'au moins un autre miroir ne l'est pas : on ne met jamais tous les
        miroirs de côté en même temps (sinon le service resterait muet 5 min même après son retour)."""
        now = time.time()
        if len(mirrors) < 2 or self._down_until.get(host, 0) <= now:
            return False
        return any(self._down_until.get(h, 0) <= now for h in mirrors if h != host)

    def _attempt(self, method, url, params, data, json_body, accept, service, mirrors) -> tuple[str, Any]:
        """Un appel à un serveur : ("ok", valeur), ("retry", message), ("slow", message) ou ("fatal", message).

        Un serveur injoignable n'est écarté que s'il a des miroirs : un service à serveur unique doit pouvoir
        être réessayé tout de suite après une coupure passagère."""
        host = urlsplit(url).hostname or url
        if self._set_aside(host, mirrors):
            return "retry", f"{host} écarté (injoignable récemment)"
        slot = self._slots.get(host)
        if slot:
            slot.acquire()
        try:
            self._throttle(host)
            r = self.client.request(method, url, params=params, data=data, json=json_body)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if len(mirrors) > 1:
                self._down_until[host] = time.time() + DOWN_S
            return "retry", f"{host} injoignable ({type(exc).__name__})"
        except httpx.TransportError as exc:
            return "retry", f"{host} : {type(exc).__name__}"
        finally:
            if slot:
                slot.release()
        if r.status_code == 200:
            try:
                value = r.json()
            except ValueError:
                return "retry", f"{host} a renvoyé une réponse non JSON"
            problem = accept(value) if accept else None
            return ("retry", f"{host} : {problem}") if problem else ("ok", value)
        if any(t in r.text for t in TOO_SLOW_TEXT):
            return "slow", f"{service} : {TOO_SLOW_HINT}"
        if r.status_code not in RETRYABLE | RETRYABLE_BY_HOST.get(host, set()):
            return "fatal", f"{service} : erreur {r.status_code} — {r.text.strip().replace(chr(10), ' ')[:300]}"
        if retry_after := r.headers.get("retry-after", "").strip():
            # Le serveur demande d'attendre : on obéit (borné), plutôt que de le marteler.
            try:
                self.sleep(min(float(retry_after), MAX_RETRY_AFTER_S))
            except ValueError:
                pass
        return "retry", f"{host} : {r.status_code}"

    def _hedged(self, urls, call, hedge_after_s: float) -> tuple[str, Any]:
        """Requêtes décalées : un serveur, puis le suivant si pas de réponse valide après `hedge_after_s`
        (ou dès un échec) ; la première réponse valide gagne. Les requêtes perdantes finissent en arrière-plan."""
        # Pool propre à cet appel, libéré sans attendre : une requête perdante (jusqu'à 90 s) ne bloque jamais
        # les appels suivants.
        pool = ThreadPoolExecutor(max_workers=len(urls), thread_name_prefix="hedge")
        try:
            pending: set[Future] = set()
            queue = list(urls)
            last: tuple[str, Any] = ("retry", "aucun serveur")
            while queue or pending:
                if queue:
                    pending.add(pool.submit(call, queue.pop(0)))
                done, pending = wait(pending, timeout=hedge_after_s if queue else None, return_when=FIRST_COMPLETED)
                for f in done:
                    kind, value = f.result()
                    if kind in {"ok", "fatal"}:
                        return kind, value
                    last = (kind, value)
            return last
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def request_json(
        self,
        method: str,
        urls: str | list[str],
        *,
        params: dict | None = None,
        data: dict | None = None,
        json_body: dict | None = None,
        ttl_s: float | None = 30 * DAY,
        service: str = "service externe",
        hedge_after_s: float | None = None,
        accept: Callable[[Any], str | None] | None = None,
        attempts: int | None = None,
    ) -> Any:
        """Appelle des serveurs équivalents ; `ttl_s=None` = cache sans expiration.

        - `hedge_after_s` : met les serveurs en concurrence (voir `_hedged`) au lieu de les essayer un par un ;
        - `accept(valeur)` : renvoie un message si une réponse 200 est en fait une erreur (ex. Overpass) ;
        - `attempts` : nombre de tours d'essais (défaut : `retries`), espacés de 1, 2, 4, 8, 8… s.
        La clé de cache ignore le serveur effectivement utilisé (les miroirs sont équivalents).
        """
        urls = [urls] if isinstance(urls, str) else urls
        key = self._cache_key(method, urls[0], [params, data, json_body])
        cached = self._cache_get(key, ttl_s)
        if cached is not None:
            return cached

        hosts = [urlsplit(u).hostname or u for u in urls]

        def call(url: str) -> tuple[str, Any]:
            return self._attempt(method, url, params, data, json_body, accept, service, hosts)

        last_error = ""
        attempts = attempts or self.retries
        for attempt in range(attempts):
            if hedge_after_s is not None and len(urls) > 1:
                outcomes = [self._hedged(urls, call, hedge_after_s)]
            else:
                outcomes = []
                for url in urls:
                    outcomes.append(call(url))
                    if outcomes[-1][0] in {"ok", "fatal"}:
                        break
            for kind, value in outcomes:
                if kind == "ok":
                    self._cache_put(key, value)
                    return value
                if kind == "fatal" or (kind == "slow" and attempt >= 1):
                    raise HttpError(value)  # « slow » deux fois de suite : la demande elle-même est en cause
                last_error = value
            if attempt < attempts - 1:
                self.sleep(min(2**attempt, MAX_BACKOFF_S))
        raise HttpError(f"{service} indisponible après {attempts} essais ({last_error}). Réessayer plus tard.")
