"""Bandeau des pièces perdues.

Deux exemplaires encadrent l'échiquier, l'un pour chaque camp, et suivent son
orientation.

Convention chess.com : les pièces alignées à côté d'un joueur sont celles qu'il
a *prises* à l'adversaire, pas celles qu'il a perdues. Elles sont dessinées
avec le jeu de pièces choisi, et non en caractères Unicode : les glyphes
typographiques ne ressemblent à rien à cette taille et ne suivent pas le thème.

Les pièces d'un même type se chevauchent, comme sur une pile de prises — sinon
une série de huit pions déborderait de la colonne.
"""

from __future__ import annotations

import chess
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from src.core.material import ORDRE_AFFICHAGE, Captures
from src.ui.pieces import JEU_INTEGRE, PieceSet

HAUTEUR = 30
TAILLE_PIECE = 26
# Fraction de la largeur d'une pièce avant de poser la suivante du même type.
CHEVAUCHEMENT = 0.58
ECART_GROUPES = 0.28


class _BandePieces(QWidget):
    """Suite de pièces dessinées, du plus fort au plus faible."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(HAUTEUR)
        # Largeur calée sur le contenu : sinon la bande s'étire et repousse
        # l'avantage matériel à l'autre bout de la ligne.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self._captures: Captures | None = None
        self._piece_set = PieceSet(JEU_INTEGRE)

    def set_piece_set(self, key: str) -> None:
        self._piece_set = PieceSet(key)
        self.update()

    def set_captures(self, captures: Captures | None) -> None:
        self._captures = captures
        self.updateGeometry()  # la largeur dépend du nombre de pièces
        self.update()

    def _largeur_contenu(self) -> float:
        if self._captures is None or not self._captures.pieces:
            return 0.0
        taille = min(TAILLE_PIECE, float(self.height()))
        largeur = 0.0
        for piece_type in ORDRE_AFFICHAGE:
            nombre = self._captures.pieces.get(piece_type, 0)
            if not nombre:
                continue
            largeur += nombre * taille * CHEVAUCHEMENT + taille * ECART_GROUPES
        # La dernière pièce est entière, pas seulement sa portion visible.
        return largeur + taille * (1.0 - CHEVAUCHEMENT)

    def paintEvent(self, event) -> None:
        if self._captures is None or not self._captures.pieces:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        taille = min(TAILLE_PIECE, float(self.height()))
        y = (self.height() - taille) / 2.0
        x = 0.0

        for piece_type in ORDRE_AFFICHAGE:
            nombre = self._captures.pieces.get(piece_type, 0)
            if not nombre:
                continue
            piece = chess.Piece(piece_type, self._captures.color)
            for _ in range(nombre):
                self._piece_set.draw(painter, piece, QRectF(x, y, taille, taille))
                x += taille * CHEVAUCHEMENT
            x += taille * ECART_GROUPES

        painter.end()

    def sizeHint(self) -> QSize:
        return QSize(int(self._largeur_contenu()), HAUTEUR)

    def minimumSizeHint(self) -> QSize:
        return QSize(0, HAUTEUR)


class CapturedWidget(QWidget):
    """Nom du joueur, pièces qu'il a prises, et son avantage éventuel."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(HAUTEUR)

        self.label_nom = QLabel("—")
        police_nom = QFont(self.font())
        police_nom.setBold(True)
        self.label_nom.setFont(police_nom)

        self.bande = _BandePieces()

        self.label_avantage = QLabel("")
        police_avantage = QFont(self.font())
        police_avantage.setBold(True)
        self.label_avantage.setFont(police_avantage)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)
        layout.addWidget(self.label_nom)
        layout.addWidget(self.bande)
        layout.addWidget(self.label_avantage)
        layout.addStretch()

    # -- API --------------------------------------------------------------

    def set_player(self, nom: str, elo: int = 0) -> None:
        self.label_nom.setText(f"{nom} ({elo})" if elo else nom)

    def set_piece_set(self, key: str) -> None:
        self.bande.set_piece_set(key)

    def set_captures(self, captures: Captures, avantage: int) -> None:
        """`avantage` est la différence de matériel, du point de vue de ce camp.

        Seul le camp qui mène affiche un nombre : montrer « +3 » d'un côté et
        « −3 » de l'autre serait redondant et rendrait la lecture ambiguë.
        """
        self.bande.set_captures(captures)
        self.label_avantage.setText(f"+{avantage}" if avantage > 0 else "")

    def clear(self) -> None:
        self.bande.set_captures(None)
        self.label_avantage.setText("")

    def sizeHint(self) -> QSize:
        return QSize(320, HAUTEUR)


def apply_summary(
    haut: CapturedWidget,
    bas: CapturedWidget,
    board: chess.Board,
    flipped: bool,
    root: chess.Board | None = None,
) -> None:
    """Met à jour les deux bandeaux selon l'orientation de l'échiquier.

    Ce qu'un joueur a pris, ce sont les pertes de l'autre : le bandeau des
    blancs affiche donc `pertes_noires`.
    """
    from src.core.material import summary

    pertes_blanches, pertes_noires, difference = summary(board, root)

    prises_des_blancs = (pertes_noires, difference if difference > 0 else 0)
    prises_des_noirs = (pertes_blanches, -difference if difference < 0 else 0)

    # Sans retournement, les blancs occupent le bas de l'échiquier.
    if flipped:
        haut.set_captures(*prises_des_blancs)
        bas.set_captures(*prises_des_noirs)
    else:
        haut.set_captures(*prises_des_noirs)
        bas.set_captures(*prises_des_blancs)