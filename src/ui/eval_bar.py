"""Barre d'évaluation verticale.

La hauteur de la partie blanche suit la probabilité de victoire, pas les
centipions. C'est ce que fait chess.com, et c'est le bon choix : une barre
linéaire en centipions serait collée en butée dès qu'un camp a une pièce
d'avance, et ne montrerait plus rien pendant tout le reste de la partie.

La barre se cale sur le carré réellement dessiné par l'échiquier. Sans ça elle
occupe toute la hauteur de la colonne alors que l'échiquier n'en est qu'un
carré centré : les deux ne s'alignent qu'au hasard des proportions de fenêtre.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.core.engine import win_probability

LARGEUR = 28
COULEUR_BLANC = "#F0F0F0"
COULEUR_NOIR = "#403D39"
COULEUR_NEUTRE = "#6E6A64"
COULEUR_REPERE = "#00000055"

# Bornes : un camp écrasé garde un filet visible, sinon « gagné » et « mat
# en 2 » se ressemblent. Un mat annoncé, lui, remplit la barre entièrement —
# c'est la seule situation où il n'y a plus rien à nuancer.
MINIMUM = 0.03
MAXIMUM = 0.97

DUREE_ANIMATION_MS = 220


class EvalBar(QWidget):
    """Jauge blancs/noirs, alignée sur l'échiquier et orientée comme lui."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(LARGEUR)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self._cp: int | None = None
        self._mate: int | None = None
        self._result: float | None = None
        self._flipped = False
        self._board_widget: QWidget | None = None

        # La barre démarre à l'équilibre plutôt qu'à une extrémité : une
        # jauge qui bondit de zéro à sa valeur au premier coup est illisible.
        self._proportion_affichee = 0.5
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(DUREE_ANIMATION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_anim_value)
        self._animate = True

    # -- API --------------------------------------------------------------

    def set_board(self, widget: QWidget) -> None:
        """Associe l'échiquier dont la barre doit épouser la hauteur.

        Les deux widgets sont dans la même rangée, donc la même hauteur : il
        suffit de refaire le même calcul de carré centré pour tomber pile en
        face des cases.
        """
        self._board_widget = widget

    def set_evaluation(
        self,
        cp_white: int | None,
        mate: int | None = None,
        result: float | None = None,
    ) -> None:
        """Évaluation en centipions du point de vue des blancs.

        Priorité décroissante : `result` (partie terminée), `mate` (mat
        annoncé), puis `cp_white`. `None` partout remet la jauge à l'équilibre
        et masque le chiffre.
        """
        self._cp = cp_white
        self._mate = mate
        self._result = result
        self._glisser_vers(self._proportion_cible())

    def set_animate(self, actif: bool) -> None:
        self._animate = actif
        if not actif:
            self._animation.stop()
            self._proportion_affichee = self._proportion_cible()
            self.update()

    # -- animation --------------------------------------------------------

    def _glisser_vers(self, cible: float) -> None:
        self._animation.stop()
        if not self._animate or abs(cible - self._proportion_affichee) < 0.001:
            self._proportion_affichee = cible
            self.update()
            return
        self._animation.setStartValue(float(self._proportion_affichee))
        self._animation.setEndValue(float(cible))
        self._animation.start()

    def _on_anim_value(self, valeur) -> None:
        self._proportion_affichee = float(valeur)
        self.update()

    def set_flipped(self, flipped: bool) -> None:
        self._flipped = flipped
        self.update()

    def clear(self) -> None:
        self.set_evaluation(None)

    # -- géométrie --------------------------------------------------------

    def _bande(self) -> tuple[float, float]:
        """Position et hauteur de la zone utile, calée sur l'échiquier."""
        hauteur = float(self.height())
        if self._board_widget is None:
            return 0.0, hauteur
        cote = float(min(self._board_widget.width(), self._board_widget.height()))
        if cote <= 0:
            return 0.0, hauteur
        haut = (self._board_widget.height() - cote) / 2.0
        return haut, cote

    def _proportion_cible(self) -> float:
        """Proportion visée. Un mat sature la barre du côté du mateur."""
        if self._result is not None:
            return self._result
        if self._mate is not None:
            return 1.0 if self._mate > 0 else 0.0
        if self._cp is None:
            return 0.5
        return max(MINIMUM, min(MAXIMUM, win_probability(self._cp)))

    def _texte(self) -> str:
        if self._result is not None:
            return {1.0: "1-0", 0.0: "0-1"}.get(self._result, "½")
        if self._mate is not None:
            return f"M{abs(self._mate)}"
        if self._cp is None:
            return ""
        valeur = abs(self._cp) / 100.0
        # Sous 10 pions on garde deux décimales : c'est là que se joue la
        # lecture fine d'une partie, et 0.3 contre 0.7 doit se distinguer.
        return f"{valeur:.2f}" if valeur < 10 else f"{valeur:.0f}"

    # -- rendu ------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        largeur = float(self.width())
        haut, hauteur = self._bande()
        proportion = self._proportion_affichee

        painter.fillRect(QRectF(0, haut, largeur, hauteur), QColor(COULEUR_NOIR))

        part = hauteur * proportion
        rect = (
            QRectF(0, haut, largeur, part)
            if self._flipped
            else QRectF(0, haut + hauteur - part, largeur, part)
        )
        painter.fillRect(rect, QColor(COULEUR_BLANC))

        # Repère d'équilibre : sans lui, un écart de quelques pourcents est
        # indétectable et la barre paraît figée.
        milieu = haut + hauteur / 2.0
        painter.setPen(QPen(QColor(COULEUR_REPERE), 1.0))
        painter.drawLine(QPointF(0, milieu), QPointF(largeur, milieu))

        texte = self._texte()
        if not texte:
            painter.end()
            return

        blancs_devant = self._proportion_cible() > 0.5 or (
            self._proportion_cible() == 0.5 and self._result is None
        )
        police = QFont(self.font())
        police.setBold(True)
        police.setPointSizeF(max(6.0, largeur * 0.30))
        painter.setFont(police)
        painter.setPen(QColor(COULEUR_NOIR if blancs_devant else COULEUR_BLANC))

        en_bas = blancs_devant != self._flipped
        zone = (
            QRectF(0, haut + hauteur - 20, largeur, 18)
            if en_bas
            else QRectF(0, haut + 2, largeur, 18)
        )
        painter.drawText(zone, Qt.AlignmentFlag.AlignCenter, texte)
        painter.end()

    def sizeHint(self) -> QSize:
        return QSize(LARGEUR, 560)