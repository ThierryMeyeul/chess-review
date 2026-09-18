"""Sélection d'une partie depuis chess.com.

L'appel réseau ne doit pas plus tourner dans le thread graphique que l'analyse
Stockfish : sur une connexion lente, télécharger six mois d'archives fige la
fenêtre pendant plusieurs secondes. Même remède qu'ailleurs, un QThread et des
signaux.

Le pseudo et les filtres sont conservés d'une session à l'autre via QSettings :
personne n'a envie de retaper son pseudo à chaque fois.
"""

from __future__ import annotations

import chess
from PySide6.QtCore import QObject, QSettings, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from src.core.fetch import ChessComClient, ChessComError, GameSummary

ORGANISATION = "chess-review"
APPLICATION = "chess-review"

CADENCES = (
    ("Toutes", None),
    ("Rapide", ["rapid"]),
    ("Blitz", ["blitz"]),
    ("Bullet", ["bullet"]),
    ("Par jour", ["daily"]),
)


class FetchWorker(QObject):
    """Télécharge les parties. Vit dans son propre thread."""

    finished = Signal(object)  # list[GameSummary]
    failed = Signal(str)

    def __init__(
        self,
        username: str,
        limit: int,
        time_classes: list[str] | None,
        rated_only: bool,
        user_agent: str,
    ) -> None:
        super().__init__()
        self._username = username
        self._limit = limit
        self._time_classes = time_classes
        self._rated_only = rated_only
        self._user_agent = user_agent

    @Slot()
    def run(self) -> None:
        try:
            client = ChessComClient(user_agent=self._user_agent)
            parties = client.recent_games(
                self._username,
                limit=self._limit,
                time_classes=self._time_classes,
                rated_only=self._rated_only,
            )
            self.finished.emit(parties)
        except ChessComError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # ne jamais mourir en silence dans un thread
            self.failed.emit(f"Erreur inattendue : {exc}")


class ChessComDialog(QDialog):
    """Saisie du pseudo, liste des parties, sélection."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Récupérer une partie sur chess.com")
        self.resize(640, 480)

        self._settings = QSettings(ORGANISATION, APPLICATION)
        self._parties: list[GameSummary] = []
        self._thread: QThread | None = None
        self._worker: FetchWorker | None = None

        self._build_ui()
        self._restore()

    # -- interface --------------------------------------------------------

    def _build_ui(self) -> None:
        self.edit_pseudo = QLineEdit()
        self.edit_pseudo.setPlaceholderText("ton pseudo chess.com")
        self.edit_pseudo.returnPressed.connect(self._chercher)

        self.combo_cadence = QComboBox()
        for libelle, valeur in CADENCES:
            self.combo_cadence.addItem(libelle, valeur)

        self.spin_limite = QSpinBox()
        self.spin_limite.setRange(5, 100)
        self.spin_limite.setValue(20)

        self.check_classees = QCheckBox("Parties classées seulement")

        self.btn_chercher = QPushButton("Chercher")
        self.btn_chercher.setDefault(True)
        self.btn_chercher.clicked.connect(self._chercher)

        formulaire = QFormLayout()
        formulaire.addRow("Pseudo", self.edit_pseudo)
        formulaire.addRow("Cadence", self.combo_cadence)
        formulaire.addRow("Nombre de parties", self.spin_limite)
        formulaire.addRow("", self.check_classees)

        ligne_bouton = QHBoxLayout()
        ligne_bouton.addStretch()
        ligne_bouton.addWidget(self.btn_chercher)

        self.liste = QListWidget()
        self.liste.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.liste.itemDoubleClicked.connect(lambda _: self.accept())
        self.liste.currentRowChanged.connect(self._maj_bouton_ok)

        self.label_statut = QLabel(" ")
        self.label_statut.setWordWrap(True)

        self.boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.boutons.button(QDialogButtonBox.StandardButton.Open).setText("Analyser")
        self.boutons.accepted.connect(self.accept)
        self.boutons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(formulaire)
        layout.addLayout(ligne_bouton)
        layout.addWidget(self.liste, stretch=1)
        layout.addWidget(self.label_statut)
        layout.addWidget(self.boutons)

        self._maj_bouton_ok(-1)

    def _maj_bouton_ok(self, row: int) -> None:
        self.boutons.button(QDialogButtonBox.StandardButton.Open).setEnabled(row >= 0)

    # -- préférences ------------------------------------------------------

    def _restore(self) -> None:
        self.edit_pseudo.setText(self._settings.value("chesscom/username", "", str))
        index = self.combo_cadence.findText(
            self._settings.value("chesscom/cadence", "Toutes", str)
        )
        self.combo_cadence.setCurrentIndex(max(0, index))
        self.spin_limite.setValue(int(self._settings.value("chesscom/limite", 20)))
        self.check_classees.setChecked(
            self._settings.value("chesscom/classees", False, bool)
        )

    def _sauver(self) -> None:
        self._settings.setValue("chesscom/username", self.edit_pseudo.text().strip())
        self._settings.setValue("chesscom/cadence", self.combo_cadence.currentText())
        self._settings.setValue("chesscom/limite", self.spin_limite.value())
        self._settings.setValue("chesscom/classees", self.check_classees.isChecked())

    # -- recherche --------------------------------------------------------

    @property
    def username(self) -> str:
        return self.edit_pseudo.text().strip()

    def _chercher(self) -> None:
        if self._thread is not None:
            return
        pseudo = self.username
        if not pseudo:
            self.label_statut.setText("Saisis d'abord un pseudo.")
            return

        self._sauver()
        self.liste.clear()
        self._parties = []
        self._maj_bouton_ok(-1)
        self._verrouiller(True)
        self.label_statut.setText(f"Recherche des parties de {pseudo}…")

        worker = FetchWorker(
            username=pseudo,
            limit=self.spin_limite.value(),
            time_classes=self.combo_cadence.currentData(),
            rated_only=self.check_classees.isChecked(),
            user_agent=f"chess-review/1.0 (utilisateur: {pseudo})",
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)

        self._worker = worker
        self._thread = thread
        thread.start()

    def _verrouiller(self, occupe: bool) -> None:
        self.btn_chercher.setEnabled(not occupe)
        self.edit_pseudo.setEnabled(not occupe)
        self.combo_cadence.setEnabled(not occupe)
        self.spin_limite.setEnabled(not occupe)
        self.check_classees.setEnabled(not occupe)

    @Slot(object)
    def _on_finished(self, parties: list[GameSummary]) -> None:
        self._parties = parties
        if not parties:
            self.label_statut.setText(
                "Aucune partie trouvée. Vérifie le pseudo ou élargis les filtres."
            )
            return

        pseudo = self.username
        for partie in parties:
            item = QListWidgetItem(partie.label(pseudo))
            item.setToolTip(partie.url)
            self.liste.addItem(item)
        self.liste.setCurrentRow(0)
        self.label_statut.setText(f"{len(parties)} partie(s). Double-clique pour ouvrir.")

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.label_statut.setText(message)

    @Slot()
    def _on_thread_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self._verrouiller(False)

    # -- résultat ---------------------------------------------------------

    def selected_game(self) -> GameSummary | None:
        row = self.liste.currentRow()
        if 0 <= row < len(self._parties):
            return self._parties[row]
        return None

    def selected_color(self) -> chess.Color | None:
        """Couleur jouée par l'utilisateur, pour orienter l'échiquier."""
        partie = self.selected_game()
        return partie.color_of(self.username) if partie else None

    def closeEvent(self, event) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        super().closeEvent(event)