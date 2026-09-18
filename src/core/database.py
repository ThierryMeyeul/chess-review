"""Persistance des parties et de leurs analyses.

SQLAlchemy plutôt que du SQL brut, pour une raison pratique : la même couche
tourne sur MySQL en production et sur SQLite en mémoire pendant les tests. Sans
ça, tester la persistance supposerait un serveur MySQL allumé, et la suite
cesserait d'être lançable partout.

Ce qui est stocké est volontairement le strict nécessaire pour réafficher une
analyse sans relancer Stockfish : évaluation avant et après chaque coup, coup
recommandé, badge et précision. Les variantes complètes ne sont pas conservées
— elles pèsent lourd et se recalculent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence
from urllib.parse import quote_plus

import chess
import chess.engine
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship

from src.core.classify import ClassifiedMove, GameReport, MoveClass, PlayerReport
from src.core.engine import Line, MoveAnalysis, PositionAnalysis

# Sentinelle : une PositionAnalysis reconstruite reçoit deux variantes fictives
# pour ne pas être prise pour une position à coup unique. `is_forced` n'a aucun
# sens sur une analyse relue depuis la base.
_LIGNE_FANTOME = "—"


class DatabaseError(RuntimeError):
    """Erreur de connexion ou de requête, présentable à l'utilisateur."""


# --------------------------------------------------------------------------
# Configuration de connexion
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class DatabaseConfig:
    """Paramètres de connexion, indépendants du SGBD."""

    host: str = "localhost"
    port: int = 3306
    database: str = "chess_review"
    user: str = ""
    password: str = ""
    driver: str = "mysql+pymysql"

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Lit .env. Les identifiants n'ont rien à faire dans le code."""
        return cls(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "3306")),
            database=os.environ.get("DB_NAME", "chess_review"),
            user=os.environ.get("DB_USER", ""),
            password=os.environ.get("DB_PASSWORD", ""),
        )

    @property
    def url(self) -> str:
        # quote_plus sur le mot de passe : un « @ » ou un « / » casserait l'URL.
        identifiants = self.user
        if self.password:
            identifiants += f":{quote_plus(self.password)}"
        return (
            f"{self.driver}://{identifiants}@{self.host}:{self.port}/{self.database}"
            "?charset=utf8mb4"
        )

    @property
    def url_masquee(self) -> str:
        """Même URL, mot de passe remplacé — pour l'affichage et les logs."""
        identifiants = self.user + (":••••••" if self.password else "")
        return f"{self.driver}://{identifiants}@{self.host}:{self.port}/{self.database}"

    @property
    def configured(self) -> bool:
        return bool(self.user and self.database)


# --------------------------------------------------------------------------
# Modèles
# --------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32), default="pgn")
    source_url: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    pgn: Mapped[str] = mapped_column(Text)

    white: Mapped[str] = mapped_column(String(64), default="?")
    black: Mapped[str] = mapped_column(String(64), default="?")
    white_rating: Mapped[int] = mapped_column(Integer, default=0)
    black_rating: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str] = mapped_column(String(16), default="*")
    time_class: Mapped[str] = mapped_column(String(16), default="")
    eco: Mapped[str] = mapped_column(String(8), default="")
    opening: Mapped[str] = mapped_column(String(160), default="")

    played_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="game", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def label(self) -> str:
        date = self.played_at.strftime("%Y-%m-%d") if self.played_at else "—"
        return f"{date}  {self.white} — {self.black}"

    @property
    def analysed(self) -> bool:
        return bool(self.analyses)


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), index=True
    )

    engine: Mapped[str] = mapped_column(String(64), default="Stockfish")
    depth: Mapped[int] = mapped_column(Integer, default=0)
    book_plies: Mapped[int] = mapped_column(Integer, default=0)
    white_accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    black_accuracy: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    game: Mapped[Game] = relationship(back_populates="analyses")
    moves: Mapped[list["AnalysedMove"]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
        order_by="AnalysedMove.ply",
        lazy="selectin",
    )


class AnalysedMove(Base):
    __tablename__ = "analysed_moves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )

    ply: Mapped[int] = mapped_column(Integer)
    move_number: Mapped[int] = mapped_column(Integer)
    white_to_move: Mapped[bool] = mapped_column(Boolean)
    san: Mapped[str] = mapped_column(String(16))
    uci: Mapped[str] = mapped_column(String(8))
    fen_before: Mapped[str] = mapped_column(String(120))

    cp_before: Mapped[int] = mapped_column(Integer, default=0)
    cp_after: Mapped[int] = mapped_column(Integer, default=0)
    mate_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    best_uci: Mapped[str] = mapped_column(String(8), default="")
    best_san: Mapped[str] = mapped_column(String(16), default="")

    classification: Mapped[str] = mapped_column(String(24))
    accuracy: Mapped[float] = mapped_column(Float, default=0.0)

    analysis: Mapped[Analysis] = relationship(back_populates="moves")


# --------------------------------------------------------------------------
# Conversions
# --------------------------------------------------------------------------


def _position(fen: str, cp_white: int, mate: int | None, best: chess.Move | None,
              best_san: str) -> PositionAnalysis:
    """Recompose une PositionAnalysis minimale à partir des colonnes stockées."""
    board = chess.Board(fen)
    score = chess.engine.Mate(mate) if mate is not None else chess.engine.Cp(cp_white)
    coup = best if best is not None else next(iter(board.legal_moves), None)

    lignes: list[Line] = []
    if coup is not None:
        lignes.append(
            Line(move=coup, san=best_san or board.san(coup), score_white=score, pv=[coup])
        )
        # Deuxième ligne fictive : sans elle la position passerait pour forcée.
        lignes.append(Line(move=coup, san=_LIGNE_FANTOME, score_white=score, pv=[coup]))
    return PositionAnalysis(fen=fen, turn=board.turn, lines=lignes, depth=0)


def stored_to_report(analysis: Analysis) -> GameReport:
    """Reconstruit un GameReport affichable depuis la base.

    Suffisant pour tout ce que montre l'interface : badge, précision,
    évaluation, coup recommandé. Les variantes profondes ne sont pas restaurées
    puisqu'elles ne sont pas stockées.
    """
    coups: list[ClassifiedMove] = []
    for enregistre in analysis.moves:
        board = chess.Board(enregistre.fen_before)
        move = chess.Move.from_uci(enregistre.uci)
        meilleur = (
            chess.Move.from_uci(enregistre.best_uci) if enregistre.best_uci else None
        )

        avant = _position(
            enregistre.fen_before, enregistre.cp_before, None, meilleur, enregistre.best_san
        )
        apres_board = board.copy()
        apres_board.push(move)
        apres = _position(
            apres_board.fen(), enregistre.cp_after, enregistre.mate_after, None, ""
        )

        coups.append(
            ClassifiedMove(
                analysis=MoveAnalysis(
                    ply=enregistre.ply,
                    move_number=enregistre.move_number,
                    turn=chess.WHITE if enregistre.white_to_move else chess.BLACK,
                    move=move,
                    san=enregistre.san,
                    fen_before=enregistre.fen_before,
                    before=avant,
                    after=apres,
                ),
                classification=MoveClass(enregistre.classification),
                accuracy=enregistre.accuracy,
            )
        )

    def rapport(couleur: chess.Color, precision: float) -> PlayerReport:
        compte: dict[MoveClass, int] = {}
        for coup in coups:
            if coup.turn == couleur:
                compte[coup.classification] = compte.get(coup.classification, 0) + 1
        return PlayerReport(color=couleur, accuracy=precision, counts=compte)

    return GameReport(
        moves=coups,
        white=rapport(chess.WHITE, analysis.white_accuracy),
        black=rapport(chess.BLACK, analysis.black_accuracy),
    )


# --------------------------------------------------------------------------
# Dépôt
# --------------------------------------------------------------------------


class GameRepository:
    """Point d'entrée unique vers la base.

    Accepte soit une URL, soit un Engine déjà construit — c'est cette seconde
    forme que les tests utilisent avec SQLite en mémoire.
    """

    def __init__(self, url_or_engine: str | Engine, echo: bool = False) -> None:
        try:
            if isinstance(url_or_engine, Engine):
                self.engine = url_or_engine
            else:
                self.engine = create_engine(
                    url_or_engine,
                    echo=echo,
                    pool_pre_ping=True,  # une connexion MySQL expirée est ré-ouverte
                    pool_recycle=1800,
                )
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Connexion impossible : {exc}") from exc

    # -- schéma -----------------------------------------------------------

    def create_all(self) -> None:
        try:
            Base.metadata.create_all(self.engine)
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Création du schéma impossible : {exc}") from exc

    def ping(self) -> bool:
        """Teste la connexion. Utilisé par le bouton « Tester » des réglages."""
        from sqlalchemy import text

        try:
            with self.engine.connect() as connexion:
                connexion.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError as exc:
            raise DatabaseError(str(exc)) from exc

    def dispose(self) -> None:
        self.engine.dispose()

    # -- écriture ---------------------------------------------------------

    def save_game(
        self,
        pgn: str,
        *,
        source: str = "pgn",
        source_url: str | None = None,
        white: str = "?",
        black: str = "?",
        white_rating: int = 0,
        black_rating: int = 0,
        result: str = "*",
        time_class: str = "",
        eco: str = "",
        opening: str = "",
        played_at: datetime | None = None,
    ) -> int:
        """Enregistre une partie, ou met à jour celle qui a la même URL.

        L'URL chess.com sert de clé naturelle : réimporter la même partie ne
        doit pas créer de doublon.
        """
        try:
            with Session(self.engine) as session, session.begin():
                partie = None
                if source_url:
                    partie = session.scalar(
                        select(Game).where(Game.source_url == source_url)
                    )
                if partie is None:
                    partie = Game(source_url=source_url)
                    session.add(partie)

                partie.source = source
                partie.pgn = pgn
                partie.white = white[:64]
                partie.black = black[:64]
                partie.white_rating = white_rating
                partie.black_rating = black_rating
                partie.result = result[:16]
                partie.time_class = time_class[:16]
                partie.eco = eco[:8]
                partie.opening = opening[:160]
                partie.played_at = played_at
                session.flush()
                return partie.id
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Enregistrement impossible : {exc}") from exc

    def save_analysis(
        self,
        game_id: int,
        report: GameReport,
        *,
        depth: int = 0,
        engine_name: str = "Stockfish",
        book_plies: int = 0,
        replace: bool = True,
    ) -> int:
        """Enregistre un rapport. Par défaut, remplace l'analyse précédente.

        Garder l'historique des analyses d'une même partie n'a guère d'intérêt :
        seule la plus profonde compte.
        """
        try:
            with Session(self.engine) as session, session.begin():
                if replace:
                    session.execute(
                        delete(Analysis).where(Analysis.game_id == game_id)
                    )

                analyse = Analysis(
                    game_id=game_id,
                    engine=engine_name[:64],
                    depth=depth,
                    book_plies=book_plies,
                    white_accuracy=report.white.accuracy,
                    black_accuracy=report.black.accuracy,
                )
                session.add(analyse)
                session.flush()

                for coup in report.moves:
                    donnees = coup.analysis
                    meilleure = donnees.before.best
                    session.add(
                        AnalysedMove(
                            analysis_id=analyse.id,
                            ply=donnees.ply,
                            move_number=donnees.move_number,
                            white_to_move=donnees.turn == chess.WHITE,
                            san=donnees.san[:16],
                            uci=donnees.move.uci(),
                            fen_before=donnees.fen_before[:120],
                            cp_before=donnees.before.cp_white,
                            cp_after=donnees.after.cp_white,
                            mate_after=donnees.after.mate_white,
                            best_uci=meilleure.move.uci() if meilleure else "",
                            best_san=(meilleure.san if meilleure else "")[:16],
                            classification=coup.classification.value,
                            accuracy=coup.accuracy,
                        )
                    )
                return analyse.id
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Enregistrement de l'analyse impossible : {exc}") from exc

    def delete_game(self, game_id: int) -> None:
        """Supprime une partie et, par cascade, ses analyses.

        On charge l'objet au lieu d'émettre un DELETE en masse : celui-ci
        court-circuite la cascade de l'ORM, et tous les SGBD n'appliquent pas
        les clés étrangères de la même façon — SQLite les ignore par défaut.
        Les analyses resteraient orphelines.
        """
        try:
            with Session(self.engine) as session, session.begin():
                partie = session.get(Game, game_id)
                if partie is not None:
                    session.delete(partie)
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Suppression impossible : {exc}") from exc

    # -- lecture ----------------------------------------------------------

    def list_games(self, limit: int = 100, search: str = "") -> list[Game]:
        """Parties les plus récentes d'abord, filtrables par joueur ou ouverture."""
        try:
            with Session(self.engine) as session:
                # nullslast() émet « NULLS LAST », que MySQL et MariaDB
                # rejettent — c'est de la syntaxe PostgreSQL. On trie d'abord
                # sur « la date est-elle nulle », ce qui est portable partout.
                requete = select(Game).order_by(
                    Game.played_at.is_(None).asc(),
                    Game.played_at.desc(),
                    Game.created_at.desc(),
                )
                if search:
                    motif = f"%{search}%"
                    requete = requete.where(
                        Game.white.like(motif)
                        | Game.black.like(motif)
                        | Game.opening.like(motif)
                    )
                parties = list(session.scalars(requete.limit(limit)))
                for partie in parties:
                    session.expunge(partie)
                return parties
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Lecture impossible : {exc}") from exc

    def get_game(self, game_id: int) -> Game | None:
        try:
            with Session(self.engine) as session:
                partie = session.get(Game, game_id)
                if partie is not None:
                    session.expunge(partie)
                return partie
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Lecture impossible : {exc}") from exc

    def latest_report(self, game_id: int) -> GameReport | None:
        """Dernière analyse d'une partie, prête à afficher."""
        try:
            with Session(self.engine) as session:
                analyse = session.scalar(
                    select(Analysis)
                    .where(Analysis.game_id == game_id)
                    .order_by(Analysis.created_at.desc(), Analysis.id.desc())
                    .limit(1)
                )
                if analyse is None:
                    return None
                return stored_to_report(analyse)
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Lecture de l'analyse impossible : {exc}") from exc

    def analysis_meta(self, game_id: int) -> dict | None:
        """Profondeur et date de la dernière analyse, sans charger les coups."""
        try:
            with Session(self.engine) as session:
                analyse = session.scalar(
                    select(Analysis)
                    .where(Analysis.game_id == game_id)
                    .order_by(Analysis.created_at.desc(), Analysis.id.desc())
                    .limit(1)
                )
                if analyse is None:
                    return None
                return {
                    "depth": analyse.depth,
                    "engine": analyse.engine,
                    "book_plies": analyse.book_plies,
                    "white_accuracy": analyse.white_accuracy,
                    "black_accuracy": analyse.black_accuracy,
                    "created_at": analyse.created_at,
                }
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Lecture impossible : {exc}") from exc

    def stats(self) -> dict:
        """Compteurs pour l'écran d'accueil."""
        from sqlalchemy import func

        try:
            with Session(self.engine) as session:
                parties = session.scalar(select(func.count(Game.id))) or 0
                analyses = session.scalar(select(func.count(Analysis.id))) or 0
                return {"games": parties, "analyses": analyses}
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Lecture impossible : {exc}") from exc