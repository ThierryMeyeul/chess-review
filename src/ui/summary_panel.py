"""Récapitulatif d'une analyse.

Précision des deux camps, puis le décompte des badges. Seules les catégories
effectivement rencontrées sont affichées : montrer dix lignes dont sept à zéro
occupe la place sans rien apprendre.
"""

from __future__ import annotations

import chess
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.classify import GameReport, MoveClass
from src.ui.badges import BadgeIcons
from src.ui.board_widget import COULEURS_BADGE, GLYPHES_BADGE

# Ordre d'affichage, du meilleur au pire.
ORDRE = (
    MoveClass.BRILLIANT,
    MoveClass.GREAT,
    MoveClass.BEST,
    MoveClass.EXCELLENT,
    MoveClass.GOOD,
    MoveClass.BOOK,
    MoveClass.FORCED,
    MoveClass.INACCURACY,
    MoveClass.MISTAKE,
    MoveClass.MISS,
    MoveClass.BLUNDER,
)

TAILLE_ICONE = 16


class SummaryPanel(QWidget):
    """Précisions et décompte des badges, une colonne par camp."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._badges = BadgeIcons()
        self._pixmaps: dict[MoveClass, QPixmap | None] = {}

        self.label_blancs = QLabel("—")
        self.label_noirs = QLabel("—")
        for etiquette in (self.label_blancs, self.label_noirs):
            etiquette.setObjectName("grandChiffre")
            etiquette.setAlignment(Qt.AlignmentFlag.AlignCenter)

        titre_blancs = QLabel("Blancs")
        titre_noirs = QLabel("Noirs")
        for etiquette in (titre_blancs, titre_noirs):
            etiquette.setObjectName("sousTitre")
            etiquette.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.grille = QGridLayout()
        self.grille.setContentsMargins(0, 6, 0, 0)
        self.grille.setHorizontalSpacing(10)
        self.grille.setVerticalSpacing(3)
        self.grille.setColumnStretch(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        entete = QGridLayout()
        entete.setContentsMargins(0, 0, 0, 0)
        entete.addWidget(titre_blancs, 0, 0)
        entete.addWidget(titre_noirs, 0, 1)
        entete.addWidget(self.label_blancs, 1, 0)
        entete.addWidget(self.label_noirs, 1, 1)
        layout.addLayout(entete)
        layout.addLayout(self.grille)

        self.clear()

    # -- API --------------------------------------------------------------

    def clear(self) -> None:
        self.label_blancs.setText("—")
        self.label_noirs.setText("—")
        self._vider_grille()

    def set_report(self, report: GameReport | None) -> None:
        if report is None:
            self.clear()
            return

        self.label_blancs.setText(f"{report.white.accuracy:.1f} %")
        self.label_noirs.setText(f"{report.black.accuracy:.1f} %")
        self._vider_grille()

        blancs = report.white.counts
        noirs = report.black.counts
        ligne = 0
        for classification in ORDRE:
            n_blanc = blancs.get(classification, 0)
            n_noir = noirs.get(classification, 0)
            if not n_blanc and not n_noir:
                continue
            self._ajouter_ligne(ligne, classification, n_blanc, n_noir)
            ligne += 1

    # -- construction -----------------------------------------------------

    def _vider_grille(self) -> None:
        while self.grille.count():
            element = self.grille.takeAt(0)
            widget = element.widget()
            if widget is not None:
                widget.deleteLater()

    def _ajouter_ligne(
        self, ligne: int, classification: MoveClass, n_blanc: int, n_noir: int
    ) -> None:
        couleur = COULEURS_BADGE[classification]

        icone = QLabel()
        pixmap = self._pixmap(classification)
        if pixmap is not None:
            icone.setPixmap(pixmap)
        else:
            icone.setText(GLYPHES_BADGE.get(classification, "•"))
            icone.setStyleSheet(f"color: {couleur}; font-weight: 700;")
        icone.setFixedWidth(TAILLE_ICONE + 2)
        icone.setAlignment(Qt.AlignmentFlag.AlignCenter)

        nom = QLabel(classification.label)
        nom.setStyleSheet(f"color: {couleur};")

        gras = QFont(self.font())
        gras.setBold(True)

        compte_blanc = QLabel(str(n_blanc))
        compte_noir = QLabel(str(n_noir))
        for etiquette in (compte_blanc, compte_noir):
            etiquette.setFont(gras)
            etiquette.setAlignment(Qt.AlignmentFlag.AlignCenter)
            etiquette.setFixedWidth(34)

        self.grille.addWidget(compte_blanc, ligne, 0)
        self.grille.addWidget(icone, ligne, 1, Qt.AlignmentFlag.AlignRight)
        self.grille.addWidget(nom, ligne, 2)
        self.grille.addWidget(compte_noir, ligne, 3)
        self.grille.setColumnStretch(2, 1)

    def _pixmap(self, classification: MoveClass) -> QPixmap | None:
        """Icône convertie une fois, gardée en cache."""
        if classification in self._pixmaps:
            return self._pixmaps[classification]

        moteur = self._badges.renderer(classification)
        pixmap: QPixmap | None = None
        if moteur is not None:
            pixmap = QPixmap(QSize(TAILLE_ICONE, TAILLE_ICONE))
            pixmap.fill(Qt.GlobalColor.transparent)
            peintre = QPainter(pixmap)
            peintre.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            moteur.render(peintre)
            peintre.end()

        self._pixmaps[classification] = pixmap
        return pixmap