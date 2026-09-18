"""Analyse continue de la position affichée.

Différent de worker.py, qui analyse une partie entière puis rend la main. Ici
le moteur reste allumé et évalue la position courante à chaque changement,
comme le fait un échiquier d'analyse.

Le point délicat est l'obsolescence. Si l'utilisateur joue cinq coups en trois
secondes, cinq demandes s'empilent alors que seule la dernière compte. Chaque
demande est donc comparée à la plus récente avant d'être calculée, et le
résultat est jeté si la position a changé entre-temps.
"""

from __future__ import annotations

from dataclasses import dataclass

import chess
from PySide6.QtCore import QMutex, QMutexLocker, QObject, QThread, Signal, Slot

from src.core.engine import ChessEngine, EngineConfig


@dataclass(frozen=True)
class LiveEval:
    """Évaluation d'une position, du point de vue des blancs."""

    fen: str
    cp_white: int
    mate_white: int | None
    best_san: str
    best_uci: str
    pv_san: str
    depth: int
    # Jusqu'à trois variantes : (évaluation lisible, suite en notation SAN).
    lines: tuple[tuple[str, str], ...] = ()

    @property
    def texte(self) -> str:
        if self.mate_white is not None:
            camp = "blancs" if self.mate_white > 0 else "noirs"
            return f"Mat en {abs(self.mate_white)} pour les {camp}"
        return f"{self.cp_white / 100:+.2f}"


class _LiveWorker(QObject):
    """Vit dans le thread d'analyse. Ne jamais appeler ses méthodes directement."""

    result = Signal(object)
    failed = Signal(str)

    def __init__(self, engine_path: str | None, config: EngineConfig) -> None:
        super().__init__()
        self._engine_path = engine_path
        self._config = config
        self._engine: ChessEngine | None = None
        self._mutex = QMutex()
        self._latest_fen: str | None = None

    # -- appelé depuis le thread graphique --------------------------------

    def set_latest(self, fen: str) -> None:
        with QMutexLocker(self._mutex):
            self._latest_fen = fen

    def _is_latest(self, fen: str) -> bool:
        with QMutexLocker(self._mutex):
            return self._latest_fen == fen

    # -- exécuté dans le thread d'analyse ---------------------------------

    @Slot()
    def start(self) -> None:
        try:
            self._engine = ChessEngine(
                path=self._engine_path, config=self._config
            ).open()
        except Exception as exc:
            self.failed.emit(str(exc))

    @Slot(str)
    def analyse(self, fen: str) -> None:
        if self._engine is None or not self._is_latest(fen):
            return  # demande déjà périmée avant même d'avoir commencé

        try:
            board = chess.Board(fen)
        except ValueError:
            return

        if board.is_game_over():
            self.result.emit(
                LiveEval(
                    fen=fen,
                    cp_white=0,
                    mate_white=None,
                    best_san="",
                    best_uci="",
                    pv_san=self._issue(board),
                    lines=(),
                    depth=0,
                )
            )
            return

        try:
            analyse = self._engine.analyse_position(board)
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        if not self._is_latest(fen):
            return  # la position a changé pendant le calcul

        meilleure = analyse.best
        self.result.emit(
            LiveEval(
                fen=fen,
                cp_white=analyse.cp_white,
                mate_white=analyse.mate_white,
                best_san=meilleure.san if meilleure else "",
                best_uci=meilleure.move.uci() if meilleure else "",
                pv_san=self._variante(board, meilleure.pv if meilleure else []),
                depth=analyse.depth,
                lines=tuple(
                    (
                        self._texte_score(ligne.score_white),
                        self._variante(board, ligne.pv, limite=8),
                    )
                    for ligne in analyse.lines
                ),
            )
        )

    @Slot()
    def stop(self) -> None:
        if self._engine is not None:
            self._engine.close()
            self._engine = None

    # -- mise en forme ----------------------------------------------------

    @staticmethod
    def _issue(board: chess.Board) -> str:
        if board.is_checkmate():
            return "Échec et mat"
        if board.is_stalemate():
            return "Pat"
        if board.is_insufficient_material():
            return "Matériel insuffisant"
        return "Partie terminée"

    @staticmethod
    def _texte_score(score) -> str:
        """Évaluation d'une variante, du point de vue des blancs."""
        mat = score.mate()
        if mat is not None:
            return f"{'+' if mat > 0 else '-'}M{abs(mat)}"
        centipions = score.score(mate_score=100_000) or 0
        return f"{centipions / 100:+.2f}"

    @staticmethod
    def _variante(board: chess.Board, pv: list[chess.Move], limite: int = 6) -> str:
        if not pv:
            return ""
        try:
            return board.variation_san(pv[:limite])
        except ValueError:
            return ""


class LiveAnalyser(QObject):
    """Façade côté interface. Gère le thread et l'obsolescence des demandes."""

    result = Signal(object)  # LiveEval
    failed = Signal(str)

    _demande = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self._worker: _LiveWorker | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(
        self, engine_path: str | None = None, config: EngineConfig | None = None
    ) -> None:
        """Démarre le moteur. Relancer après un changement de réglages."""
        self.stop()

        worker = _LiveWorker(engine_path, config or EngineConfig(depth=16, multipv=1))
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.start)
        self._demande.connect(worker.analyse)
        worker.result.connect(self.result)
        worker.failed.connect(self.failed)

        self._worker = worker
        self._thread = thread
        thread.start()

    def request(self, board: chess.Board) -> None:
        """Demande l'évaluation d'une position. Les demandes se remplacent."""
        if self._worker is None:
            return
        fen = board.fen()
        # Enregistré avant l'émission : le worker doit pouvoir constater qu'une
        # demande plus récente existe, y compris pendant son propre calcul.
        self._worker.set_latest(fen)
        self._demande.emit(fen)

    def stop(self) -> None:
        if self._worker is not None:
            # Fermeture demandée dans le thread du moteur : le sous-processus
            # lui appartient.
            self._worker.stop()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        self._worker = None
        self._thread = None