"""Icônes des badges de classification.

Les symboles texte (« ?! », « ★ ») restent le repli : ils ne dépendent d'aucune
ressource et fonctionnent toujours. Quand les icônes ont été installées par
scripts/fetch_cgr_assets.py, elles prennent la place.

Les fichiers ne sont pas embarqués dans le dépôt — voir la note de licence du
script d'extraction.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtSvg import QSvgRenderer

from src.core.classify import MoveClass
from src.core.paths import PROJECT_ROOT


def badges_dir() -> Path:
    import os

    surcharge = os.environ.get("CHESS_REVIEW_BADGES")
    return Path(surcharge).expanduser() if surcharge else PROJECT_ROOT / "assets" / "badges"


class BadgeIcons:
    """Cache d'icônes, une par catégorie de coup."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dossier = directory or badges_dir()
        self._cache: dict[MoveClass, QSvgRenderer | None] = {}

    @property
    def available(self) -> bool:
        return self._dossier.is_dir() and any(self._dossier.glob("*.svg"))

    def renderer(self, classification: MoveClass) -> QSvgRenderer | None:
        """Rend l'icône, ou None s'il faut retomber sur le symbole texte."""
        if classification in self._cache:
            return self._cache[classification]

        fichier = self._dossier / f"{classification.value}.svg"
        moteur: QSvgRenderer | None = None
        if fichier.is_file():
            candidat = QSvgRenderer(str(fichier))
            # Un SVG illisible doit se comporter comme un fichier absent :
            # sinon la pastille disparaît sans que rien ne la remplace.
            if candidat.isValid():
                moteur = candidat

        self._cache[classification] = moteur
        return moteur