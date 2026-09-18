"""Encapsulation de Stockfish.

Cette couche ne connaît ni l'interface graphique ni chess.com : elle prend des
positions ou une partie, et rend des évaluations exploitables par classify.py.
"""

from __future__ import annotations

import math
import os
import shutil
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterable, Iterator, Sequence

import chess
import chess.engine
import chess.pgn

# Chemins usuels du binaire selon la plateforme.
_CANDIDATS = (
    "/usr/games/stockfish",
    "/usr/local/bin/stockfish",
    "/opt/homebrew/bin/stockfish",
    "C:/Program Files/Stockfish/stockfish.exe",
)


class EngineNotFound(RuntimeError):
    """Le binaire Stockfish est introuvable."""


def find_stockfish(chemin: str | None = None) -> str:
    """Localise le binaire.

    Ordre de priorité : argument explicite, variable STOCKFISH_PATH, PATH
    système, puis les emplacements usuels.
    """
    pistes = [chemin, os.environ.get("STOCKFISH_PATH"), shutil.which("stockfish")]
    pistes.extend(_CANDIDATS)
    for piste in pistes:
        if piste and os.path.isfile(piste) and os.access(piste, os.X_OK):
            return piste
    raise EngineNotFound(
        "Stockfish introuvable. Installe-le ou renseigne STOCKFISH_PATH "
        "dans le fichier .env."
    )


@dataclass(frozen=True)
class EngineConfig:
    """Paramètres d'analyse.

    depth : profondeur de recherche. 12 pour un survol rapide, 18-20 pour une
    analyse sérieuse. Le coût est à peu près exponentiel.
    multipv : nombre de variantes retournées. Il en faut au moins 2 pour
    distinguer un coup forcé d'un coup réellement choisi (utile au badge
    « brillant »).
    """

    depth: int = 16
    threads: int = 1
    hash_mb: int = 128
    multipv: int = 2
    nodes: int | None = None  # si renseigné, prime sur depth (tests rapides)

    def to_limit(self) -> chess.engine.Limit:
        if self.nodes is not None:
            return chess.engine.Limit(nodes=self.nodes)
        return chess.engine.Limit(depth=self.depth)


# Conversion centipions -> probabilité de victoire, formule utilisée par
# Lichess pour son calcul de précision. Le lissage évite qu'un +9 et un +30
# soient traités comme deux mondes différents : au-delà d'un certain avantage,
# la partie est gagnée de la même manière.
_LISSAGE = 0.00368208


def win_probability(cp: float) -> float:
    """Probabilité de victoire (0..1) pour le camp dont l'évaluation est `cp`."""
    return 1.0 / (1.0 + math.exp(-_LISSAGE * cp))


def score_to_cp(score: chess.engine.Score, plafond: int = 1000) -> int:
    """Ramène un score (éventuellement un mat) à des centipions bornés.

    Un mat annoncé devient +/- plafond : au-delà, la différence n'a plus de
    sens pour mesurer la qualité d'un coup.
    """
    valeur = score.score(mate_score=100_000)
    if valeur is None:  # pragma: no cover - défensif
        return 0
    return max(-plafond, min(plafond, valeur))


@dataclass
class Line:
    """Une variante proposée par le moteur."""

    move: chess.Move
    san: str
    score_white: chess.engine.Score  # toujours du point de vue des blancs
    pv: list[chess.Move] = field(default_factory=list)


@dataclass
class PositionAnalysis:
    """Résultat de l'analyse d'une position."""

    fen: str
    turn: chess.Color
    lines: list[Line]
    depth: int

    @property
    def best(self) -> Line | None:
        return self.lines[0] if self.lines else None

    @property
    def outcome_white(self) -> float | None:
        """Issue de la partie : 1 victoire blanche, 0 noire, 0.5 nulle.

        `None` si la partie continue. Déduit de la position elle-même, donc
        valable aussi pour une analyse relue depuis la base.
        """
        resultat = chess.Board(self.fen).outcome()
        if resultat is None:
            return None
        if resultat.winner is chess.WHITE:
            return 1.0
        if resultat.winner is chess.BLACK:
            return 0.0
        return 0.5

    @property
    def score_white(self) -> chess.engine.Score:
        if self.lines:
            return self.lines[0].score_white

        # Position terminale : le moteur n'a rien à dire, mais l'évaluation
        # n'est pas nulle pour autant. Sans ça, un mat afficherait 0.00 et la
        # jauge resterait à l'équilibre alors que la partie est décidée.
        issue = self.outcome_white
        if issue == 1.0:
            return chess.engine.Cp(100_000)
        if issue == 0.0:
            return chess.engine.Cp(-100_000)
        return chess.engine.Cp(0)

    @property
    def cp_white(self) -> int:
        return score_to_cp(self.score_white)

    @property
    def mate_white(self) -> int | None:
        """Nombre de coups avant mat, positif si les blancs matent."""
        if not self.lines:
            return None
        return self.score_white.mate()

    @property
    def is_forced(self) -> bool:
        """Vrai s'il n'existe qu'un seul coup légal."""
        return len(self.lines) == 1


@dataclass
class MoveAnalysis:
    """Un coup joué, encadré par l'évaluation d'avant et celle d'après."""

    ply: int
    move_number: int
    turn: chess.Color  # camp qui a joué
    move: chess.Move
    san: str
    fen_before: str
    before: PositionAnalysis
    after: PositionAnalysis

    @property
    def is_best(self) -> bool:
        best = self.before.best
        return best is not None and best.move == self.move

    @property
    def best_san(self) -> str:
        best = self.before.best
        return best.san if best else ""

    def _pov(self, cp_white: int) -> int:
        """Ramène une évaluation blancs au point de vue du joueur qui a joué."""
        return cp_white if self.turn == chess.WHITE else -cp_white

    @property
    def cp_before(self) -> int:
        return self._pov(self.before.cp_white)

    @property
    def cp_after(self) -> int:
        return self._pov(self.after.cp_white)

    @property
    def mate_for_mover_before(self) -> int | None:
        """Mat disponible avant le coup, du point de vue du joueur au trait."""
        mat = self.before.mate_white
        if mat is None:
            return None
        return mat if self.turn == chess.WHITE else -mat

    @property
    def mate_for_mover(self) -> int | None:
        """Mat après le coup, du point de vue du joueur qui vient de jouer.

        Positif : il mate. Négatif : il se fait mater.
        """
        mat = self.after.mate_white
        if mat is None:
            return None
        return mat if self.turn == chess.WHITE else -mat

    @property
    def outcome_white(self) -> float | None:
        """Issue après le coup, si la partie s'y termine."""
        return self.after.outcome_white

    @property
    def centipawn_loss(self) -> int:
        """Perte en centipions, jamais négative.

        Un coup meilleur que ce que le moteur avait vu (ça arrive à faible
        profondeur) compte comme une perte nulle, pas comme un gain.
        """
        return max(0, self.cp_before - self.cp_after)

    @property
    def win_prob_before(self) -> float:
        return win_probability(self.cp_before)

    @property
    def win_prob_after(self) -> float:
        return win_probability(self.cp_after)

    @property
    def win_prob_drop(self) -> float:
        """Chute de probabilité de victoire (0..1). Base des classifications."""
        return max(0.0, self.win_prob_before - self.win_prob_after)


ProgressCallback = Callable[[int, int], None]


class ChessEngine:
    """Gestionnaire de session Stockfish.

    Le processus reste ouvert entre les appels : le relancer à chaque position
    coûterait plus cher que l'analyse elle-même.

        with ChessEngine() as moteur:
            analyse = moteur.analyse_position(chess.Board())
    """

    def __init__(
        self,
        path: str | None = None,
        config: EngineConfig | None = None,
    ) -> None:
        self.path = find_stockfish(path)
        self.config = config or EngineConfig()
        self._engine: chess.engine.SimpleEngine | None = None
        self._stop = threading.Event()

    # -- cycle de vie -----------------------------------------------------

    def open(self) -> "ChessEngine":
        if self._engine is None:
            self._engine = chess.engine.SimpleEngine.popen_uci(self.path)
            self._engine.configure(
                {"Threads": self.config.threads, "Hash": self.config.hash_mb}
            )
        return self

    def close(self) -> None:
        if self._engine is not None:
            self._engine.quit()
            self._engine = None

    def __enter__(self) -> "ChessEngine":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def engine(self) -> chess.engine.SimpleEngine:
        if self._engine is None:
            raise RuntimeError("Moteur non démarré : utilise open() ou le with.")
        return self._engine

    # -- annulation -------------------------------------------------------

    def request_stop(self) -> None:
        """Demande l'arrêt d'une analyse de partie en cours (appel externe)."""
        self._stop.set()

    def clear_stop(self) -> None:
        self._stop.clear()

    # -- analyse ----------------------------------------------------------

    def analyse_position(self, board: chess.Board) -> PositionAnalysis:
        """Analyse une position et rend les meilleures variantes."""
        if board.is_game_over():
            return PositionAnalysis(
                fen=board.fen(), turn=board.turn, lines=[], depth=0
            )

        multipv = min(self.config.multipv, board.legal_moves.count())
        infos = self.engine.analyse(
            board, self.config.to_limit(), multipv=multipv
        )
        if isinstance(infos, dict):  # multipv=1 rend un dict, pas une liste
            infos = [infos]

        lines: list[Line] = []
        for info in infos:
            pv = list(info.get("pv") or [])
            if not pv:
                continue
            lines.append(
                Line(
                    move=pv[0],
                    san=board.san(pv[0]),
                    score_white=info["score"].white(),
                    pv=pv,
                )
            )
        profondeur = int(infos[0].get("depth", 0)) if infos else 0
        return PositionAnalysis(
            fen=board.fen(), turn=board.turn, lines=lines, depth=profondeur
        )

    def analyse_moves(
        self,
        moves: Sequence[chess.Move],
        board: chess.Board | None = None,
        progress: ProgressCallback | None = None,
    ) -> list[MoveAnalysis]:
        """Analyse une suite de coups depuis une position de départ.

        N coups demandent N+1 analyses de position : l'évaluation d'après un
        coup est celle d'avant le suivant, on ne la calcule donc qu'une fois.
        """
        board = board.copy() if board is not None else chess.Board()
        total = len(moves) + 1
        self.clear_stop()

        resultats: list[MoveAnalysis] = []
        precedente = self.analyse_position(board)
        if progress:
            progress(1, total)

        for index, move in enumerate(moves):
            if self._stop.is_set():
                break
            if move not in board.legal_moves:
                raise ValueError(
                    f"Coup illégal au demi-coup {index + 1} : {move.uci()} "
                    f"dans {board.fen()}"
                )

            san = board.san(move)
            fen_before = board.fen()
            trait = board.turn
            numero = board.fullmove_number

            board.push(move)
            suivante = self.analyse_position(board)

            resultats.append(
                MoveAnalysis(
                    ply=index + 1,
                    move_number=numero,
                    turn=trait,
                    move=move,
                    san=san,
                    fen_before=fen_before,
                    before=precedente,
                    after=suivante,
                )
            )
            precedente = suivante
            if progress:
                progress(index + 2, total)

        return resultats

    def analyse_game(
        self,
        game: chess.pgn.Game,
        progress: ProgressCallback | None = None,
    ) -> list[MoveAnalysis]:
        """Analyse la ligne principale d'une partie PGN."""
        board = game.board()
        moves = list(game.mainline_moves())
        return self.analyse_moves(moves, board=board, progress=progress)


def iter_positions(game: chess.pgn.Game) -> Iterator[tuple[chess.Board, chess.Move]]:
    """Parcourt (position, coup joué) le long de la ligne principale."""
    board = game.board()
    for move in game.mainline_moves():
        yield board.copy(), move
        board.push(move)