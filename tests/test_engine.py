"""Tests du module core.engine.

Les tests moteur tournent avec une limite en nœuds plutôt qu'en profondeur :
c'est déterministe en durée, ce qui garde la suite sous quelques secondes.
"""

from __future__ import annotations

import io

import chess
import chess.pgn
import pytest

from src.core.engine import (
    ChessEngine,
    EngineConfig,
    EngineNotFound,
    MoveAnalysis,
    find_stockfish,
    score_to_cp,
    win_probability,
)

RAPIDE = EngineConfig(nodes=60_000, multipv=2, threads=1, hash_mb=32)


# --------------------------------------------------------------------------
# Fonctions pures : pas besoin du moteur, donc instantanées.
# --------------------------------------------------------------------------


def test_find_stockfish_trouve_le_binaire():
    assert find_stockfish().endswith("stockfish")


def test_find_stockfish_chemin_invalide_est_ignore(monkeypatch):
    """Un chemin explicite bidon ne doit pas masquer la découverte automatique."""
    assert find_stockfish("/chemin/qui/nexiste/pas").endswith("stockfish")


def test_find_stockfish_leve_si_rien(monkeypatch):
    monkeypatch.delenv("STOCKFISH_PATH", raising=False)
    monkeypatch.setattr("src.core.engine.shutil.which", lambda _: None)
    monkeypatch.setattr("src.core.engine._CANDIDATS", ())
    with pytest.raises(EngineNotFound):
        find_stockfish()


def test_win_probability_equilibre():
    assert win_probability(0) == pytest.approx(0.5)


def test_win_probability_monotone():
    assert win_probability(-300) < win_probability(0) < win_probability(300)


def test_win_probability_bornee():
    assert 0.0 <= win_probability(-100_000) < 0.01
    assert 0.99 < win_probability(100_000) <= 1.0


def test_score_to_cp_plafonne_le_mat():
    assert score_to_cp(chess.engine.Mate(1)) == 1000
    assert score_to_cp(chess.engine.Mate(-1)) == -1000


def test_score_to_cp_laisse_passer_les_valeurs_normales():
    assert score_to_cp(chess.engine.Cp(42)) == 42
    assert score_to_cp(chess.engine.Cp(-42)) == -42


# --------------------------------------------------------------------------
# Moteur : une seule instance partagée pour toute la suite.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def moteur():
    with ChessEngine(config=RAPIDE) as e:
        yield e


def test_ouverture_et_fermeture():
    e = ChessEngine(config=RAPIDE)
    e.open()
    assert e.analyse_position(chess.Board()).lines
    e.close()
    assert e._engine is None


def test_utilisation_sans_open_leve():
    e = ChessEngine(config=RAPIDE)
    with pytest.raises(RuntimeError):
        e.analyse_position(chess.Board())


def test_position_initiale_est_equilibree(moteur):
    analyse = moteur.analyse_position(chess.Board())
    assert analyse.best is not None
    assert analyse.best.move in chess.Board().legal_moves
    assert abs(analyse.cp_white) < 150, "la position de départ n'est pas gagnée"


def test_multipv_rend_plusieurs_variantes(moteur):
    analyse = moteur.analyse_position(chess.Board())
    assert len(analyse.lines) == 2
    # La première variante est au moins aussi bonne que la seconde.
    assert analyse.lines[0].score_white >= analyse.lines[1].score_white


def test_mat_en_un_est_trouve(moteur):
    # Mat du couloir : la tour arrive en a8.
    board = chess.Board("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    analyse = moteur.analyse_position(board)
    assert analyse.best.score_white.is_mate()
    assert analyse.best.score_white.mate() == 1


def test_position_terminee_rend_une_analyse_vide(moteur):
    # Mat du berger consommé : plus aucun coup légal.
    board = chess.Board(
        "r1bqkb1r/pppp1Qpp/2n2n2/4p3/2B1P3/8/PPPP1PPP/RNB1K1NR b KQkq - 0 4"
    )
    assert board.is_game_over()
    analyse = moteur.analyse_position(board)
    assert analyse.lines == []
    assert analyse.best is None


def test_position_terminale_a_une_evaluation(moteur):
    """Un mat vaut la victoire, pas zéro.

    Sans ça, la jauge revient à l'équilibre au moment précis où la partie est
    décidée — c'est la dernière chose qu'on veut voir.
    """
    mat_des_noirs = chess.Board(
        "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3"
    )
    analyse = moteur.analyse_position(mat_des_noirs)
    assert analyse.lines == []
    assert analyse.outcome_white == 0.0
    assert analyse.cp_white == -1000


def test_pat_vaut_la_nulle(moteur):
    pat = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    analyse = moteur.analyse_position(pat)
    assert analyse.outcome_white == 0.5
    assert analyse.cp_white == 0


def test_partie_en_cours_n_a_pas_d_issue(moteur):
    assert moteur.analyse_position(chess.Board()).outcome_white is None


def test_coup_force_est_detecte(moteur):
    # Échec de la tour h8, la case g1 est couverte par le fou a7 : reste Rg2.
    board = chess.Board("k6r/b7/8/8/8/8/8/7K w - - 0 1")
    assert board.legal_moves.count() == 1, "le test suppose un unique coup légal"
    analyse = moteur.analyse_position(board)
    assert analyse.is_forced


# --------------------------------------------------------------------------
# Analyse de partie
# --------------------------------------------------------------------------


def _coups(board: chess.Board, *sans: str) -> list[chess.Move]:
    b = board.copy()
    out = []
    for san in sans:
        move = b.parse_san(san)
        out.append(move)
        b.push(move)
    return out


def test_analyse_moves_structure(moteur):
    board = chess.Board()
    moves = _coups(board, "e4", "e5", "Nf3", "Nc6")
    resultats = moteur.analyse_moves(moves, board)

    assert len(resultats) == 4
    assert [r.ply for r in resultats] == [1, 2, 3, 4]
    assert [r.san for r in resultats] == ["e4", "e5", "Nf3", "Nc6"]
    assert [r.turn for r in resultats] == [
        chess.WHITE,
        chess.BLACK,
        chess.WHITE,
        chess.BLACK,
    ]
    assert [r.move_number for r in resultats] == [1, 1, 2, 2]


def test_chainage_des_evaluations(moteur):
    """L'évaluation d'après un coup est celle d'avant le suivant."""
    board = chess.Board()
    resultats = moteur.analyse_moves(_coups(board, "e4", "e5", "Nf3"), board)
    for precedent, suivant in zip(resultats, resultats[1:]):
        assert precedent.after is suivant.before


def test_perte_jamais_negative(moteur):
    board = chess.Board()
    resultats = moteur.analyse_moves(_coups(board, "e4", "e5", "Nf3", "Nc6"), board)
    assert all(r.centipawn_loss >= 0 for r in resultats)


def test_gaffe_produit_une_grosse_perte(moteur):
    """Mat du sot : 2.g4?? autorise Dh4 mat."""
    board = chess.Board()
    resultats = moteur.analyse_moves(_coups(board, "f3", "e5", "g4"), board)
    gaffe = resultats[-1]
    assert gaffe.san == "g4"
    assert gaffe.turn == chess.WHITE
    assert gaffe.centipawn_loss > 500
    # Les blancs étaient déjà un peu moins bien après 1.f3 : la chute ne peut
    # donc pas atteindre 0,5 même sur un mat forcé.
    assert gaffe.win_prob_drop > 0.35
    assert not gaffe.is_best


def test_bon_coup_produit_une_perte_faible(moteur):
    board = chess.Board()
    resultats = moteur.analyse_moves(_coups(board, "e4", "e5", "Nf3", "Nc6"), board)
    assert all(r.centipawn_loss < 120 for r in resultats)


def test_point_de_vue_du_joueur(moteur):
    """cp_before est compté positivement pour le camp qui joue."""
    board = chess.Board()
    resultats = moteur.analyse_moves(_coups(board, "e4", "e5"), board)
    blanc, noir = resultats
    assert blanc.cp_before == blanc.before.cp_white
    assert noir.cp_before == -noir.before.cp_white
    # Après 1.e4, le trait est aux noirs et l'évaluation blanche est positive :
    # du point de vue des noirs elle doit donc être négative.
    assert noir.before.cp_white > 0
    assert noir.cp_before < 0


def test_coup_illegal_leve(moteur):
    board = chess.Board()
    with pytest.raises(ValueError, match="illégal"):
        moteur.analyse_moves([chess.Move.from_uci("e2e5")], board)


def test_callback_de_progression(moteur):
    board = chess.Board()
    appels: list[tuple[int, int]] = []
    moves = _coups(board, "e4", "e5")
    moteur.analyse_moves(moves, board, progress=lambda f, t: appels.append((f, t)))

    assert appels[0] == (1, 3), "la position de départ compte comme une étape"
    assert appels[-1] == (3, 3), "la progression atteint bien 100 %"
    assert [a for a, _ in appels] == sorted(a for a, _ in appels)


def test_arret_demande_interrompt(moteur):
    board = chess.Board()
    moves = _coups(board, "e4", "e5", "Nf3", "Nc6", "Bb5", "a6")

    def stopper(fait: int, total: int) -> None:
        if fait >= 2:
            moteur.request_stop()

    resultats = moteur.analyse_moves(moves, board, progress=stopper)
    assert 0 < len(resultats) < len(moves)
    moteur.clear_stop()


def test_analyse_game_depuis_un_pgn(moteur):
    pgn = io.StringIO(
        '[Event "Test"]\n[White "A"]\n[Black "B"]\n[Result "1-0"]\n\n'
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 1-0\n"
    )
    game = chess.pgn.read_game(pgn)
    resultats = moteur.analyse_game(game)

    assert len(resultats) == 5
    assert resultats[-1].san == "Bb5"
    assert all(isinstance(r, MoveAnalysis) for r in resultats)


def test_is_best_reconnait_le_coup_du_moteur(moteur):
    """Sur un coup unique, le coup joué est forcément celui du moteur.

    On évite volontairement la position de départ : avec une limite en nœuds
    et une table de hachage qui se remplit, deux analyses successives du même
    échiquier peuvent rendre e4 puis d4. Ce n'est pas un bug, c'est le moteur.
    """
    board = chess.Board("k6r/b7/8/8/8/8/8/7K w - - 0 1")
    move = board.parse_san("Kg2")
    resultats = moteur.analyse_moves([move], board)
    assert resultats[0].is_best
    assert resultats[0].best_san == "Kg2"