"""Jeux de pièces.

python-chess embarque Cburnett et ne permet pas d'en changer : le SVG des
pièces est produit par `chess.svg.board()` en même temps que les cases. Pour
offrir le choix, on demande donc à python-chess un échiquier *vide* — cases,
coordonnées, surbrillances — et on dessine les pièces par-dessus, chacune
depuis son propre SVG.

Les fichiers ne sont pas embarqués dans le dépôt : scripts/fetch_pieces.py les
récupère. Sans eux, Cburnett fait office de repli et rien ne casse.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chess
import chess.svg
from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from src.core.paths import PROJECT_ROOT

# Nom de fichier attendu pour chaque pièce, convention Lichess.
CODES_FICHIERS = {
    (chess.WHITE, chess.PAWN): "wP",
    (chess.WHITE, chess.KNIGHT): "wN",
    (chess.WHITE, chess.BISHOP): "wB",
    (chess.WHITE, chess.ROOK): "wR",
    (chess.WHITE, chess.QUEEN): "wQ",
    (chess.WHITE, chess.KING): "wK",
    (chess.BLACK, chess.PAWN): "bP",
    (chess.BLACK, chess.KNIGHT): "bN",
    (chess.BLACK, chess.BISHOP): "bB",
    (chess.BLACK, chess.ROOK): "bR",
    (chess.BLACK, chess.QUEEN): "bQ",
    (chess.BLACK, chess.KING): "bK",
}

JEU_INTEGRE = "cburnett-builtin"


@dataclass(frozen=True)
class PieceSetInfo:
    key: str
    name: str
    author: str
    license: str


# Catalogue proposé au téléchargement. Les licences sont celles déclarées par
# Lichess : plusieurs sont non commerciales, d'où leur mention explicite.
JEUX_TELECHARGEABLES: dict[str, PieceSetInfo] = {
    "merida": PieceSetInfo(
        "merida", "Merida", "Armando Hernandez Marroquin", "GPLv2+"
    ),
    "chessnut": PieceSetInfo(
        "chessnut", "Chessnut", "Alexis Luengas", "Apache 2.0"
    ),
    "cburnett": PieceSetInfo(
        "cburnett", "Cburnett", "Colin M.L. Burnett", "GPLv2+"
    ),
    "alpha": PieceSetInfo(
        "alpha", "Alpha", "Eric Bentzen", "usage personnel non commercial"
    ),
    "staunty": PieceSetInfo("staunty", "Staunty", "sadsnake1", "CC BY-NC-SA 4.0"),
    "gioco": PieceSetInfo("gioco", "Gioco", "sadsnake1", "CC BY-NC-SA 4.0"),
    "fresca": PieceSetInfo("fresca", "Fresca", "sadsnake1", "CC BY-NC-SA 4.0"),
    "cardinal": PieceSetInfo("cardinal", "Cardinal", "sadsnake1", "CC BY-NC-SA 4.0"),
    "maestro": PieceSetInfo("maestro", "Maestro", "sadsnake1", "CC BY-NC-SA 4.0"),
    "california": PieceSetInfo(
        "california", "California", "Jerry S.", "CC BY-NC-SA 4.0"
    ),
    "tatiana": PieceSetInfo("tatiana", "Tatiana", "sadsnake1", "CC BY-NC-SA 4.0"),
    "governor": PieceSetInfo("governor", "Governor", "Armando Marroquin", "GPLv2+"),
}

INTEGRE = PieceSetInfo(
    JEU_INTEGRE, "Cburnett (intégré)", "Colin M.L. Burnett", "GPLv2+"
)


def pieces_dir() -> Path:
    """Dossier des jeux téléchargés."""
    import os

    surcharge = os.environ.get("CHESS_REVIEW_PIECES")
    return Path(surcharge).expanduser() if surcharge else PROJECT_ROOT / "assets" / "pieces"


def installed_sets() -> list[PieceSetInfo]:
    """Jeu intégré, puis ceux effectivement présents sur le disque."""
    disponibles = [INTEGRE]
    racine = pieces_dir()
    if not racine.is_dir():
        return disponibles

    for dossier in sorted(racine.iterdir()):
        if not dossier.is_dir():
            continue
        # Un jeu incomplet est pire qu'absent : des pièces disparaîtraient
        # silencieusement de l'échiquier.
        if not all(
            (dossier / f"{code}.svg").is_file() or (dossier / f"{code}.png").is_file()
            for code in CODES_FICHIERS.values()
        ):
            continue
        info = JEUX_TELECHARGEABLES.get(dossier.name)
        disponibles.append(
            info
            or PieceSetInfo(dossier.name, dossier.name.title(), "inconnu", "inconnue")
        )
    return disponibles


class PieceSet:
    """Fournit un QSvgRenderer par pièce, en les gardant en cache.

    Recharger un SVG à chaque case redessinée coûterait une trentaine de
    parsings XML par image ; ici il y en a douze au maximum, une fois.
    """

    def __init__(self, key: str = JEU_INTEGRE) -> None:
        self._key = key
        self._cache: dict[tuple[chess.Color, chess.PieceType], object] = {}
        self._dossier = pieces_dir() / key
        self._externe = key != JEU_INTEGRE and self._dossier.is_dir()

    @property
    def key(self) -> str:
        return self._key

    @property
    def uses_files(self) -> bool:
        return self._externe

    def draw(self, painter: QPainter, piece: chess.Piece, rect: QRectF) -> bool:
        """Dessine une pièce dans un rectangle. Rend False si elle manque.

        Les jeux Lichess sont en SVG, ceux extraits de chess-game-review en
        PNG : d'où deux chemins de rendu derrière une seule méthode, pour que
        l'appelant n'ait pas à connaître le format.
        """
        ressource = self._ressource(piece)
        if ressource is None:
            return False
        if isinstance(ressource, QPixmap):
            painter.drawPixmap(rect.toRect(), ressource)
        else:
            ressource.render(painter, rect)
        return True

    def _ressource(self, piece: chess.Piece):
        cle = (piece.color, piece.piece_type)
        cache = self._cache.get(cle)
        if cache is not None:
            return cache

        ressource = self._charger(piece)
        if ressource is not None:
            self._cache[cle] = ressource
        return ressource

    def _charger(self, piece: chess.Piece):
        if self._externe:
            code = CODES_FICHIERS[(piece.color, piece.piece_type)]

            png = self._dossier / f"{code}.png"
            if png.is_file():
                image = QPixmap(str(png))
                if not image.isNull():
                    return image

            svg = self._dossier / f"{code}.svg"
            if svg.is_file():
                moteur = QSvgRenderer()
                if moteur.load(QByteArray(svg.read_bytes())):
                    return moteur
            # Fichier illisible : on retombe sur l'intégré plutôt que de
            # laisser un trou sur l'échiquier.

        moteur = QSvgRenderer()
        if moteur.load(QByteArray(chess.svg.piece(piece).encode("utf-8"))):
            return moteur
        return None