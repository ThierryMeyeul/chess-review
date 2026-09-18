"""Tests du module core.fetch.

Aucun appel réseau : la session HTTP est remplacée par un faux transport qui
rend des réponses préenregistrées. C'est pour ça que le client accepte une
session en paramètre — sans cette couture, tester ce module supposerait une
connexion et un pseudo réel, donc des tests lents et non reproductibles.
"""

from __future__ import annotations

import chess
import pytest

from src.core.fetch import (
    BASE_URL,
    ChessComClient,
    ChessComError,
    GameSummary,
    PlayerNotFound,
    RateLimited,
)

PGN_COURT = (
    '[Event "Live Chess"]\n[White "nakul60"]\n[Black "Thierry-Meyeul"]\n'
    '[Result "0-1"]\n\n1. e4 e5 2. Nf3 Nc6 0-1\n'
)


def partie_api(**surcharges) -> dict:
    """Charge utile typique d'une partie renvoyée par l'API."""
    base = {
        "url": "https://www.chess.com/game/live/1",
        "pgn": PGN_COURT,
        "time_control": "600",
        "time_class": "rapid",
        "rated": True,
        "rules": "chess",
        "end_time": 1_700_000_000,
        "white": {"username": "nakul60", "rating": 1249, "result": "resigned"},
        "black": {"username": "Thierry-Meyeul", "rating": 1214, "result": "win"},
    }
    base.update(surcharges)
    return base


class FausseReponse:
    def __init__(self, status_code: int, payload=None, casse: bool = False) -> None:
        self.status_code = status_code
        self._payload = payload
        self._casse = casse

    def json(self):
        if self._casse:
            raise ValueError("JSON invalide")
        return self._payload


class FausseSession:
    """Transport simulé. Enregistre les appels pour pouvoir les vérifier."""

    def __init__(self, routes: dict[str, FausseReponse], defaut=None) -> None:
        self.routes = routes
        self.defaut = defaut or FausseReponse(404)
        self.appels: list[tuple[str, dict]] = []

    def get(self, url, headers, timeout):
        self.appels.append((url, headers))
        return self.routes.get(url, self.defaut)


class SessionQuiExplose:
    def get(self, url, headers, timeout):
        raise OSError("réseau injoignable")


def client(routes: dict, **kw) -> tuple[ChessComClient, FausseSession]:
    session = FausseSession(routes)
    return ChessComClient(session=session, **kw), session


# --------------------------------------------------------------------------
# GameSummary
# --------------------------------------------------------------------------


def test_from_api_lit_les_champs():
    partie = GameSummary.from_api(partie_api())
    assert partie.white == "nakul60"
    assert partie.black_rating == 1214
    assert partie.time_class == "rapid"
    assert partie.rated is True
    assert partie.rules == "chess"


def test_from_api_tolere_les_champs_manquants():
    partie = GameSummary.from_api({})
    assert partie.white == "?"
    assert partie.white_rating == 0
    assert partie.end_time is None
    assert partie.date == "?"


def test_date_formatee():
    assert GameSummary.from_api(partie_api()).date.startswith("2023-11")


def test_color_of_insensible_a_la_casse():
    partie = GameSummary.from_api(partie_api())
    assert partie.color_of("THIERRY-MEYEUL") is chess.BLACK
    assert partie.color_of("nakul60") is chess.WHITE
    assert partie.color_of("inconnu") is None


def test_opponent_of():
    partie = GameSummary.from_api(partie_api())
    assert partie.opponent_of("thierry-meyeul") == "nakul60"
    assert partie.opponent_of("inconnu") == "?"


def test_outcome_victoire_et_defaite():
    partie = GameSummary.from_api(partie_api())
    assert partie.outcome_for("Thierry-Meyeul") == "win"
    assert partie.outcome_for("nakul60") == "loss"


@pytest.mark.parametrize(
    "motif", ["agreed", "repetition", "stalemate", "insufficient", "50move"]
)
def test_outcome_nulle(motif):
    """Dans une nulle, les deux camps portent le même motif."""
    partie = GameSummary.from_api(
        partie_api(
            white={"username": "a", "rating": 1, "result": motif},
            black={"username": "b", "rating": 1, "result": motif},
        )
    )
    assert partie.outcome_for("a") == "draw"
    assert partie.outcome_for("b") == "draw"


def test_outcome_joueur_absent():
    assert GameSummary.from_api(partie_api()).outcome_for("personne") == "?"


def test_label_contient_l_adversaire():
    partie = GameSummary.from_api(partie_api())
    etiquette = partie.label("Thierry-Meyeul")
    assert "nakul60" in etiquette
    assert "rapid" in etiquette


def test_game_parse_le_pgn():
    partie = GameSummary.from_api(partie_api())
    game = partie.game()
    assert game is not None
    assert len(list(game.mainline_moves())) == 4


def test_game_sans_pgn():
    assert GameSummary.from_api(partie_api(pgn="")).game() is None


# --------------------------------------------------------------------------
# Transport et erreurs
# --------------------------------------------------------------------------


def test_user_agent_est_envoye():
    cli, session = client(
        {f"{BASE_URL}/player/jo": FausseReponse(200, {"username": "jo"})},
        user_agent="mon-agent/2.0",
    )
    cli.profile("jo")
    _, entetes = session.appels[0]
    assert entetes["User-Agent"] == "mon-agent/2.0"


def test_pseudo_normalise_en_minuscules():
    cli, session = client(
        {f"{BASE_URL}/player/jo": FausseReponse(200, {})},
    )
    cli.profile("  JO  ")
    assert session.appels[0][0] == f"{BASE_URL}/player/jo"


def test_404_devient_player_not_found():
    cli, _ = client({})
    with pytest.raises(PlayerNotFound):
        cli.profile("fantome")


def test_429_devient_rate_limited():
    cli, _ = client({f"{BASE_URL}/player/jo": FausseReponse(429)})
    with pytest.raises(RateLimited):
        cli.profile("jo")


def test_403_mentionne_le_user_agent():
    cli, _ = client({f"{BASE_URL}/player/jo": FausseReponse(403)})
    with pytest.raises(ChessComError, match="User-Agent"):
        cli.profile("jo")


def test_code_inattendu():
    cli, _ = client({f"{BASE_URL}/player/jo": FausseReponse(500)})
    with pytest.raises(ChessComError, match="HTTP 500"):
        cli.profile("jo")


def test_json_invalide():
    cli, _ = client({f"{BASE_URL}/player/jo": FausseReponse(200, casse=True)})
    with pytest.raises(ChessComError, match="illisible"):
        cli.profile("jo")


def test_panne_reseau():
    cli = ChessComClient(session=SessionQuiExplose())
    with pytest.raises(ChessComError, match="Requête impossible"):
        cli.profile("jo")


# --------------------------------------------------------------------------
# Archives et parties
# --------------------------------------------------------------------------

ARCHIVES = [
    f"{BASE_URL}/player/jo/games/2025/11",
    f"{BASE_URL}/player/jo/games/2025/12",
    f"{BASE_URL}/player/jo/games/2026/01",
]


def routes_completes(parties_par_mois: dict[str, list[dict]]) -> dict:
    """Toutes les archives sont routées, les non précisées étant vides.

    Sans ce remplissage, les mois absents tombent sur le 404 par défaut de la
    fausse session et le test échoue pour une raison qui n'a rien à voir avec
    ce qu'il vérifie.
    """
    routes = {
        f"{BASE_URL}/player/jo/games/archives": FausseReponse(200, {"archives": ARCHIVES})
    }
    for url in ARCHIVES:
        routes[url] = FausseReponse(200, {"games": parties_par_mois.get(url, [])})
    return routes


def test_archives_rendues_dans_l_ordre():
    cli, _ = client(routes_completes({}))
    assert cli.archives("jo") == ARCHIVES


def test_month_construit_l_url():
    cli, session = client(
        {f"{BASE_URL}/player/jo/games/2026/01": FausseReponse(200, {"games": [partie_api()]})}
    )
    parties = cli.month("jo", 2026, 1)
    assert len(parties) == 1
    assert session.appels[0][0].endswith("/games/2026/01")


def test_month_mois_sur_deux_chiffres():
    cli, session = client(
        {f"{BASE_URL}/player/jo/games/2026/03": FausseReponse(200, {"games": []})}
    )
    cli.month("jo", 2026, 3)
    assert session.appels[0][0].endswith("/2026/03")


def test_parse_games_tolere_une_reponse_vide():
    cli, _ = client({f"{BASE_URL}/player/jo/games/2026/01": FausseReponse(200, {})})
    assert cli.month("jo", 2026, 1) == []


def test_recent_games_remonte_du_plus_recent():
    routes = routes_completes(
        {
            ARCHIVES[0]: [partie_api(url="vieille")],
            ARCHIVES[1]: [partie_api(url="moyenne")],
            ARCHIVES[2]: [partie_api(url="recente")],
        }
    )
    cli, _ = client(routes)
    parties = cli.recent_games("jo", limit=3)
    assert [p.url for p in parties] == ["recente", "moyenne", "vieille"]


def test_recent_games_s_arrete_des_que_la_limite_est_atteinte():
    routes = routes_completes(
        {
            ARCHIVES[0]: [partie_api(url="vieille")],
            ARCHIVES[1]: [partie_api(url="moyenne")],
            ARCHIVES[2]: [partie_api(url="a"), partie_api(url="b")],
        }
    )
    cli, session = client(routes)
    parties = cli.recent_games("jo", limit=2)

    assert len(parties) == 2
    urls_appelees = [url for url, _ in session.appels]
    assert ARCHIVES[0] not in urls_appelees, "mois inutiles téléchargés"


def test_recent_games_ordre_dans_un_mois():
    """Dans un mois, la dernière partie de la liste est la plus récente."""
    routes = routes_completes(
        {ARCHIVES[2]: [partie_api(url="ancienne"), partie_api(url="nouvelle")]}
    )
    cli, _ = client(routes)
    assert cli.recent_games("jo", limit=2)[0].url == "nouvelle"


def test_recent_games_filtre_les_variantes():
    routes = routes_completes(
        {
            ARCHIVES[2]: [
                partie_api(url="960", rules="chess960"),
                partie_api(url="classique", rules="chess"),
            ]
        }
    )
    cli, _ = client(routes)
    parties = cli.recent_games("jo", limit=10)
    assert [p.url for p in parties] == ["classique"]


def test_recent_games_sans_filtre_de_regles():
    routes = routes_completes(
        {ARCHIVES[2]: [partie_api(url="960", rules="chess960")]}
    )
    cli, _ = client(routes)
    assert len(cli.recent_games("jo", limit=10, rules=None)) == 1


def test_recent_games_filtre_la_cadence():
    routes = routes_completes(
        {
            ARCHIVES[2]: [
                partie_api(url="bullet", time_class="bullet"),
                partie_api(url="rapid", time_class="rapid"),
            ]
        }
    )
    cli, _ = client(routes)
    parties = cli.recent_games("jo", limit=10, time_classes=["RAPID"])
    assert [p.url for p in parties] == ["rapid"]


def test_recent_games_filtre_les_non_classees():
    routes = routes_completes(
        {
            ARCHIVES[2]: [
                partie_api(url="amicale", rated=False),
                partie_api(url="classee", rated=True),
            ]
        }
    )
    cli, _ = client(routes)
    parties = cli.recent_games("jo", limit=10, rated_only=True)
    assert [p.url for p in parties] == ["classee"]


def test_recent_games_ignore_les_parties_sans_pgn():
    """Une partie abandonnée avant le premier coup n'a pas de PGN."""
    routes = routes_completes(
        {ARCHIVES[2]: [partie_api(url="vide", pgn=""), partie_api(url="pleine")]}
    )
    cli, _ = client(routes)
    assert [p.url for p in cli.recent_games("jo", limit=10)] == ["pleine"]


def test_recent_games_limite_le_nombre_d_archives():
    routes = routes_completes({url: [] for url in ARCHIVES})
    cli, session = client(routes)
    cli.recent_games("jo", limit=50, max_archives=1)

    urls_appelees = [url for url, _ in session.appels]
    assert ARCHIVES[2] in urls_appelees
    assert ARCHIVES[1] not in urls_appelees


def test_recent_games_joueur_inconnu():
    cli, _ = client({})
    with pytest.raises(PlayerNotFound):
        cli.recent_games("fantome")


def test_un_mois_absent_n_interrompt_pas_le_parcours():
    """Un 404 sur une archive mensuelle n'est pas un pseudo inexistant."""
    routes = routes_completes({ARCHIVES[0]: [partie_api(url="vieille")]})
    del routes[ARCHIVES[2]]  # ce mois a disparu depuis la liste d'archives
    cli, _ = client(routes)

    parties = cli.recent_games("jo", limit=10)
    assert [p.url for p in parties] == ["vieille"]


def test_archive_absente_rend_une_liste_vide():
    cli, _ = client({})
    assert cli.archive(f"{BASE_URL}/player/jo/games/2026/01") == []


def test_month_404_reste_un_pseudo_introuvable():
    """Sur un endpoint joueur, en revanche, le 404 garde son sens."""
    cli, _ = client({})
    with pytest.raises(PlayerNotFound, match="fantome"):
        cli.month("fantome", 2026, 1)


def test_archives_404_reste_un_pseudo_introuvable():
    cli, _ = client({})
    with pytest.raises(PlayerNotFound):
        cli.archives("fantome")