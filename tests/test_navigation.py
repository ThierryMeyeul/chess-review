"""Tests du module core.navigation.

Aucune dépendance à Qt ni à Stockfish : c'est tout l'intérêt d'avoir sorti la
navigation de l'interface. Les rapports sont fabriqués à la main.
"""

from __future__ import annotations

import io

import chess
import chess.engine
import chess.pgn
import pytest

from src.core.classify import ClassifiedMove, GameReport, MoveClass, PlayerReport
from src.core.engine import Line, MoveAnalysis, PositionAnalysis
from src.core.navigation import GameNavigator

ESPAGNOLE = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]


def coups(*sans: str) -> list[chess.Move]:
    board = chess.Board()
    out = []
    for san in sans:
        move = board.parse_san(san)
        out.append(move)
        board.push(move)
    return out


def faux_rapport(classifications: list[MoveClass]) -> GameReport:
    """Rapport minimal : seules les classifications comptent pour ces tests."""
    board = chess.Board()
    moves: list[ClassifiedMove] = []
    for index, classification in enumerate(classifications):
        move = board.parse_san(ESPAGNOLE[index])
        trait = board.turn
        fen = board.fen()
        ligne = Line(
            move=move, san=board.san(move), score_white=chess.engine.Cp(0), pv=[move]
        )
        before = PositionAnalysis(fen=fen, turn=trait, lines=[ligne, ligne], depth=1)
        board.push(move)
        after = PositionAnalysis(
            fen=board.fen(), turn=board.turn, lines=[ligne], depth=1
        )
        moves.append(
            ClassifiedMove(
                analysis=MoveAnalysis(
                    ply=index + 1,
                    move_number=(index // 2) + 1,
                    turn=trait,
                    move=move,
                    san=ESPAGNOLE[index],
                    fen_before=fen,
                    before=before,
                    after=after,
                ),
                classification=classification,
                accuracy=100.0,
            )
        )
    return GameReport(
        moves=moves,
        white=PlayerReport(color=chess.WHITE, accuracy=100.0),
        black=PlayerReport(color=chess.BLACK, accuracy=100.0),
    )


@pytest.fixture
def nav() -> GameNavigator:
    return GameNavigator(coups(*ESPAGNOLE))


# --------------------------------------------------------------------------
# État initial
# --------------------------------------------------------------------------


def test_demarre_a_la_position_initiale(nav: GameNavigator):
    assert nav.ply == 0
    assert nav.board == chess.Board()
    assert nav.last_move is None


def test_longueur_en_demi_coups(nav: GameNavigator):
    assert len(nav) == 6


def test_navigateur_vide():
    vide = GameNavigator([])
    assert len(vide) == 0
    assert not vide.can_go_forward
    assert not vide.can_go_back
    assert vide.last_move is None


def test_la_position_de_depart_n_est_pas_partagee(nav: GameNavigator):
    """Modifier l'échiquier rendu ne doit pas corrompre le navigateur."""
    board = nav.board
    board.push_san("h4")
    assert nav.board.fen() != board.fen()


# --------------------------------------------------------------------------
# Déplacement
# --------------------------------------------------------------------------


def test_avance_et_recule(nav: GameNavigator):
    assert nav.next() == 1
    assert nav.next() == 2
    assert nav.previous() == 1
    assert nav.ply == 1


def test_premier_et_dernier(nav: GameNavigator):
    assert nav.last() == 6
    assert nav.board.fullmove_number == 4
    assert nav.first() == 0


def test_bornes_silencieuses(nav: GameNavigator):
    nav.first()
    assert nav.previous() == 0, "reculer avant le début ne doit pas lever"
    nav.last()
    assert nav.next() == 6, "avancer après la fin ne doit pas lever"


def test_goto_borne(nav: GameNavigator):
    assert nav.goto(-5) == 0
    assert nav.goto(99) == 6


def test_can_go(nav: GameNavigator):
    nav.first()
    assert not nav.can_go_back
    assert nav.can_go_forward
    nav.last()
    assert nav.can_go_back
    assert not nav.can_go_forward


def test_board_at_rend_la_bonne_position(nav: GameNavigator):
    assert nav.board_at(0) == chess.Board()
    assert nav.board_at(6).fullmove_number == 4


def test_board_at_borne(nav: GameNavigator):
    assert nav.board_at(-3) == chess.Board()
    assert nav.board_at(99).fen() == nav.board_at(6).fen()


def test_board_at_ne_bouge_pas_le_curseur(nav: GameNavigator):
    nav.goto(2)
    nav.board_at(5)
    assert nav.ply == 2


def test_board_at_rend_une_copie(nav: GameNavigator):
    board = nav.board_at(0)
    board.push_san("h4")
    assert nav.board_at(0) == chess.Board()


def test_last_move_correspond_a_la_position(nav: GameNavigator):
    nav.goto(1)
    assert nav.board.san(nav.next_move) == "e5"
    assert nav.last_move == coups("e4")[0]


def test_next_move_en_fin_de_partie(nav: GameNavigator):
    nav.last()
    assert nav.next_move is None


# --------------------------------------------------------------------------
# Rapport attaché
# --------------------------------------------------------------------------


def test_sans_rapport_current_est_none(nav: GameNavigator):
    nav.goto(3)
    assert nav.current is None


def test_current_suit_le_curseur(nav: GameNavigator):
    nav.attach_report(faux_rapport([MoveClass.BOOK] * 6))
    nav.goto(0)
    assert nav.current is None
    nav.goto(3)
    assert nav.current.san == "Nf3"


def test_current_au_dernier_coup(nav: GameNavigator):
    nav.attach_report(faux_rapport([MoveClass.BOOK] * 6))
    nav.last()
    assert nav.current.san == "a6"


def test_from_pgn_charge_les_coups():
    pgn = io.StringIO('[Event "T"]\n\n1. e4 e5 2. Nf3 *\n')
    nav = GameNavigator.from_pgn(chess.pgn.read_game(pgn))
    assert len(nav) == 3
    nav.last()
    assert nav.board.piece_at(chess.F3) is not None


# --------------------------------------------------------------------------
# Saut de faute en faute
# --------------------------------------------------------------------------


def rapport_avec_fautes() -> GameReport:
    # plies :        1        2          3               4            5         6
    return faux_rapport(
        [
            MoveClass.BOOK,
            MoveClass.BOOK,
            MoveClass.BLUNDER,   # blancs, demi-coup 3
            MoveClass.EXCELLENT,
            MoveClass.BEST,
            MoveClass.MISTAKE,   # noirs, demi-coup 6
        ]
    )


def test_next_mistake_saute_les_bons_coups(nav: GameNavigator):
    nav.attach_report(rapport_avec_fautes())
    assert nav.next_mistake() == 3
    assert nav.next_mistake() == 6


def test_next_mistake_rend_none_a_la_fin(nav: GameNavigator):
    nav.attach_report(rapport_avec_fautes())
    nav.goto(6)
    assert nav.next_mistake() is None
    assert nav.ply == 6, "un échec ne doit pas déplacer le curseur"


def test_next_mistake_filtre_par_couleur(nav: GameNavigator):
    nav.attach_report(rapport_avec_fautes())
    assert nav.next_mistake(chess.BLACK) == 6


def test_previous_mistake(nav: GameNavigator):
    nav.attach_report(rapport_avec_fautes())
    nav.last()
    assert nav.previous_mistake() == 3
    assert nav.previous_mistake() is None


def test_mistake_sans_rapport(nav: GameNavigator):
    assert nav.next_mistake() is None
    assert nav.previous_mistake() is None