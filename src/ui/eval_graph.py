"""Graphe d'évaluation de la partie.

Une aire dont la frontière suit la probabilité de victoire des blancs : zone
claire en bas, sombre en haut. La courbe porte un point coloré par coup, et un
curseur marque la position affichée.

La hauteur suit la probabilité de victoire et non les centipions, pour la même
raison que la jauge verticale : en centipions, la courbe serait collée en butée
dès qu'un camp a une pièce d'avance et ne montrerait plus rien.

Cliquer ou faire glisser déplace la partie — c'est le moyen le plus rapide de
sauter à l'endroit où tout a basculé.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from src.core.classify import GameReport, MoveClass
from src.core.engine import win_probability
from src.ui.board_widget import COULEURS_BADGE

HAUTEUR = 62
RAYON_POINT = 2.6
RAYON_POINT_ACTIF = 4.2

# Catégories sans intérêt visuel : les afficher noierait les autres sous une
# masse de points verts.
SANS_POINT = frozenset(
    {MoveClass.BEST, MoveClass.EXCELLENT, MoveClass.GOOD, MoveClass.FORCED}
)


@dataclass(frozen=True)
class PointCourbe:
    ply: int
    proportion: float  # 0..1, part revenant aux blancs
    classification: MoveClass | None
    san: str


class EvalGraph(QWidget):
    """Courbe d'évaluation, un point par demi-coup."""

    ply_selected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(HAUTEUR)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._points: list[PointCourbe] = []
        self._ply = 0
        self._survol: int | None = None
        self._couleurs = {
            "clair": "#F0F0F0",
            "sombre": "#2E2E2B",
            "milieu": "#00000033",
            "curseur": "#4E9BE6",
        }

    # -- API --------------------------------------------------------------

    def set_colors(self, clair: str, sombre: str, curseur: str) -> None:
        self._couleurs.update(clair=clair, sombre=sombre, curseur=curseur)
        self.update()

    def set_report(self, report: GameReport | None) -> None:
        """Alimente la courbe. `None` la vide."""
        self._points = []
        if report is not None:
            # Le demi-coup 0 est la position de départ : équilibre par
            # convention, sinon la courbe démarrerait dans le vide.
            self._points.append(PointCourbe(0, 0.5, None, ""))
            for coup in report.moves:
                apres = coup.analysis.after
                issue = apres.outcome_white
                proportion = (
                    issue if issue is not None else win_probability(apres.cp_white)
                )
                self._points.append(
                    PointCourbe(
                        ply=coup.analysis.ply,
                        proportion=max(0.02, min(0.98, proportion)),
                        classification=coup.classification,
                        san=coup.san,
                    )
                )
        self.update()

    def set_ply(self, ply: int) -> None:
        self._ply = ply
        self.update()

    @property
    def has_data(self) -> bool:
        return len(self._points) > 1

    # -- géométrie --------------------------------------------------------

    def _x(self, index: int) -> float:
        if len(self._points) < 2:
            return 0.0
        return index * (self.width() - 1) / (len(self._points) - 1)

    def _y(self, proportion: float) -> float:
        # Plus les blancs vont bien, plus la frontière monte.
        return self.height() * (1.0 - proportion)

    def _index_au_point(self, x: float) -> int:
        if len(self._points) < 2:
            return 0
        pas = (self.width() - 1) / (len(self._points) - 1)
        return max(0, min(len(self._points) - 1, round(x / pas)))

    # -- interactions -----------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if not self.has_data:
            return
        index = self._index_au_point(event.position().x())
        self.ply_selected.emit(self._points[index].ply)

    def mouseMoveEvent(self, event) -> None:
        if not self.has_data:
            return
        if event.buttons() & Qt.MouseButton.LeftButton:
            index = self._index_au_point(event.position().x())
            self.ply_selected.emit(self._points[index].ply)
            return

        index = self._index_au_point(event.position().x())
        if index != self._survol:
            self._survol = index
            point = self._points[index]
            if point.san:
                etiquette = point.san
                if point.classification is not None:
                    etiquette += f" — {point.classification.label}"
                QToolTip.showText(event.globalPosition().toPoint(), etiquette, self)
            self.update()

    def leaveEvent(self, event) -> None:
        self._survol = None
        self.update()

    # -- rendu ------------------------------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        largeur, hauteur = float(self.width()), float(self.height())
        painter.fillRect(
            QRectF(0, 0, largeur, hauteur), QColor(self._couleurs["sombre"])
        )

        if not self.has_data:
            painter.end()
            return

        # Aire claire sous la courbe.
        chemin = QPainterPath()
        chemin.moveTo(0.0, hauteur)
        for index, point in enumerate(self._points):
            chemin.lineTo(self._x(index), self._y(point.proportion))
        chemin.lineTo(largeur, hauteur)
        chemin.closeSubpath()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(self._couleurs["clair"])))
        painter.drawPath(chemin)

        # Ligne d'équilibre : sans elle, les petits écarts sont illisibles.
        painter.setPen(QPen(QColor(self._couleurs["milieu"]), 1.0))
        painter.drawLine(QPointF(0, hauteur / 2), QPointF(largeur, hauteur / 2))

        self._draw_points(painter)
        self._draw_curseur(painter, hauteur)
        painter.end()

    def _draw_points(self, painter: QPainter) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        for index, point in enumerate(self._points):
            if point.classification is None or point.classification in SANS_POINT:
                continue
            couleur = QColor(COULEURS_BADGE[point.classification])
            actif = index == self._survol or point.ply == self._ply
            rayon = RAYON_POINT_ACTIF if actif else RAYON_POINT

            centre = QPointF(self._x(index), self._y(point.proportion))
            if actif:
                painter.setPen(QPen(QColor("#FFFFFF"), 1.5))
            else:
                painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(couleur)
            painter.drawEllipse(centre, rayon, rayon)

    def _draw_curseur(self, painter: QPainter, hauteur: float) -> None:
        index = next(
            (i for i, p in enumerate(self._points) if p.ply == self._ply), None
        )
        if index is None:
            return
        x = self._x(index)
        painter.setPen(QPen(QColor(self._couleurs["curseur"]), 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawLine(QPointF(x, 0), QPointF(x, hauteur))

    def sizeHint(self) -> QSize:
        return QSize(520, HAUTEUR)