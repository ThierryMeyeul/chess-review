"""Meilleures variantes du moteur pour la position affichée.

Trois lignes : évaluation à gauche, suite proposée à droite. Le contenu vient
du moteur d'analyse continue, pas du rapport enregistré — celui-ci ne stocke
que le meilleur coup, et conserver trois variantes par position multiplierait
la taille de la base sans grand profit.

Conséquence assumée : le panneau se remplit avec une fraction de seconde de
retard sur la navigation, et reste vide si le moteur continu est indisponible.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGridLayout, QLabel, QSizePolicy, QWidget

NOMBRE_LIGNES = 3


class LinesPanel(QWidget):
    """Tableau des variantes principales."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        self._evaluations: list[QLabel] = []
        self._variantes: list[QLabel] = []

        grille = QGridLayout(self)
        grille.setContentsMargins(0, 0, 0, 0)
        grille.setHorizontalSpacing(8)
        grille.setVerticalSpacing(4)
        grille.setColumnStretch(1, 1)

        police_eval = QFont("monospace")
        police_eval.setBold(True)
        police_variante = QFont("monospace")

        for ligne in range(NOMBRE_LIGNES):
            evaluation = QLabel("")
            evaluation.setFont(police_eval)
            evaluation.setAlignment(Qt.AlignmentFlag.AlignCenter)
            evaluation.setFixedWidth(54)
            evaluation.setObjectName("chipEval")

            variante = QLabel("")
            variante.setFont(police_variante)
            # Une variante longue ne doit pas élargir la colonne : on tronque.
            variante.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            variante.setMinimumWidth(0)
            variante.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )

            grille.addWidget(evaluation, ligne, 0)
            grille.addWidget(variante, ligne, 1)
            self._evaluations.append(evaluation)
            self._variantes.append(variante)

        self.clear()

    # -- API --------------------------------------------------------------

    def clear(self) -> None:
        for evaluation, variante in zip(self._evaluations, self._variantes):
            evaluation.setText("—")
            variante.setText("")

    def set_lines(self, lignes: tuple[tuple[str, str], ...]) -> None:
        for index in range(NOMBRE_LIGNES):
            if index < len(lignes):
                evaluation, variante = lignes[index]
                self._evaluations[index].setText(evaluation)
                self._variantes[index].setText(variante)
                self._variantes[index].setToolTip(variante)
            else:
                self._evaluations[index].setText("—")
                self._variantes[index].setText("")
                self._variantes[index].setToolTip("")