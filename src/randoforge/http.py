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
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from . import __version__

USER_AGENT = f"RandoForge/{__version__} (+https://github.com/LaMachiiine/randoforge)"
RETRYABLE = {429, 500, 502, 503, 504}

DAY = 86_400.0


class HttpError(Exception):
    """Échec d'un appel externe, avec un message compréhensible par Claude."""


class CachedHttp:
    def __init__(
        self,
        cache_path: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        retries: int = 3,
        min_interval_s: dict[str, float] | None = None,
    ):
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=90, transport=transport, follow_redirects=True
        )
        self.sleep = sleep
        self.retries = retries
        # Délai minimal entre deux appels à un même hôte (ex. Nominatim : 1 req/s).
        self.min_interval_s = min_interval_s or {"nominatim.openstreetmap.org": 1.1}
        self._last_call: dict[str, float] = {}
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

    def _throttle(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        interval = self.min_interval_s.get(host)
        if interval:
            wait = self._last_call.get(host, 0) + interval - time.time()
            if wait > 0:
                self.sleep(wait)
            self._last_call[host] = time.time()

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
    ) -> Any:
        """Appelle le premier serveur qui répond ; `ttl_s=None` = cache sans expiration.

        La clé de cache ignore le serveur effectivement utilisé (les miroirs sont équivalents).
        """
        urls = [urls] if isinstance(urls, str) else urls
        key = self._cache_key(method, urls[0], [params, data, json_body])
        cached = self._cache_get(key, ttl_s)
        if cached is not None:
            return cached

        last_error = ""
        for attempt in range(self.retries):
            for url in urls:
                self._throttle(url)
                try:
                    r = self.client.request(method, url, params=params, data=data, json=json_body)
                except httpx.TransportError as exc:
                    last_error = f"{urlsplit(url).hostname} injoignable ({type(exc).__name__})"
                    continue
                if r.status_code == 200:
                    try:
                        value = r.json()
                    except ValueError:
                        last_error = f"{urlsplit(url).hostname} a renvoyé une réponse non JSON"
                        continue
                    self._cache_put(key, value)
                    return value
                body = r.text.strip().replace("\n", " ")[:300]
                if r.status_code not in RETRYABLE:
                    raise HttpError(f"{service} : erreur {r.status_code} — {body}")
                last_error = f"{urlsplit(url).hostname} : {r.status_code}"
            if attempt < self.retries - 1:
                self.sleep(2**attempt)
        raise HttpError(f"{service} indisponible après {self.retries} essais ({last_error}). Réessayer plus tard.")
