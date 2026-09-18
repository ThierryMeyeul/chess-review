"""Tests du module core.database.

Tournent sur SQLite en mémoire. C'est la raison d'être de SQLAlchemy ici : la
même couche sert MySQL en production et un fichier éphémère en test, donc la
suite reste lançable sans serveur allumé.
"""

from __future__ import annotations

from datetime import datetime

import chess
import chess.engine
import pytest
from sqlalchemy import create_engine

from src.core.classify import ClassifiedMove, GameReport, MoveClass, PlayerReport
from src.core.database import (
    DatabaseConfig,
    GameRepository,
    stored_to_report,
)
from src.core.engine import Line, MoveAnalysis, PositionAnalysis

PGN = '[White "a"]\n[Black "b"]\n\n1. e4 e5 2. Nf3 Nc6 *\n'
COUPS = ["e4", "e5", "Nf3", "Nc6"]


@pytest.fixture
def depot() -> GameRepository:
    repo = GameRepository(create_engine("sqlite://"))
    repo.create_all()
    return repo


def faux_rapport(classifications: list[MoveClass] | None = None) -> GameReport:
    classifications = classifications or [
        MoveClass.BOOK,
        MoveClass.BOOK,
        MoveClass.BEST,
        MoveClass.BLUNDER,
    ]
    board = chess.Board()
    coups: list[ClassifiedMove] = []
    for index, classification in enumerate(classifications):
        move = board.parse_san(COUPS[index])
        trait = board.turn
        fen = board.fen()
        ligne = Line(
            move=move, san=COUPS[index], score_white=chess.engine.Cp(25 * index), pv=[move]
        )
        avant = PositionAnalysis(fen=fen, turn=trait, lines=[ligne, ligne], depth=16)
        board.push(move)
        apres = PositionAnalysis(
            fen=board.fen(), turn=board.turn, lines=[ligne, ligne], depth=16
        )
        coups.append(
            ClassifiedMove(
                analysis=MoveAnalysis(
                    ply=index + 1,
                    move_number=(index // 2) + 1,
                    turn=trait,
                    move=move,
                    san=COUPS[index],
                    fen_before=fen,
                    before=avant,
                    after=apres,
                ),
                classification=classification,
                accuracy=90.0 - index,
            )
        )
    return GameReport(
        moves=coups,
        white=PlayerReport(color=chess.WHITE, accuracy=88.5),
        black=PlayerReport(color=chess.BLACK, accuracy=93.2),
    )


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def test_url_contient_les_parametres():
    config = DatabaseConfig(host="h", port=1234, database="d", user="u", password="p")
    assert "u:p@h:1234/d" in config.url
    assert "charset=utf8mb4" in config.url


def test_url_echappe_les_caracteres_speciaux():
    """Un « @ » ou un « / » dans le mot de passe casserait l'URL."""
    config = DatabaseConfig(user="u", password="a@b/c")
    assert "a%40b%2Fc" in config.url
    assert "a@b/c" not in config.url


def test_url_masquee_cache_le_mot_de_passe():
    config = DatabaseConfig(user="meyeul", password="secret")
    assert "secret" not in config.url_masquee
    assert "meyeul" in config.url_masquee


def test_url_sans_mot_de_passe():
    config = DatabaseConfig(user="u", password="")
    assert "u@" in config.url


def test_configured():
    assert not DatabaseConfig().configured
    assert DatabaseConfig(user="u", database="d").configured


def test_from_env(monkeypatch):
    monkeypatch.setenv("DB_HOST", "serveur")
    monkeypatch.setenv("DB_PORT", "3307")
    monkeypatch.setenv("DB_NAME", "base")
    monkeypatch.setenv("DB_USER", "jo")
    monkeypatch.setenv("DB_PASSWORD", "motdepasse")
    config = DatabaseConfig.from_env()
    assert (config.host, config.port, config.database, config.user) == (
        "serveur",
        3307,
        "base",
        "jo",
    )


# --------------------------------------------------------------------------
# Schéma et connexion
# --------------------------------------------------------------------------


def test_ping(depot: GameRepository):
    assert depot.ping() is True


def test_create_all_idempotent(depot: GameRepository):
    depot.create_all()  # ne doit pas lever une seconde fois


def test_stats_vides(depot: GameRepository):
    assert depot.stats() == {"games": 0, "analyses": 0}


# --------------------------------------------------------------------------
# Parties
# --------------------------------------------------------------------------


def test_save_game_rend_un_identifiant(depot: GameRepository):
    identifiant = depot.save_game(PGN, white="a", black="b")
    assert isinstance(identifiant, int)
    assert depot.stats()["games"] == 1


def test_get_game(depot: GameRepository):
    identifiant = depot.save_game(PGN, white="nakul60", black="Thierry", eco="C68")
    partie = depot.get_game(identifiant)
    assert partie.white == "nakul60"
    assert partie.eco == "C68"
    assert partie.pgn == PGN


def test_get_game_inexistante(depot: GameRepository):
    assert depot.get_game(999) is None


def test_reimport_ne_cree_pas_de_doublon(depot: GameRepository):
    """L'URL chess.com sert de clé naturelle."""
    url = "https://www.chess.com/game/live/1"
    premier = depot.save_game(PGN, source_url=url, white="a")
    second = depot.save_game(PGN, source_url=url, white="a-corrige")

    assert premier == second
    assert depot.stats()["games"] == 1
    assert depot.get_game(premier).white == "a-corrige"


def test_parties_sans_url_sont_distinctes(depot: GameRepository):
    depot.save_game(PGN)
    depot.save_game(PGN)
    assert depot.stats()["games"] == 2


def test_list_games_plus_recentes_d_abord(depot: GameRepository):
    depot.save_game(PGN, white="ancienne", played_at=datetime(2024, 1, 1))
    depot.save_game(PGN, white="recente", played_at=datetime(2026, 1, 1))
    assert [p.white for p in depot.list_games()] == ["recente", "ancienne"]


def test_list_games_recherche(depot: GameRepository):
    depot.save_game(PGN, white="meyeul", black="autre")
    depot.save_game(PGN, white="inconnu", black="encore")
    assert [p.white for p in depot.list_games(search="meye")] == ["meyeul"]


def test_list_games_recherche_sur_l_ouverture(depot: GameRepository):
    depot.save_game(PGN, white="a", opening="Ruy Lopez: Exchange")
    assert len(depot.list_games(search="Ruy")) == 1


def test_list_games_limite(depot: GameRepository):
    for _ in range(5):
        depot.save_game(PGN)
    assert len(depot.list_games(limit=2)) == 2


def test_delete_game(depot: GameRepository):
    identifiant = depot.save_game(PGN)
    depot.delete_game(identifiant)
    assert depot.get_game(identifiant) is None


def test_label_lisible(depot: GameRepository):
    identifiant = depot.save_game(
        PGN, white="a", black="b", played_at=datetime(2026, 3, 4)
    )
    assert depot.get_game(identifiant).label == "2026-03-04  a — b"


# --------------------------------------------------------------------------
# Analyses
# --------------------------------------------------------------------------


def test_save_analysis(depot: GameRepository):
    partie = depot.save_game(PGN)
    identifiant = depot.save_analysis(partie, faux_rapport(), depth=18, book_plies=2)
    assert isinstance(identifiant, int)
    assert depot.stats()["analyses"] == 1


def test_analysis_meta(depot: GameRepository):
    partie = depot.save_game(PGN)
    depot.save_analysis(partie, faux_rapport(), depth=18, book_plies=2)
    meta = depot.analysis_meta(partie)
    assert meta["depth"] == 18
    assert meta["book_plies"] == 2
    assert meta["white_accuracy"] == pytest.approx(88.5)


def test_analysis_meta_absente(depot: GameRepository):
    assert depot.analysis_meta(depot.save_game(PGN)) is None


def test_reanalyse_remplace_la_precedente(depot: GameRepository):
    """Garder dix analyses de la même partie n'a aucun intérêt."""
    partie = depot.save_game(PGN)
    depot.save_analysis(partie, faux_rapport(), depth=12)
    depot.save_analysis(partie, faux_rapport(), depth=20)

    assert depot.stats()["analyses"] == 1
    assert depot.analysis_meta(partie)["depth"] == 20


def test_replace_false_conserve_les_deux(depot: GameRepository):
    partie = depot.save_game(PGN)
    depot.save_analysis(partie, faux_rapport(), depth=12)
    depot.save_analysis(partie, faux_rapport(), depth=20, replace=False)
    assert depot.stats()["analyses"] == 2


def test_supprimer_la_partie_supprime_l_analyse(depot: GameRepository):
    partie = depot.save_game(PGN)
    depot.save_analysis(partie, faux_rapport())
    depot.delete_game(partie)
    assert depot.stats()["analyses"] == 0


# --------------------------------------------------------------------------
# Aller-retour
# --------------------------------------------------------------------------


def test_relecture_restitue_les_badges(depot: GameRepository):
    partie = depot.save_game(PGN)
    depot.save_analysis(partie, faux_rapport())

    rapport = depot.latest_report(partie)
    assert [c.classification for c in rapport.moves] == [
        MoveClass.BOOK,
        MoveClass.BOOK,
        MoveClass.BEST,
        MoveClass.BLUNDER,
    ]


def test_relecture_restitue_les_coups(depot: GameRepository):
    partie = depot.save_game(PGN)
    depot.save_analysis(partie, faux_rapport())

    rapport = depot.latest_report(partie)
    assert [c.san for c in rapport.moves] == COUPS
    assert [c.analysis.ply for c in rapport.moves] == [1, 2, 3, 4]
    assert rapport.moves[0].turn == chess.WHITE
    assert rapport.moves[1].turn == chess.BLACK


def test_relecture_restitue_les_precisions(depot: GameRepository):
    partie = depot.save_game(PGN)
    depot.save_analysis(partie, faux_rapport())

    rapport = depot.latest_report(partie)
    assert rapport.white.accuracy == pytest.approx(88.5)
    assert rapport.black.accuracy == pytest.approx(93.2)
    assert rapport.moves[0].accuracy == pytest.approx(90.0)


def test_relecture_restitue_les_evaluations(depot: GameRepository):
    partie = depot.save_game(PGN)
    depot.save_analysis(partie, faux_rapport())

    origine = faux_rapport()
    relu = depot.latest_report(partie)
    for avant, apres in zip(origine.moves, relu.moves):
        assert apres.analysis.cp_before == avant.analysis.cp_before
        assert apres.analysis.cp_after == avant.analysis.cp_after


def test_relecture_restitue_le_coup_recommande(depot: GameRepository):
    partie = depot.save_game(PGN)
    depot.save_analysis(partie, faux_rapport())

    relu = depot.latest_report(partie)
    assert relu.moves[0].analysis.best_san == "e4"


def test_relecture_ne_prend_pas_les_positions_pour_forcees(depot: GameRepository):
    """Une position relue n'a qu'une variante stockée : il faut l'empêcher
    d'être classée « coup forcé »."""
    partie = depot.save_game(PGN)
    depot.save_analysis(partie, faux_rapport())

    relu = depot.latest_report(partie)
    assert not relu.moves[0].analysis.before.is_forced


def test_relecture_compte_les_fautes(depot: GameRepository):
    partie = depot.save_game(PGN)
    depot.save_analysis(partie, faux_rapport())

    relu = depot.latest_report(partie)
    assert len(relu.mistakes()) == 1
    assert relu.mistakes()[0].san == "Nc6"


def test_latest_report_absent(depot: GameRepository):
    assert depot.latest_report(depot.save_game(PGN)) is None


def test_mat_est_conserve(depot: GameRepository):
    rapport = faux_rapport()
    dernier = rapport.moves[-1].analysis
    dernier.after.lines[0] = Line(
        move=dernier.after.lines[0].move,
        san="x",
        score_white=chess.engine.Mate(3),
        pv=[],
    )
    partie = depot.save_game(PGN)
    depot.save_analysis(partie, rapport)

    relu = depot.latest_report(partie)
    assert relu.moves[-1].analysis.after.mate_white == 3


def test_tri_compatible_mysql():
    """« NULLS LAST » est du PostgreSQL : MariaDB le refuse.

    SQLite l'accepte, donc seul un test sur le dialecte MySQL attrape le
    problème avant la production.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects import mysql

    from src.core.database import Game

    requete = select(Game).order_by(
        Game.played_at.is_(None).asc(),
        Game.played_at.desc(),
        Game.created_at.desc(),
    )
    sql = str(requete.compile(dialect=mysql.dialect()))
    assert "NULLS LAST" not in sql.upper()


def test_liste_place_les_parties_sans_date_a_la_fin(depot: GameRepository):
    depot.save_game(PGN, white="sans_date")
    depot.save_game(PGN, white="datee", played_at=datetime(2026, 1, 1))
    assert [p.white for p in depot.list_games()] == ["datee", "sans_date"]