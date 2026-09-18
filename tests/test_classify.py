"""Tests du module core.classify.

La classification est de la logique pure : elle ne doit pas dépendre de
Stockfish. La plupart des tests construisent donc des MoveAnalysis fabriqués à
la main, ce qui les rend instantanés et parfaitement déterministes. Seuls les
deux derniers font tourner le moteur, pour vérifier que les deux couches se
branchent correctement.
"""

from __future__ import annotations

import chess
import chess.engine
import pytest

from src.core.classify import (
    ClassifierConfig,
    MoveClass,
    best_line_gap,
    build_report,
    classify_by_eval,
    offers_material,
    changes_outcome,
    classify_move,
    is_simple_recapture,
    material_balance,
    move_accuracy,
    sacrifice_amount,
)
from src.core.engine import ChessEngine, EngineConfig, Line, MoveAnalysis, PositionAnalysis

# Position italienne, trait aux blancs, beaucoup de coups légaux.
ITALIENNE = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
# Après 1.e4, trait aux noirs.
APRES_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
# Échec de la tour, une seule parade.
FORCEE = "k6r/b7/8/8/8/8/8/7K w - - 0 1"


def fabrique(
    fen: str,
    san: str,
    cp_before: int,
    cp_after: int,
    *,
    best_san: str | None = None,
    second_cp: int | None = None,
    reply_san: str | None = None,
    ply: int = 1,
    mate_before: int | None = None,
    mate_after: int | None = None,
) -> MoveAnalysis:
    """Construit un MoveAnalysis sans passer par le moteur.

    Les cp sont toujours exprimés du point de vue des blancs, comme le fait
    Stockfish. `second_cp` alimente la deuxième variante : sans elle la
    position passerait pour forcée.
    """
    board = chess.Board(fen)
    move = board.parse_san(san)
    best_move = board.parse_san(best_san) if best_san else move

    score_avant = (
        chess.engine.Mate(mate_before)
        if mate_before is not None
        else chess.engine.Cp(cp_before)
    )
    score_apres = (
        chess.engine.Mate(mate_after)
        if mate_after is not None
        else chess.engine.Cp(cp_after)
    )

    lignes = [
        Line(
            move=best_move,
            san=board.san(best_move),
            score_white=score_avant,
            pv=[best_move],
        )
    ]
    if second_cp is not None:
        autre = next(m for m in board.legal_moves if m != best_move)
        lignes.append(
            Line(
                move=autre,
                san=board.san(autre),
                score_white=chess.engine.Cp(second_cp),
                pv=[autre],
            )
        )

    before = PositionAnalysis(fen=fen, turn=board.turn, lines=lignes, depth=16)

    apres_board = board.copy()
    apres_board.push(move)
    reponse = (
        apres_board.parse_san(reply_san)
        if reply_san
        else next(iter(apres_board.legal_moves), None)
    )
    lignes_apres = (
        [
            Line(
                move=reponse,
                san=apres_board.san(reponse),
                score_white=score_apres,
                pv=[reponse],
            )
        ]
        if reponse is not None
        else []
    )
    after = PositionAnalysis(
        fen=apres_board.fen(), turn=apres_board.turn, lines=lignes_apres, depth=16
    )

    return MoveAnalysis(
        ply=ply,
        move_number=board.fullmove_number,
        turn=board.turn,
        move=move,
        san=san,
        fen_before=fen,
        before=before,
        after=after,
    )


def quelconque(fen: str, san: str, cp_before: int, cp_after: int, **kw) -> MoveAnalysis:
    """Raccourci : un coup non optimal, avec deux variantes très proches."""
    kw.setdefault("best_san", "d4" if fen == ITALIENNE else "e5")
    kw.setdefault("second_cp", cp_before - 1)
    return fabrique(fen, san, cp_before, cp_after, **kw)


# --------------------------------------------------------------------------
# Cohérence de l'énumération
# --------------------------------------------------------------------------


def test_toutes_les_classes_ont_un_libelle_et_un_symbole():
    for classe in MoveClass:
        assert classe.label
        assert isinstance(classe.symbol, str)


def test_is_mistake_ne_couvre_que_les_fautes():
    fautes = {c for c in MoveClass if c.is_mistake}
    assert fautes == {
        MoveClass.INACCURACY,
        MoveClass.MISTAKE,
        MoveClass.MISS,
        MoveClass.BLUNDER,
    }


# --------------------------------------------------------------------------
# Mesures
# --------------------------------------------------------------------------


def test_material_balance_position_initiale():
    board = chess.Board()
    assert material_balance(board, chess.WHITE) == 0.0
    assert material_balance(board, chess.BLACK) == 0.0


def test_material_balance_dame_en_moins():
    board = chess.Board()
    board.remove_piece_at(chess.D8)  # dame noire
    assert material_balance(board, chess.WHITE) == 9.0
    assert material_balance(board, chess.BLACK) == -9.0


def test_sacrifice_amount_compte_apres_la_reprise():
    """Cxe5 puis Cxe5 : un cavalier contre un pion, soit deux pions nets."""
    analysis = fabrique(ITALIENNE, "Nxe5", 0, 0, reply_san="Nxe5")
    assert sacrifice_amount(analysis) == pytest.approx(2.0)


def test_sacrifice_amount_nul_sur_un_coup_calme():
    analysis = fabrique(ITALIENNE, "d3", 0, 0, reply_san="d6")
    assert sacrifice_amount(analysis) == pytest.approx(0.0)


def test_best_line_gap_sans_deuxieme_variante():
    analysis = fabrique(ITALIENNE, "d4", 0, 0)
    assert best_line_gap(analysis) == 0.0


def test_best_line_gap_mesure_l_ecart():
    analysis = fabrique(ITALIENNE, "d4", 0, 0, second_cp=-200)
    assert best_line_gap(analysis) == pytest.approx(0.176, abs=0.01)


def test_best_line_gap_cote_noir():
    """Côté noir, c'est le score le plus négatif qui est le meilleur."""
    analysis = fabrique(APRES_E4, "e5", -0, 0, best_san="e5", second_cp=200)
    assert best_line_gap(analysis) > 0.0


def test_move_accuracy_coup_parfait():
    assert move_accuracy(0.0) == pytest.approx(100.0, abs=0.01)


def test_move_accuracy_coup_ameliorant():
    """Un coup qui améliore la position ne dépasse pas 100."""
    assert move_accuracy(-0.2) == 100.0


def test_move_accuracy_courbe_chesscom():
    """Valeurs de référence de la courbe adoptée."""
    assert move_accuracy(0.05) == pytest.approx(49.7, abs=0.5)
    assert move_accuracy(0.10) == pytest.approx(24.7, abs=0.5)
    assert move_accuracy(0.20) == pytest.approx(6.1, abs=0.5)


def test_move_accuracy_decroissante():
    assert move_accuracy(0.0) > move_accuracy(0.05) > move_accuracy(0.30)


def test_move_accuracy_bornee():
    assert 0.0 <= move_accuracy(1.0) <= 100.0


# --------------------------------------------------------------------------
# Classification : cas simples
# --------------------------------------------------------------------------


def test_theorique_prime_sur_tout():
    analysis = quelconque(ITALIENNE, "d3", 0, -400)  # objectivement une gaffe
    assert classify_move(analysis, is_book=True) is MoveClass.BOOK


def test_coup_force_a_sa_propre_categorie():
    """chess-game-review distingue « forcé » de « meilleur »."""
    analysis = fabrique(FORCEE, "Kg2", 0, 0)
    assert analysis.before.is_forced
    assert classify_move(analysis) is MoveClass.FORCED


def test_coup_du_moteur_est_marque_meilleur():
    analysis = fabrique(ITALIENNE, "d4", 0, 0, best_san="d4", second_cp=-1)
    assert classify_move(analysis) is MoveClass.BEST


@pytest.mark.parametrize(
    "cp_after, attendu",
    [
        (-20, MoveClass.EXCELLENT),
        (-40, MoveClass.GOOD),
        (-100, MoveClass.INACCURACY),
        (-200, MoveClass.MISTAKE),
        (-400, MoveClass.BLUNDER),
    ],
)
def test_seuils_depuis_une_position_egale(cp_after, attendu):
    """Grille « position égale » : 0, −25, −50, −150, −250 centipions."""
    analysis = quelconque(ITALIENNE, "d3", 0, cp_after)
    assert classify_move(analysis) is attendu


def test_occasion_manquee_en_position_gagnee():
    """Même chute, mais depuis une position nettement gagnante."""
    analysis = quelconque(ITALIENNE, "d3", 400, 0)
    assert classify_move(analysis) is MoveClass.MISS


def test_la_meme_chute_en_position_egale_est_une_gaffe():
    analysis = quelconque(ITALIENNE, "d3", 0, -400)
    assert classify_move(analysis) is MoveClass.BLUNDER


def test_point_de_vue_noir():
    """Pour les noirs, un score blanc qui monte est une dégradation."""
    analysis = fabrique(
        APRES_E4, "a6", 0, 400, best_san="e5", second_cp=-1
    )
    assert classify_move(analysis) is MoveClass.BLUNDER


# --------------------------------------------------------------------------
# Classification : brillant et trouvaille
# --------------------------------------------------------------------------


def brillant(**surcharges) -> MoveAnalysis:
    """Un sacrifice de cavalier qui coche toutes les conditions."""
    defauts = dict(
        fen=ITALIENNE,
        san="Nxe5",
        cp_before=0,
        cp_after=20,
        best_san="Nxe5",
        second_cp=-150,
        reply_san="Nxe5",
    )
    defauts.update(surcharges)
    return fabrique(**defauts)


def test_brillant_sacrifice_avec_compensation():
    assert classify_move(brillant()) is MoveClass.BRILLIANT


def test_offers_material_detecte_la_reprise():
    assert offers_material(brillant())


def test_offers_material_faux_si_la_reprise_est_ailleurs():
    """Une pièce qui pendait déjà n'est pas un sacrifice du coup joué."""
    analysis = fabrique(
        ITALIENNE, "d3", 0, 20, best_san="d3", second_cp=-150, reply_san="Nd4"
    )
    assert not offers_material(analysis)


def test_pas_brillant_si_la_piece_pendait_deja():
    """Le cas qui produisait des faux positifs : perte réelle, mais antérieure."""
    analysis = fabrique(
        ITALIENNE, "d3", 0, 20, best_san="d3", second_cp=-150, reply_san="Nd4"
    )
    assert classify_move(analysis) is not MoveClass.BRILLIANT


def test_pas_brillant_si_pas_strictement_le_meilleur():
    """« Quasi optimal » ne suffit plus."""
    assert classify_move(brillant(best_san="d4")) is not MoveClass.BRILLIANT


def test_pas_brillant_sans_compensation():
    """Sacrifice qui laisse la position au niveau de l'alternative tranquille."""
    assert classify_move(brillant(second_cp=-5)) is not MoveClass.BRILLIANT


def test_pas_brillant_si_on_reste_moins_bien():
    assert classify_move(brillant(cp_after=-150)) is not MoveClass.BRILLIANT


def test_brillant_si_le_sacrifice_mate():
    """Le mat dispense de l'exigence d'écart : c'est la compensation ultime."""
    analysis = brillant(second_cp=-5)
    # On force un mat dans l'analyse d'après.
    analysis.after.lines[0] = Line(
        move=analysis.after.lines[0].move,
        san=analysis.after.lines[0].san,
        score_white=chess.engine.Mate(2),
        pv=analysis.after.lines[0].pv,
    )
    assert analysis.mate_for_mover == 2
    assert classify_move(analysis) is MoveClass.BRILLIANT


def test_pas_brillant_si_le_sacrifice_se_fait_mater():
    analysis = brillant()
    analysis.after.lines[0] = Line(
        move=analysis.after.lines[0].move,
        san=analysis.after.lines[0].san,
        score_white=chess.engine.Mate(-3),
        pv=analysis.after.lines[0].pv,
    )
    assert classify_move(analysis) is not MoveClass.BRILLIANT


def test_pas_brillant_si_le_sacrifice_perd():
    analysis = fabrique(
        ITALIENNE, "Nxe5", 0, -400, best_san="d4", second_cp=-50, reply_san="Nxe5"
    )
    assert classify_move(analysis) is MoveClass.BLUNDER


def test_pas_brillant_si_deja_gagnant():
    """Sacrifier quand on gagne déjà largement n'a rien de remarquable."""
    assert classify_move(brillant(cp_before=900, cp_after=900)) is not MoveClass.BRILLIANT


def test_pas_brillant_sans_sacrifice():
    analysis = fabrique(
        ITALIENNE, "d4", 0, 0, best_san="d4", second_cp=-1, reply_san="exd4"
    )
    assert classify_move(analysis) is not MoveClass.BRILLIANT


def test_pas_brillant_pour_un_simple_pion():
    """Un pion offert ne suffit pas : le seuil est à une pièce mineure."""
    analysis = fabrique(
        ITALIENNE, "d4", 0, 20, best_san="d4", second_cp=-150, reply_san="exd4"
    )
    assert classify_move(analysis) is not MoveClass.BRILLIANT


def test_trouvaille_seul_coup_jouable():
    analysis = fabrique(
        ITALIENNE, "d4", 0, 0, best_san="d4", second_cp=-200, reply_san="exd4"
    )
    assert classify_move(analysis) is MoveClass.GREAT


def test_pas_de_trouvaille_si_plusieurs_bons_coups():
    analysis = fabrique(
        ITALIENNE, "d4", 0, 0, best_san="d4", second_cp=-5, reply_san="exd4"
    )
    assert classify_move(analysis) is MoveClass.BEST


def test_badges_ajoutes_desactivables():
    """Sans eux, on retrouve exactement les huit catégories d'origine."""
    analysis = brillant()
    assert classify_move(analysis) is MoveClass.BRILLIANT

    sans = ClassifierConfig(detect_special=False)
    assert classify_move(analysis, config=sans) is not MoveClass.BRILLIANT


def test_occasion_manquee_desactivable():
    analysis = coup_de_mat(mate_before=3, cp_after=150)
    assert classify_move(analysis) is MoveClass.MISS
    assert (
        classify_move(analysis, config=ClassifierConfig(detect_special=False))
        is MoveClass.BLUNDER
    )


# --------------------------------------------------------------------------
# Rapport de partie
# --------------------------------------------------------------------------


def partie_fictive() -> list[MoveAnalysis]:
    """Deux coups blancs, deux coups noirs, dont une gaffe blanche."""
    return [
        quelconque(ITALIENNE, "d3", 0, -10, ply=1),
        quelconque(APRES_E4, "a6", 0, 10, ply=2),
        quelconque(ITALIENNE, "d3", 0, -400, ply=3),
        quelconque(APRES_E4, "a6", 0, 10, ply=4),
    ]


def test_build_report_compte_les_coups():
    report = build_report(partie_fictive())
    assert len(report.moves) == 4
    assert sum(report.white.counts.values()) == 2
    assert sum(report.black.counts.values()) == 2


def test_build_report_precision_penalise_la_gaffe():
    report = build_report(partie_fictive())
    assert report.white.accuracy < report.black.accuracy
    assert 0.0 <= report.white.accuracy <= 100.0


def test_build_report_isole_les_fautes():
    report = build_report(partie_fictive())
    assert len(report.mistakes()) == 1
    assert len(report.mistakes(chess.WHITE)) == 1
    assert report.mistakes(chess.BLACK) == []
    assert report.white.mistakes == 1


def test_book_plies_marque_et_exclut_la_theorie():
    report = build_report(partie_fictive(), book_plies=2)
    assert report.moves[0].classification is MoveClass.BOOK
    assert report.moves[1].classification is MoveClass.BOOK
    assert report.moves[2].classification is not MoveClass.BOOK
    # Les coups théoriques comptent dans la moyenne : leur précision est de
    # 100, ce qui la tire vers le haut sans la fausser.
    sans_livre = build_report(partie_fictive())
    assert report.black.accuracy >= sans_livre.black.accuracy


def test_for_color():
    report = build_report(partie_fictive())
    assert report.for_color(chess.WHITE) is report.white
    assert report.for_color(chess.BLACK) is report.black


def test_affichage_lisible():
    report = build_report(partie_fictive())
    texte = str(report.moves[0])
    assert "d3" in texte
    assert report.moves[0].classification.label in texte


# --------------------------------------------------------------------------
# Intégration avec le moteur
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def moteur():
    with ChessEngine(config=EngineConfig(nodes=60_000, multipv=2, hash_mb=32)) as e:
        yield e


def test_integration_le_mat_du_sot_est_une_gaffe(moteur):
    board = chess.Board()
    moves = []
    b = board.copy()
    for san in ("f3", "e5", "g4"):
        m = b.parse_san(san)
        moves.append(m)
        b.push(m)

    analyses = moteur.analyse_moves(moves, board)
    report = build_report(analyses)
    assert report.moves[-1].classification is MoveClass.BLUNDER
    assert report.white.accuracy < report.black.accuracy


def test_integration_rapport_sur_une_ouverture_correcte(moteur):
    board = chess.Board()
    moves = []
    b = board.copy()
    for san in ("e4", "e5", "Nf3", "Nc6"):
        m = b.parse_san(san)
        moves.append(m)
        b.push(m)

    report = build_report(moteur.analyse_moves(moves, board))
    assert report.mistakes() == []
    # La courbe de précision adoptée est bien plus sévère que celle de
    # Lichess : 70 sur une ouverture correcte analysée à faible profondeur est
    # attendu, et c'est précisément ce qui aligne les scores sur chess.com.
    assert report.white.accuracy > 60
    assert report.black.accuracy > 60


# --------------------------------------------------------------------------
# Mats — la branche que les centipions ne savent pas juger
# --------------------------------------------------------------------------


def coup_de_mat(**surcharges) -> MoveAnalysis:
    """Un coup blanc quelconque, avec des scores de mat paramétrables."""
    defauts = dict(
        fen=ITALIENNE,
        san="d3",
        cp_before=0,
        cp_after=0,
        best_san="d4",
        second_cp=-1,
    )
    defauts.update(surcharges)
    return fabrique(**defauts)


def test_mat_conserve_a_la_meme_distance():
    # best_san="d3" : on joue bien le coup du moteur, sinon le plafond
    # « meilleur réservé à la recommandation » s'appliquerait.
    analysis = coup_de_mat(mate_before=4, mate_after=4, best_san="d3", second_cp=700)
    assert classify_move(analysis) is MoveClass.BEST


def test_mat_accelere():
    analysis = coup_de_mat(mate_before=6, mate_after=3, best_san="d3", second_cp=700)
    assert classify_move(analysis) is MoveClass.BEST


def test_mat_repousse_de_deux_coups():
    analysis = coup_de_mat(mate_before=2, mate_after=4)
    assert classify_move(analysis) is MoveClass.EXCELLENT


def test_mat_repousse_de_cinq_coups():
    """Jusqu'à sept coups de retard restent « excellent » chez eux."""
    analysis = coup_de_mat(mate_before=2, mate_after=7)
    assert classify_move(analysis) is MoveClass.EXCELLENT


def test_mat_repousse_tres_loin():
    """Le cas que le plafonnement à 1000 centipions rendait invisible."""
    analysis = coup_de_mat(mate_before=2, mate_after=14)
    assert classify_move(analysis) is MoveClass.GOOD


def test_mat_perdu_mais_position_toujours_gagnee():
    analysis = coup_de_mat(mate_before=3, cp_after=800)
    assert classify_move(analysis) is MoveClass.INACCURACY


def test_mat_perdu_avantage_moyen():
    analysis = coup_de_mat(mate_before=3, cp_after=400)
    assert classify_move(analysis) is MoveClass.MISTAKE


def test_mat_perdu_avantage_modeste():
    analysis = coup_de_mat(mate_before=3, cp_after=150)
    assert classify_move(analysis) is MoveClass.MISS


def test_mat_perdu_et_position_perdue():
    """Gaffe requalifiée en occasion manquée : on gagnait avant le coup."""
    analysis = coup_de_mat(mate_before=3, cp_after=-200)
    assert classify_move(analysis) is MoveClass.MISS


def test_se_faire_mater_depuis_une_position_tenable():
    analysis = coup_de_mat(cp_before=0, mate_after=-3)
    assert classify_move(analysis) is MoveClass.BLUNDER


def test_se_faire_mater_depuis_une_position_deja_mauvaise():
    analysis = coup_de_mat(cp_before=-500, mate_after=-3)
    assert classify_move(analysis) is MoveClass.MISTAKE


def test_se_faire_mater_depuis_une_position_perdue():
    """Quand tout est déjà perdu, le mat n'ajoute pas grand-chose."""
    analysis = coup_de_mat(cp_before=-800, mate_after=-3)
    assert classify_move(analysis) is MoveClass.INACCURACY


def test_defense_qui_repousse_le_mat_adverse():
    analysis = coup_de_mat(mate_before=-2, mate_after=-6, best_san="d3", second_cp=700)
    assert classify_move(analysis) is MoveClass.BEST


def test_defense_qui_accelere_sa_propre_perte():
    analysis = coup_de_mat(mate_before=-6, mate_after=-2)
    assert classify_move(analysis) is MoveClass.EXCELLENT


def test_mat_evite():
    analysis = coup_de_mat(mate_before=-3, cp_after=-200, best_san="d3", second_cp=700)
    assert classify_move(analysis) is MoveClass.BEST


def test_le_coup_du_moteur_echappe_a_la_branche_mat():
    """Jouer le coup du moteur ne peut jamais être sanctionné.

    Ici le mat passe de 2 à 9 coups, mais c'est la ligne principale : la
    branche mat ne doit pas s'y substituer.
    """
    analysis = coup_de_mat(
        san="d4", best_san="d4", mate_before=2, mate_after=9, second_cp=-1
    )
    assert classify_move(analysis) in (MoveClass.BEST, MoveClass.GREAT)
    assert not classify_move(analysis).is_mistake


def test_seul_coup_menant_au_mat_est_une_trouvaille():
    """Un écart énorme avec la deuxième variante, c'est la définition."""
    analysis = coup_de_mat(
        san="d4", best_san="d4", mate_before=2, mate_after=2, second_cp=-300
    )
    assert classify_move(analysis) is MoveClass.GREAT


def test_theorique_prime_toujours_sur_le_mat():
    analysis = coup_de_mat(mate_before=2, mate_after=20)
    assert classify_move(analysis, is_book=True) is MoveClass.BOOK


# --------------------------------------------------------------------------
# Critères empruntés à Chesskit
# --------------------------------------------------------------------------


def test_reprise_simple_detectee():
    """Bxc6 puis dxc6 : le second coup reprend sur la case du premier."""
    precedent = fabrique(
        "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
        "Bxc6", 0, 0, best_san="O-O", second_cp=-10,
    )
    board = chess.Board(precedent.fen_before)
    board.push(precedent.move)
    # Trait aux noirs : une alternative pire porte un cp_white positif.
    reprise = fabrique(board.fen(), "dxc6", 0, 0, best_san="dxc6", second_cp=300)

    assert is_simple_recapture(reprise, precedent)


def test_reprise_simple_n_est_pas_une_trouvaille():
    """Sans ce garde-fou, toute reprise forcée décrocherait le badge."""
    precedent = fabrique(
        "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
        "Bxc6", 0, 0, best_san="O-O", second_cp=-10,
    )
    board = chess.Board(precedent.fen_before)
    board.push(precedent.move)
    reprise = fabrique(board.fen(), "dxc6", 0, 0, best_san="dxc6", second_cp=300)

    assert classify_move(reprise, previous=precedent) is MoveClass.BEST
    # Sans le coup précédent, l'écart seul suffirait.
    assert classify_move(reprise) is MoveClass.GREAT


def test_coup_sans_rapport_n_est_pas_une_reprise():
    precedent = fabrique(ITALIENNE, "d4", 0, 0, best_san="d4", second_cp=-10)
    suivant = fabrique(APRES_E4, "a6", 0, 0, best_san="a6", second_cp=-10)
    assert not is_simple_recapture(suivant, precedent)


def test_changement_d_issue_detecte():
    """De −2.00 à +1.00 : la partie a changé de camp."""
    analysis = fabrique(ITALIENNE, "d4", -200, 100, best_san="d4", second_cp=-500)
    assert changes_outcome(analysis, ClassifierConfig())


def test_pas_de_changement_sans_traversee():
    """Progresser de +1.00 à +3.00 ne renverse rien."""
    analysis = fabrique(ITALIENNE, "d4", 100, 300, best_san="d4", second_cp=-10)
    assert not changes_outcome(analysis, ClassifierConfig())


def test_renversement_vaut_trouvaille():
    analysis = fabrique(ITALIENNE, "d4", -200, 100, best_san="d4", second_cp=-210)
    assert classify_move(analysis) is MoveClass.GREAT


def test_pas_de_trouvaille_si_l_alternative_gagnait_deja():
    """Trouver le bon coup quand tout gagne n'a aucun mérite."""
    analysis = fabrique(ITALIENNE, "d4", 900, 900, best_san="d4", second_cp=850)
    assert classify_move(analysis) is not MoveClass.GREAT


def test_pas_de_trouvaille_si_la_position_reste_perdue():
    analysis = fabrique(ITALIENNE, "d4", -600, -580, best_san="d4", second_cp=-900)
    assert classify_move(analysis) is not MoveClass.GREAT


def test_sacrifice_mesure_sur_la_variante():
    """Le décompte suit la ligne principale, pas seulement la reprise."""
    analysis = fabrique(
        ITALIENNE, "Nxe5", 0, 20, best_san="Nxe5", second_cp=-150, reply_san="Nxe5"
    )
    assert sacrifice_amount(analysis) == pytest.approx(2.0)


# --------------------------------------------------------------------------
# Grilles adaptatives de chess-game-review
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cp_before, cp_after, attendu",
    [
        # Largement gagnant avant et après : plancher à « imprécision ».
        (900, 500, MoveClass.INACCURACY),
        # Gagnant largement, puis avantage résiduel : gaffe d'office.
        (800, 100, MoveClass.BLUNDER),
        # Déjà perdu, et toujours perdu : on ne s'acharne pas.
        (-700, -1000, MoveClass.INACCURACY),
    ],
)
def test_cas_particuliers_cgr(cp_before, cp_after, attendu):
    analysis = quelconque(ITALIENNE, "d3", cp_before, cp_after)
    assert (
        classify_move(analysis, config=ClassifierConfig(detect_special=False))
        is attendu
    )


def test_grille_indulgente_quand_on_perdait_deja():
    """Même perte de 180 centipions, verdict différent selon le contexte.

    C'est tout l'intérêt des grilles doubles : lâcher du terrain quand on est
    déjà perdu se reproche moins que le faire en position gagnante.
    """
    sans = ClassifierConfig(detect_special=False)
    perdant = quelconque(ITALIENNE, "d3", -450, -630)
    gagnant = quelconque(ITALIENNE, "d3", 450, 270)

    assert classify_move(perdant, config=sans) is MoveClass.GOOD
    assert classify_move(gagnant, config=sans) is MoveClass.INACCURACY


def test_mat_delivre_est_le_meilleur_coup():
    """Cas que leur code classe par erreur en gaffe."""
    depart = "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5Q2/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
    analysis = fabrique(depart, "Qxf7#", 200, 0, best_san="Qxf7#", second_cp=-10)
    assert analysis.after.outcome_white == 1.0
    assert (
        classify_move(analysis, config=ClassifierConfig(detect_special=False))
        is MoveClass.BEST
    )
    # Avec les badges ajoutés, un mat mérite mieux qu'un simple « meilleur ».
    assert classify_move(analysis) in (MoveClass.BEST, MoveClass.GREAT)


def test_le_coup_recommande_est_toujours_le_meilleur():
    """Jouer la tête de liste du moteur ne peut jamais valoir moins.

    Les deux positions étant analysées séparément, l'évaluation d'après est
    souvent un peu moins favorable — sans ce raccourci, le coup parfait
    ressortirait en « excellent ».
    """
    analysis = fabrique(
        ITALIENNE, "d4", 0, -30, best_san="d4", second_cp=-35
    )
    assert analysis.is_best
    assert classify_move(analysis) is MoveClass.BEST


def test_un_autre_coup_reste_juge_sur_l_evaluation():
    analysis = fabrique(
        ITALIENNE, "d3", 0, -30, best_san="d4", second_cp=-1
    )
    assert not analysis.is_best
    # −30 centipions depuis l'égalité : dans la grille, au-delà de « excellent ».
    assert classify_move(analysis) is MoveClass.GOOD


def test_meilleur_reserve_au_coup_du_moteur():
    """Un coup qui conserve l'avantage sans être le bon n'est pas « meilleur ».

    Cas réel : +7.21 vers +7.28, donc un delta positif. La grille rendait
    « meilleur » alors que le moteur recommandait un autre coup.
    """
    analysis = fabrique(
        ITALIENNE, "d3", 721, 728, best_san="d4", second_cp=700
    )
    assert not analysis.is_best
    assert classify_by_eval(analysis) is MoveClass.BEST
    assert classify_move(analysis) is MoveClass.EXCELLENT


def test_le_bon_coup_garde_meilleur():
    analysis = fabrique(
        ITALIENNE, "d4", 721, 728, best_san="d4", second_cp=700
    )
    assert classify_move(analysis) is MoveClass.BEST