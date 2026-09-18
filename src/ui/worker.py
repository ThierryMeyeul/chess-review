"""Analyse en arrière-plan.

Stockfish est bloquant. Appelé depuis le thread graphique, il gèle la fenêtre
pendant toute la durée de l'analyse — trente secondes sur une partie de
quarante coups à profondeur 18. L'utilisateur conclut que l'application a
planté.

Ce module isole l'analyse dans un QThread et ne communique avec l'interface que
par signaux, seule manière sûre de traverser la frontière entre threads en Qt.
"""

from __future__ import annotations

import chess
from PySide6.QtCore import QObject, QThread, Signal, Slot

from src.core.classify import ClassifierConfig, GameReport, build_report
from src.core.engine import ChessEngine, EngineConfig


class AnalysisWorker(QObject):
    """Exécute l'analyse d'une partie. Vit dans son propre thread."""

    progress = Signal(int, int)      # (positions traitées, total)
    finished = Signal(object)        # GameReport
    failed = Signal(str)             # message d'erreur

    def __init__(
        self,
        moves: list[chess.Move],
        root_board: chess.Board,
        engine_config: EngineConfig | None = None,
        classifier_config: ClassifierConfig | None = None,
        book_plies: int = 0,
        engine_path: str | None = None,
    ) -> None:
        super().__init__()
        self._moves = list(moves)
        self._root = root_board.copy()
        self._engine_config = engine_config or EngineConfig()
        self._classifier_config = classifier_config
        self._book_plies = book_plies
        self._engine_path = engine_path
        self._engine: ChessEngine | None = None

    @Slot()
    def run(self) -> None:
        """Point d'entrée dans le thread. Ne jamais appeler directement."""
        try:
            # Le moteur est créé ici et pas dans __init__ : le sous-processus
            # doit appartenir au thread qui l'utilise.
            with ChessEngine(
                path=self._engine_path, config=self._engine_config
            ) as moteur:
                self._engine = moteur
                analyses = moteur.analyse_moves(
                    self._moves,
                    self._root,
                    progress=lambda fait, total: self.progress.emit(fait, total),
                )
            report = build_report(
                analyses,
                book_plies=self._book_plies,
                config=self._classifier_config,
            )
            self.finished.emit(report)
        except Exception as exc:  # remonter au lieu de mourir en silence
            self.failed.emit(str(exc))
        finally:
            self._engine = None

    def cancel(self) -> None:
        """Interrompt l'analyse. Appelable depuis le thread graphique.

        request_stop() pose un threading.Event, donc l'appel est sûr entre
        threads. L'analyse s'arrête au coup suivant et rend un rapport partiel.
        """
        moteur = self._engine
        if moteur is not None:
            moteur.request_stop()


class AnalysisController(QObject):
    """Gère le cycle de vie thread + worker.

    Sans cette couche, il faut recâbler une dizaine de connexions à chaque
    lancement d'analyse, et oublier d'en défaire une laisse un thread orphelin.
    """

    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)
    state_changed = Signal(bool)  # True = analyse en cours

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: AnalysisWorker | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self, worker: AnalysisWorker) -> bool:
        """Lance une analyse. Rend False si une autre tourne déjà."""
        if self.running:
            return False

        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self.progress)
        worker.finished.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_thread_finished)

        self._thread = thread
        self._worker = worker
        thread.start()
        self.state_changed.emit(True)
        return True

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()

    def wait(self, timeout_ms: int = 5000) -> None:
        """Attend la fin du thread. À appeler à la fermeture de la fenêtre."""
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(timeout_ms)

    @Slot(object)
    def _on_finished(self, report: GameReport) -> None:
        self.finished.emit(report)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.failed.emit(message)

    @Slot()
    def _on_thread_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self.state_changed.emit(False)