"""Bibliothèque des parties enregistrées.

Lecture seule sur la base, plus la suppression. La recherche porte sur les
joueurs et l'ouverture — c'est ce qu'on retient d'une partie, pas sa date.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.core.database import DatabaseError, Game, GameRepository


class LibraryDialog(QDialog):
    """Liste des parties en base, avec recherche et suppression."""

    game_chosen = Signal(int)

    def __init__(self, depot: GameRepository, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bibliothèque")
        self.resize(760, 520)
        self._depot = depot
        self._parties: list[Game] = []
        self._build_ui()
        self.recharger()

    def _build_ui(self) -> None:
        self.edit_recherche = QLineEdit()
        self.edit_recherche.setPlaceholderText("Joueur ou ouverture…")
        self.edit_recherche.setClearButtonEnabled(True)
        self.edit_recherche.textChanged.connect(lambda _: self.recharger())

        self.btn_supprimer = QPushButton("Supprimer")
        self.btn_supprimer.clicked.connect(self._supprimer)

        haut = QHBoxLayout()
        haut.addWidget(self.edit_recherche, stretch=1)
        haut.addWidget(self.btn_supprimer)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Blancs", "Noirs", "Ouverture", "Analysée"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.doubleClicked.connect(lambda _: self.accept())
        self.table.itemSelectionChanged.connect(self._maj_boutons)

        entete = self.table.horizontalHeader()
        entete.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        self.label_statut = QLabel(" ")
        self.label_statut.setObjectName("sousTitre")

        self.boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Close
        )
        self.boutons.button(QDialogButtonBox.StandardButton.Open).setText("Ouvrir")
        self.boutons.button(QDialogButtonBox.StandardButton.Open).setObjectName(
            "primaire"
        )
        self.boutons.accepted.connect(self.accept)
        self.boutons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(haut)
        layout.addWidget(self.table, stretch=1)
        layout.addWidget(self.label_statut)
        layout.addWidget(self.boutons)

        self._maj_boutons()

    # -- données ----------------------------------------------------------

    def recharger(self) -> None:
        try:
            self._parties = self._depot.list_games(
                limit=300, search=self.edit_recherche.text().strip()
            )
        except DatabaseError as exc:
            self.label_statut.setText(str(exc))
            return

        self.table.setRowCount(len(self._parties))
        for ligne, partie in enumerate(self._parties):
            date = partie.played_at.strftime("%Y-%m-%d") if partie.played_at else "—"
            valeurs = [
                date,
                f"{partie.white} ({partie.white_rating})"
                if partie.white_rating
                else partie.white,
                f"{partie.black} ({partie.black_rating})"
                if partie.black_rating
                else partie.black,
                f"{partie.eco} {partie.opening}".strip() or "—",
                "✓" if partie.analysed else "",
            ]
            for colonne, valeur in enumerate(valeurs):
                cellule = QTableWidgetItem(valeur)
                if colonne == 4 and valeur:
                    cellule.setForeground(QBrush(QColor("#95BB4A")))
                    cellule.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(ligne, colonne, cellule)

        self.table.resizeColumnsToContents()
        entete = self.table.horizontalHeader()
        entete.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.label_statut.setText(f"{len(self._parties)} partie(s)")
        if self._parties:
            self.table.selectRow(0)
        self._maj_boutons()

    def _maj_boutons(self) -> None:
        actif = self.selected_id() is not None
        self.boutons.button(QDialogButtonBox.StandardButton.Open).setEnabled(actif)
        self.btn_supprimer.setEnabled(actif)

    def selected_id(self) -> int | None:
        ligne = self.table.currentRow()
        if 0 <= ligne < len(self._parties):
            return self._parties[ligne].id
        return None

    def _supprimer(self) -> None:
        identifiant = self.selected_id()
        if identifiant is None:
            return
        reponse = QMessageBox.question(
            self,
            "Supprimer",
            "Supprimer cette partie et son analyse ? L'opération est définitive.",
        )
        if reponse != QMessageBox.StandardButton.Yes:
            return
        try:
            self._depot.delete_game(identifiant)
        except DatabaseError as exc:
            self.label_statut.setText(str(exc))
            return
        self.recharger()