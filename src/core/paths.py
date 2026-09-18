"""Emplacement des ressources.

Tant qu'on lance `python app.py` depuis la racine du projet, des chemins comme
« data/openings » fonctionnent. Dès qu'une commande installée est appelée
depuis n'importe où, ils ne désignent plus rien.

Tout passe donc par ce module, qui repère la racine à partir de son propre
fichier et non du répertoire courant. Trois variables d'environnement
permettent de surcharger les emplacements pour une installation système.
"""

from __future__ import annotations

import os
from pathlib import Path

# src/core/paths.py -> src/core -> src -> racine
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resolve(variable: str, defaut: Path) -> Path:
    surcharge = os.environ.get(variable)
    return Path(surcharge).expanduser() if surcharge else defaut


def openings_dir() -> Path:
    """Base d'ouvertures Lichess (fichiers .tsv)."""
    return _resolve("CHESS_REVIEW_OPENINGS", PROJECT_ROOT / "data" / "openings")


def sounds_dir() -> Path:
    """Échantillons audio des coups."""
    return _resolve("CHESS_REVIEW_SOUNDS", PROJECT_ROOT / "assets" / "sounds")


def games_dir() -> Path:
    """PGN téléchargés. Créé à la demande."""
    chemin = _resolve("CHESS_REVIEW_GAMES", PROJECT_ROOT / "data" / "games")
    chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def icon_file(taille: int | None = None) -> Path:
    """Icône de l'application. Sans taille, le SVG ; sinon le PNG voulu."""
    dossier = _resolve("CHESS_REVIEW_ASSETS", PROJECT_ROOT / "assets")
    return dossier / (f"icon-{taille}.png" if taille else "icon.svg")


def env_file() -> Path:
    """Fichier .env, cherché à la racine du projet."""
    return _resolve("CHESS_REVIEW_ENV", PROJECT_ROOT / ".env")