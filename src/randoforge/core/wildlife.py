"""Faune à connaître parmi les espèces observées (calcul pur sur les noms scientifiques)."""

from __future__ import annotations

# Espèces signalées à part, par genre ou espèce (nom scientifique) : le fait seulement, pas de consigne.
NOTABLE = {
    "Vipera": "vipère, venimeuse",
    "Canis lupus": "loup, grand prédateur très discret",
    "Ursus arctos": "ours brun, grand prédateur très discret",
    "Lynx lynx": "lynx, grand prédateur très discret",
}


def notable(scientific: str) -> str | None:
    for key, label in NOTABLE.items():
        if scientific == key or scientific.startswith(key + " "):
            return label
    return None


def month_window(month: int) -> tuple[int, int]:
    """Mois de la sortie et ses voisins (sans passer d'une année à l'autre : décembre → novembre–décembre)."""
    return max(1, month - 1), min(12, month + 1)
