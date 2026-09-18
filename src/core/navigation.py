"""Navigation dans une partie.

Volontairement hors de src/ui : parcourir une partie est de la logique pure, et
la sortir de Qt la rend testable sans lancer d'application graphique.

Convention : le demi-coup 0 est la position de départ. Le demi-coup N est la
position après le N-ième coup. Un navigateur sur une partie de 40 coups a donc
41 positions.
"""

from __future__ import annotations

import chess
import chess.pgn

from src.core.classify import ClassifiedMove, GameReport


class GameNavigator:
    """Curseur sur les positions successives d'une partie."""

    def __init__(
        self,
        moves: list[chess.Move],
        root_board: chess.Board | None = None,
        report: GameReport | None = None,
    ) -> None:
        self._root = (root_board or chess.Board()).copy()
        self._moves = list(moves)
        self._report = report
        self._ply = 0

        # Les positions sont précalculées : la navigation doit être instantanée,
        # et rejouer la partie depuis le début à chaque clic ne passerait pas
        # l'échelle sur une partie longue.
        self._boards: list[chess.Board] = [self._root.copy()]
        plateau = self._root.copy()
        for move in self._moves:
            plateau.push(move)
            self._boards.append(plateau.copy())

    # -- construction -----------------------------------------------------

    @classmethod
    def from_pgn(
        cls, game: chess.pgn.Game, report: GameReport | None = None
    ) -> "GameNavigator":
        return cls(list(game.mainline_moves()), game.board(), report)

    def attach_report(self, report: GameReport) -> None:
        """Associe un rapport après coup, l'analyse arrivant après le chargement."""
        self._report = report

    # -- état -------------------------------------------------------------

    @property
    def report(self) -> GameReport | None:
        return self._report

    @property
    def moves(self) -> list[chess.Move]:
        return list(self._moves)

    @property
    def ply(self) -> int:
        return self._ply

    def __len__(self) -> int:
        """Nombre de demi-coups, pas de positions."""
        return len(self._moves)

    @property
    def board(self) -> chess.Board:
        # Une copie, pas la référence : l'appelant (l'interface, un test) doit
        # pouvoir pousser des coups pour explorer une variante sans corrompre
        # les positions précalculées de la partie.
        return self._boards[self._ply].copy()

    def board_at(self, ply: int) -> chess.Board:
        """Position à un demi-coup donné, bornée et copiée."""
        index = max(0, min(len(self._moves), ply))
        return self._boards[index].copy()

    @property
    def last_move(self) -> chess.Move | None:
        """Le coup qui a mené à la position courante."""
        return self._moves[self._ply - 1] if self._ply > 0 else None

    @property
    def current(self) -> ClassifiedMove | None:
        """Le coup classé correspondant à la position courante."""
        if self._report is None or self._ply == 0:
            return None
        index = self._ply - 1
        if index < len(self._report.moves):
            return self._report.moves[index]
        return None

    @property
    def next_move(self) -> chess.Move | None:
        """Le coup à venir, utile pour afficher une flèche d'anticipation."""
        return self._moves[self._ply] if self._ply < len(self._moves) else None

    # -- déplacement ------------------------------------------------------

    @property
    def can_go_back(self) -> bool:
        return self._ply > 0

    @property
    def can_go_forward(self) -> bool:
        return self._ply < len(self._moves)

    def goto(self, ply: int) -> int:
        """Se place à un demi-coup, en bornant silencieusement."""
        self._ply = max(0, min(len(self._moves), ply))
        return self._ply

    def first(self) -> int:
        return self.goto(0)

    def last(self) -> int:
        return self.goto(len(self._moves))

    def previous(self) -> int:
        return self.goto(self._ply - 1)

    def next(self) -> int:
        return self.goto(self._ply + 1)

    def next_mistake(self, color: chess.Color | None = None) -> int | None:
        """Saute à la prochaine faute après la position courante.

        C'est le mode de lecture réellement utile : on ne relit pas une partie
        coup par coup, on saute d'erreur en erreur.
        """
        if self._report is None:
            return None
        for index, coup in enumerate(self._report.moves):
            ply = index + 1
            if ply <= self._ply:
                continue
            if not coup.classification.is_mistake:
                continue
            if color is not None and coup.turn != color:
                continue
            return self.goto(ply)
        return None

    def previous_mistake(self, color: chess.Color | None = None) -> int | None:
        if self._report is None:
            return None
        for index in range(len(self._report.moves) - 1, -1, -1):
            coup = self._report.moves[index]
            ply = index + 1
            if ply >= self._ply:
                continue
            if not coup.classification.is_mistake:
                continue
            if color is not None and coup.turn != color:
                continue
            return self.goto(ply)
        return None