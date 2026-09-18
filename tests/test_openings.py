"""Tests du module core.openings.

Aucun de ces tests ne nécessite le téléchargement de la base Lichess : ils
construisent une mini-base de quatre lignes dans un dossier temporaire. Deux
tests supplémentaires s'activent d'eux-mêmes si les vrais fichiers sont
présents dans data/openings/.
"""

from __future__ import annotations

from pathlib import Path

import chess
import pytest

from src.core.openings import (
    NullOpeningBook,
    Opening,
    OpeningBook,
    OpeningDataError,
    load_default,
    parse_moves,
)

MINI_TSV = "\n".join(
    [
        "eco\tname\tpgn",
        "B00\tKing's Pawn Game\t1. e4",
        "C20\tKing's Pawn Game: King's Knight\t1. e4 e5 2. Nf3",
        "C44\tKing's Knight Opening: Normal\t1. e4 e5 2. Nf3 Nc6",
        "A00\tVan't Kruijs Opening\t1. e3",
    ]
)


@pytest.fixture
def dossier_tsv(tmp_path: Path) -> Path:
    (tmp_path / "mini.tsv").write_text(MINI_TSV, encoding="utf-8")
    return tmp_path


@pytest.fixture
def book(dossier_tsv: Path) -> OpeningBook:
    return OpeningBook.from_directory(dossier_tsv)


def position(*sans: str) -> chess.Board:
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board


# --------------------------------------------------------------------------
# Lecture des lignes
# --------------------------------------------------------------------------


def test_parse_moves_retire_les_numeros():
    assert parse_moves("1. e4 e5 2. Nf3 Nc6") == ["e4", "e5", "Nf3", "Nc6"]


def test_parse_moves_retire_les_resultats():
    assert parse_moves("1. e4 e5 *") == ["e4", "e5"]


def test_parse_moves_accepte_les_points_multiples():
    assert parse_moves("1... e5 2. Nf3") == ["e5", "Nf3"]


def test_parse_moves_chaine_vide():
    assert parse_moves("") == []


def test_en_tete_ignoree(book: OpeningBook):
    assert len(book) > 0
    assert all(o.eco.lower() != "eco" for o in book._entries.values())


def test_ligne_corrompue_n_invalide_pas_la_base():
    book = OpeningBook.from_rows(
        [
            ("B00", "Valide", "1. e4"),
            ("X99", "Corrompue", "1. e4 Zz9 2. Qxq"),
            ("A00", "Valide aussi", "1. e3"),
        ]
    )
    assert book.lookup(position("e4")) is not None
    assert book.lookup(position("e3")) is not None


def test_ligne_trop_courte_est_ignoree():
    book = OpeningBook.from_rows([("B00",), ("B00", "Sans pgn")])
    assert len(book) == 0


# --------------------------------------------------------------------------
# Consultation
# --------------------------------------------------------------------------


def test_lookup_position_connue(book: OpeningBook):
    trouvee = book.lookup(position("e4"))
    assert trouvee is not None
    assert trouvee.eco == "B00"
    assert trouvee.ply == 1


def test_lookup_position_inconnue(book: OpeningBook):
    assert book.lookup(position("h4", "h5", "Rh3")) is None


def test_lookup_position_initiale(book: OpeningBook):
    """La position de départ n'est l'ouverture de personne."""
    assert book.lookup(chess.Board()) is None


def test_contains(book: OpeningBook):
    assert position("e4") in book
    assert position("a4") not in book


def test_le_nom_le_plus_court_gagne(book: OpeningBook):
    """Trois lignes passent par la position après 1.e4 : la plus courte prime."""
    assert book.lookup(position("e4")).name == "King's Pawn Game"


def test_transposition_reconnue(book: OpeningBook):
    """L'index porte sur des positions, donc l'ordre des coups est indifférent."""
    directe = position("e4", "e5", "Nf3", "Nc6")
    transposee = position("Nf3", "e5", "e4", "Nc6")
    assert directe.epd() == transposee.epd()
    assert book.lookup(transposee) is not None
    assert book.lookup(transposee).eco == "C44"


# --------------------------------------------------------------------------
# Parcours d'une partie
# --------------------------------------------------------------------------


def coups(*sans: str) -> list[chess.Move]:
    board = chess.Board()
    out = []
    for san in sans:
        move = board.parse_san(san)
        out.append(move)
        board.push(move)
    return out


def test_walk_partie_entierement_theorique(book: OpeningBook):
    plies, ouverture = book.walk(coups("e4", "e5", "Nf3", "Nc6"))
    assert plies == 4
    assert ouverture.eco == "C44"


def test_walk_s_arrete_a_la_sortie_de_livre(book: OpeningBook):
    plies, ouverture = book.walk(coups("e4", "e5", "Nf3", "a6"))
    assert plies == 3
    assert ouverture.eco == "C20"


def test_walk_sortie_immediate(book: OpeningBook):
    plies, ouverture = book.walk(coups("h4"))
    assert plies == 0
    assert ouverture is None


def test_walk_sans_coups(book: OpeningBook):
    assert book.walk([]) == (0, None)


def test_walk_ne_revient_pas_dans_le_livre(book: OpeningBook):
    """Une position théorique atteinte après une sortie ne recompte pas."""
    plies, _ = book.walk(coups("h4", "h5", "e4"))
    assert plies == 0


# --------------------------------------------------------------------------
# Absence de base
# --------------------------------------------------------------------------


def test_null_book_ne_trouve_rien():
    book = NullOpeningBook()
    assert book.lookup(position("e4")) is None
    assert book.walk(coups("e4", "e5")) == (0, None)


def test_from_directory_dossier_vide(tmp_path: Path):
    with pytest.raises(OpeningDataError):
        OpeningBook.from_directory(tmp_path)


def test_from_tsv_fichier_absent(tmp_path: Path):
    with pytest.raises(OpeningDataError):
        OpeningBook.from_tsv(tmp_path / "absent.tsv")


def test_load_default_retombe_sur_une_base_vide(tmp_path: Path):
    book = load_default(tmp_path / "nexiste_pas")
    assert isinstance(book, NullOpeningBook)


def test_load_default_charge_la_base(dossier_tsv: Path):
    book = load_default(dossier_tsv)
    assert not isinstance(book, NullOpeningBook)
    assert len(book) > 0


# --------------------------------------------------------------------------
# Base réelle, si elle a été téléchargée
# --------------------------------------------------------------------------

VRAIE_BASE = Path("data/openings")
besoin_base = pytest.mark.skipif(
    not list(VRAIE_BASE.glob("*.tsv")),
    reason="base Lichess absente — lance scripts/fetch_openings.py",
)


@besoin_base
def test_base_reelle_est_volumineuse():
    book = OpeningBook.from_directory(VRAIE_BASE)
    assert len(book) > 5_000


@besoin_base
def test_base_reelle_reconnait_l_espagnole():
    book = OpeningBook.from_directory(VRAIE_BASE)
    plies, ouverture = book.walk(coups("e4", "e5", "Nf3", "Nc6", "Bb5"))
    assert plies == 5
    assert ouverture is not None
    assert "Ruy Lopez" in ouverture.name or "Spanish" in ouverture.name