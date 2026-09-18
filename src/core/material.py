"""Matériel capturé.

Compter les pièces manquantes ne suffit pas : une promotion fait disparaître un
pion sans qu'il ait été pris. Un camp qui a promu deux pions et perdu trois
pièces affiche cinq absences, dont deux ne sont pas des captures.

La correction consiste à repérer les pièces en excès par rapport à la position
de départ — une deuxième dame, une troisième tour — et à en déduire autant de
pions promus, qu'on retire du décompte des pions capturés.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import chess

# Valeurs conventionnelles. Le roi n'entre pas dans le calcul : il ne se prend
# pas et fausserait toute différence.
VALEURS = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
}

ORDRE_AFFICHAGE = (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN)


@dataclass(frozen=True)
class Captures:
    """Pièces perdues par un camp, et leur valeur totale."""

    color: chess.Color
    pieces: dict[chess.PieceType, int] = field(default_factory=dict)
    promotions: int = 0

    @property
    def value(self) -> int:
        return sum(VALEURS[t] * n for t, n in self.pieces.items())

    @property
    def total(self) -> int:
        return sum(self.pieces.values())

    def symbols(self) -> str:
        """Pièces perdues en notation Unicode, des plus fortes aux pions."""
        sortie = []
        for piece_type in ORDRE_AFFICHAGE:
            nombre = self.pieces.get(piece_type, 0)
            if nombre:
                sortie.append(
                    chess.Piece(piece_type, self.color).unicode_symbol() * nombre
                )
        return "".join(sortie)


def _compter(board: chess.Board, color: chess.Color) -> dict[chess.PieceType, int]:
    return {
        piece_type: len(board.pieces(piece_type, color)) for piece_type in VALEURS
    }


def captures_for(
    board: chess.Board, color: chess.Color, root: chess.Board | None = None
) -> Captures:
    """Pièces de `color` capturées depuis la position de départ.

    `root` permet de partir d'autre chose que l'échiquier initial — une partie
    reprise en cours, par exemple. Par défaut, la position standard.
    """
    depart = root if root is not None else chess.Board()
    initial = _compter(depart, color)
    actuel = _compter(board, color)

    # Une pièce en surnombre vient nécessairement d'une promotion.
    promotions = sum(
        max(0, actuel[t] - initial[t]) for t in VALEURS if t is not chess.PAWN
    )

    manquantes = {
        t: max(0, initial[t] - actuel[t]) for t in VALEURS
    }
    manquantes[chess.PAWN] = max(0, manquantes[chess.PAWN] - promotions)

    return Captures(
        color=color,
        pieces={t: n for t, n in manquantes.items() if n > 0},
        promotions=promotions,
    )


def material_diff(board: chess.Board, root: chess.Board | None = None) -> int:
    """Avantage matériel en pions, positif si les blancs mènent.

    Calculé sur les pièces présentes et non sur les captures : les promotions
    sont ainsi prises en compte sans traitement particulier.
    """
    depart = root if root is not None else chess.Board()
    del depart  # la position de départ n'intervient pas ici
    total = 0
    for piece_type, valeur in VALEURS.items():
        total += valeur * len(board.pieces(piece_type, chess.WHITE))
        total -= valeur * len(board.pieces(piece_type, chess.BLACK))
    return total


def summary(
    board: chess.Board, root: chess.Board | None = None
) -> tuple[Captures, Captures, int]:
    """Captures des blancs, des noirs, et l'avantage matériel."""
    return (
        captures_for(board, chess.WHITE, root),
        captures_for(board, chess.BLACK, root),
        material_diff(board, root),
    )