"""Détection de la théorie d'ouverture.

Stockfish ignore ce qu'est un coup théorique : pour lui, 1.e4 est un coup comme
un autre. La notion de « livre » vient d'une base extérieure — ici celle de
Lichess, cinq fichiers TSV totalisant quelques milliers de lignes.

Le principe : on rejoue chaque ligne de la base pour en extraire les positions,
et une position connue de la base est par définition théorique. On indexe donc
des positions et non des séquences de coups, ce qui gère gratuitement les
transpositions — 1.d4 Cf6 2.c4 e6 3.Cc3 et 1.c4 e6 2.Cc3 Cf6 3.d4 aboutissent
au même EPD et sont reconnues toutes les deux.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import chess

from src.core.paths import openings_dir

# URL des fichiers sources, pour le script de téléchargement.
LICHESS_TSV_URL = (
    "https://raw.githubusercontent.com/lichess-org/chess-openings/master/{name}.tsv"
)
TSV_NAMES = ("a", "b", "c", "d", "e")

_TOKEN_NUMERO = re.compile(r"^\d+\.+$")


class OpeningDataError(RuntimeError):
    """La base d'ouvertures est absente ou illisible."""


@dataclass(frozen=True)
class Opening:
    """Une entrée de la base."""

    eco: str
    name: str
    ply: int  # profondeur en demi-coups de la ligne qui mène ici

    def __str__(self) -> str:
        return f"{self.eco} {self.name}"


def parse_moves(pgn_moves: str) -> list[str]:
    """Extrait les coups SAN d'une ligne du type « 1. e4 e5 2. Nf3 ».

    On jette les numéros de coup et les résultats ; la base Lichess ne contient
    ni commentaire ni variante, donc pas besoin d'un vrai parseur PGN.
    """
    coups = []
    for token in pgn_moves.split():
        if _TOKEN_NUMERO.match(token):
            continue
        if token in ("*", "1-0", "0-1", "1/2-1/2"):
            continue
        coups.append(token)
    return coups


class OpeningBook:
    """Index position -> ouverture.

    Une instance se construit une fois au démarrage et se consulte ensuite en
    temps constant.
    """

    def __init__(self, entries: dict[str, Opening] | None = None) -> None:
        self._entries: dict[str, Opening] = dict(entries or {})

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, board: chess.Board) -> bool:
        return board.epd() in self._entries

    # -- construction -----------------------------------------------------

    def add_line(self, eco: str, name: str, pgn_moves: str) -> None:
        """Rejoue une ligne et indexe chacune de ses positions.

        Une position déjà connue par une ligne plus courte n'est pas écrasée :
        on préfère « Défense sicilienne » à un sous-nom très spécifique quand
        les deux passent par la même position.
        """
        board = chess.Board()
        for ply, san in enumerate(parse_moves(pgn_moves), start=1):
            try:
                board.push_san(san)
            except (ValueError, AssertionError):
                return  # ligne corrompue : on abandonne celle-ci, pas la base
            cle = board.epd()
            connue = self._entries.get(cle)
            if connue is None or ply < connue.ply:
                self._entries[cle] = Opening(eco=eco, name=name, ply=ply)

    @classmethod
    def from_rows(cls, rows: Iterable[Sequence[str]]) -> "OpeningBook":
        """Construit depuis des lignes (eco, name, pgn) déjà découpées."""
        book = cls()
        for row in rows:
            if len(row) < 3:
                continue
            eco, name, pgn_moves = row[0].strip(), row[1].strip(), row[2].strip()
            if not eco or eco.lower() == "eco":  # ligne d'en-tête
                continue
            book.add_line(eco, name, pgn_moves)
        return book

    @classmethod
    def from_tsv(cls, *paths: str | Path) -> "OpeningBook":
        rows: list[Sequence[str]] = []
        for path in paths:
            chemin = Path(path)
            if not chemin.is_file():
                raise OpeningDataError(f"Fichier d'ouvertures introuvable : {chemin}")
            with chemin.open(encoding="utf-8", newline="") as f:
                rows.extend(csv.reader(f, delimiter="\t"))
        return cls.from_rows(rows)

    @classmethod
    def from_directory(cls, directory: str | Path) -> "OpeningBook":
        """Charge tous les .tsv d'un dossier (typiquement data/openings/)."""
        dossier = Path(directory)
        fichiers = sorted(dossier.glob("*.tsv"))
        if not fichiers:
            raise OpeningDataError(
                f"Aucun .tsv dans {dossier}. Lance scripts/fetch_openings.py."
            )
        return cls.from_tsv(*fichiers)

    # -- consultation -----------------------------------------------------

    def lookup(self, board: chess.Board) -> Opening | None:
        """L'ouverture correspondant à une position, si elle est connue."""
        return self._entries.get(board.epd())

    def walk(
        self,
        moves: Sequence[chess.Move],
        board: chess.Board | None = None,
    ) -> tuple[int, Opening | None]:
        """Suit une partie tant qu'elle reste dans la théorie.

        Rend le nombre de demi-coups théoriques et l'ouverture la plus profonde
        atteinte. On s'arrête à la première sortie de livre : un retour fortuit
        dans une position théorique plus tard dans la partie ne compte pas.
        """
        plateau = board.copy() if board is not None else chess.Board()
        book_plies = 0
        derniere: Opening | None = None

        for move in moves:
            if move not in plateau.legal_moves:
                break
            plateau.push(move)
            trouvee = self.lookup(plateau)
            if trouvee is None:
                break
            book_plies += 1
            derniere = trouvee

        return book_plies, derniere


class NullOpeningBook(OpeningBook):
    """Base vide : tout est hors théorie.

    Permet de faire tourner l'application sans les fichiers TSV, au prix du
    badge « Théorique ».
    """

    def __init__(self) -> None:
        super().__init__({})

    def lookup(self, board: chess.Board) -> Opening | None:
        return None


def load_default(directory: str | Path | None = None) -> OpeningBook:
    """Charge la base, ou une base vide si les fichiers manquent.

    Sans argument, l'emplacement vient de core.paths et ne dépend donc pas du
    répertoire depuis lequel l'application a été lancée.
    """
    try:
        return OpeningBook.from_directory(directory or openings_dir())
    except OpeningDataError:
        return NullOpeningBook()