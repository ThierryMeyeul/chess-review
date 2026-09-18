"""Récupération des parties depuis l'API publique de chess.com.

L'API ne demande ni clé ni authentification, mais elle a trois pièges :

1. Elle refuse le User-Agent par défaut de requests avec un 403. Il faut en
   fournir un explicite, idéalement avec un moyen de contact.
2. Les parties sont rangées par mois, et il faut d'abord demander la liste des
   archives disponibles — un joueur peut avoir des mois sans partie.
3. Tout n'est pas une partie d'échecs classique : le champ `rules` distingue
   chess960, bughouse, crazyhouse. Les analyser avec Stockfish n'aurait pas
   de sens, ils sont filtrés par défaut.

La session HTTP est injectable, ce qui permet de tester tout le module sans
réseau.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol

import chess.pgn

BASE_URL = "https://api.chess.com/pub"
USER_AGENT_DEFAUT = "chess-review/1.0 (https://github.com/)"

# Issues de partie, côté chess.com. Le gagnant porte « win » ; le perdant
# porte le motif de sa défaite, d'où cette liste.
RESULTATS_NULS = frozenset(
    {
        "agreed",
        "repetition",
        "stalemate",
        "insufficient",
        "50move",
        "timevsinsufficient",
    }
)


class ChessComError(RuntimeError):
    """Erreur générique de l'API."""


class NotFound(ChessComError):
    """Ressource absente (404). Le sens dépend de l'endpoint appelé."""


class PlayerNotFound(NotFound):
    """Le pseudo n'existe pas."""


class RateLimited(ChessComError):
    """Trop de requêtes : il faut ralentir."""


class Response(Protocol):
    """Le minimum attendu d'une réponse HTTP, pour pouvoir la simuler."""

    status_code: int

    def json(self) -> Any: ...


class Session(Protocol):
    def get(self, url: str, headers: dict, timeout: float) -> Response: ...


@dataclass(frozen=True)
class GameSummary:
    """Une partie telle que renvoyée par l'API."""

    url: str
    pgn: str
    white: str
    black: str
    white_rating: int
    black_rating: int
    white_result: str
    black_result: str
    time_class: str
    time_control: str
    rated: bool
    rules: str
    end_time: datetime | None

    # -- lecture ----------------------------------------------------------

    @classmethod
    def from_api(cls, payload: dict) -> "GameSummary":
        blanc = payload.get("white") or {}
        noir = payload.get("black") or {}
        horodatage = payload.get("end_time")
        return cls(
            url=payload.get("url", ""),
            pgn=payload.get("pgn", ""),
            white=blanc.get("username", "?"),
            black=noir.get("username", "?"),
            white_rating=int(blanc.get("rating") or 0),
            black_rating=int(noir.get("rating") or 0),
            white_result=blanc.get("result", ""),
            black_result=noir.get("result", ""),
            time_class=payload.get("time_class", ""),
            time_control=payload.get("time_control", ""),
            rated=bool(payload.get("rated", False)),
            rules=payload.get("rules", "chess"),
            end_time=(
                datetime.fromtimestamp(horodatage, tz=timezone.utc)
                if horodatage
                else None
            ),
        )

    # -- confort ----------------------------------------------------------

    @property
    def date(self) -> str:
        return self.end_time.strftime("%Y-%m-%d") if self.end_time else "?"

    def color_of(self, username: str) -> chess.Color | None:
        """Couleur jouée par un pseudo, insensible à la casse."""
        pseudo = username.lower()
        if self.white.lower() == pseudo:
            return chess.WHITE
        if self.black.lower() == pseudo:
            return chess.BLACK
        return None

    def opponent_of(self, username: str) -> str:
        couleur = self.color_of(username)
        if couleur is chess.WHITE:
            return self.black
        if couleur is chess.BLACK:
            return self.white
        return "?"

    def outcome_for(self, username: str) -> str:
        """« win », « loss », « draw » ou « ? » du point de vue d'un joueur."""
        couleur = self.color_of(username)
        if couleur is None:
            return "?"
        mien = self.white_result if couleur is chess.WHITE else self.black_result
        if mien == "win":
            return "win"
        if mien in RESULTATS_NULS:
            return "draw"
        return "loss"

    def label(self, username: str | None = None) -> str:
        """Ligne lisible pour une liste de sélection."""
        base = f"{self.date}  {self.white} ({self.white_rating}) — {self.black} ({self.black_rating})"
        if username:
            issue = {"win": "V", "loss": "D", "draw": "N", "?": "?"}[
                self.outcome_for(username)
            ]
            base = f"{self.date}  [{issue}] vs {self.opponent_of(username)}"
        return f"{base}  · {self.time_class}"

    def game(self) -> chess.pgn.Game | None:
        """Parse le PGN. Rend None si le PGN est absent ou illisible."""
        if not self.pgn:
            return None
        return chess.pgn.read_game(io.StringIO(self.pgn))


class ChessComClient:
    """Client minimal de l'API publique.

    Volontairement séquentiel : paralléliser les requêtes sur cette API mène
    vite à un 429, et récupérer trois mois d'archives prend de toute façon
    moins de temps que d'analyser une seule partie.
    """

    def __init__(
        self,
        session: Session | None = None,
        user_agent: str = USER_AGENT_DEFAUT,
        timeout: float = 20.0,
        base_url: str = BASE_URL,
    ) -> None:
        if session is None:
            import requests  # importé tardivement : les tests n'en ont pas besoin

            session = requests.Session()
        self._session = session
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._timeout = timeout
        self._base = base_url.rstrip("/")

    # -- couche transport -------------------------------------------------

    def _get(self, chemin_ou_url: str) -> Any:
        url = (
            chemin_ou_url
            if chemin_ou_url.startswith("http")
            else f"{self._base}/{chemin_ou_url.lstrip('/')}"
        )
        try:
            reponse = self._session.get(url, headers=self._headers, timeout=self._timeout)
        except Exception as exc:  # panne réseau, DNS, TLS…
            raise ChessComError(f"Requête impossible : {exc}") from exc

        code = getattr(reponse, "status_code", 0)
        if code == 404:
            # Volontairement générique : sur /player/<pseudo> un 404 signifie
            # que le joueur n'existe pas, mais sur une archive mensuelle il
            # signifie seulement que ce mois a disparu. Les appelants
            # traduisent.
            raise NotFound(f"Ressource introuvable : {url}")
        if code == 429:
            raise RateLimited("Trop de requêtes vers chess.com. Réessaie dans un instant.")
        if code == 403:
            raise ChessComError(
                "Accès refusé (403). L'API exige un User-Agent explicite."
            )
        if code != 200:
            raise ChessComError(f"Réponse inattendue de chess.com : HTTP {code}.")

        try:
            return reponse.json()
        except Exception as exc:
            raise ChessComError("Réponse illisible (JSON invalide).") from exc

    # -- points d'entrée --------------------------------------------------

    @staticmethod
    def _joueur_absent(username: str) -> PlayerNotFound:
        return PlayerNotFound(f"Pseudo introuvable sur chess.com : {username}")

    def profile(self, username: str) -> dict:
        try:
            return self._get(f"player/{username.strip().lower()}")
        except NotFound:
            raise self._joueur_absent(username) from None

    def archives(self, username: str) -> list[str]:
        """URLs mensuelles, de la plus ancienne à la plus récente."""
        try:
            donnees = self._get(f"player/{username.strip().lower()}/games/archives")
        except NotFound:
            raise self._joueur_absent(username) from None
        return list(donnees.get("archives", []))

    def month(self, username: str, year: int, month: int) -> list[GameSummary]:
        try:
            donnees = self._get(
                f"player/{username.strip().lower()}/games/{year:04d}/{month:02d}"
            )
        except NotFound:
            raise self._joueur_absent(username) from None
        return self._parse_games(donnees)

    def archive(self, url: str) -> list[GameSummary]:
        """Parties d'un mois. Un mois disparu rend une liste vide.

        Le pseudo a déjà été validé par archives() au moment où on arrive ici :
        faire échouer tout le parcours parce qu'un mois sur douze a bougé
        serait disproportionné.
        """
        try:
            return self._parse_games(self._get(url))
        except NotFound:
            return []

    @staticmethod
    def _parse_games(donnees: Any) -> list[GameSummary]:
        parties = (donnees or {}).get("games") or []
        return [GameSummary.from_api(p) for p in parties if isinstance(p, dict)]

    def recent_games(
        self,
        username: str,
        limit: int = 20,
        rules: str | None = "chess",
        time_classes: Iterable[str] | None = None,
        rated_only: bool = False,
        max_archives: int = 6,
    ) -> list[GameSummary]:
        """Les `limit` parties les plus récentes, de la plus récente d'abord.

        On remonte les archives mois par mois en partant de la fin et on
        s'arrête dès qu'on a assez de parties : inutile de télécharger deux ans
        d'historique pour en afficher vingt.
        """
        classes = {c.lower() for c in time_classes} if time_classes else None
        liste = self.archives(username)

        recoltees: list[GameSummary] = []
        for url in reversed(liste[-max_archives:] if max_archives else liste):
            for partie in reversed(self.archive(url)):
                if rules is not None and partie.rules != rules:
                    continue
                if classes is not None and partie.time_class.lower() not in classes:
                    continue
                if rated_only and not partie.rated:
                    continue
                if not partie.pgn:
                    continue  # parties abandonnées avant le premier coup
                recoltees.append(partie)
                if len(recoltees) >= limit:
                    return recoltees
        return recoltees