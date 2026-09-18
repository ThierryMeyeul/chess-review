"""Tests de la notation figurine."""

from __future__ import annotations

import pytest

from src.ui.figurine import to_figurine


@pytest.mark.parametrize(
    "san, attendu",
    [
        ("Nf3", "♞f3"),
        ("Bxb5", "♝xb5"),
        ("Qxd8+", "♛xd8+"),
        ("Rae1", "♜ae1"),
        ("Kg2", "♚g2"),
        ("Qxf7#", "♛xf7#"),
    ],
)
def test_lettre_initiale_remplacee(san, attendu):
    assert to_figurine(san) == attendu


@pytest.mark.parametrize("san", ["e4", "exd5", "b5", "axb6", "d8"])
def test_coups_de_pion_inchanges(san):
    assert to_figurine(san) == san


@pytest.mark.parametrize("san", ["O-O", "O-O-O", "O-O+", "O-O-O#"])
def test_roque_inchange(san):
    assert to_figurine(san) == san


def test_promotion():
    assert to_figurine("a8=Q") == "a8=♛"
    assert to_figurine("bxa8=N+") == "bxa8=♞+"


def test_chaine_vide():
    assert to_figurine("") == ""


def test_colonne_b_non_confondue_avec_le_fou():
    """Les colonnes sont en minuscules : « b5 » n'est pas un coup de fou."""
    assert to_figurine("b5") == "b5"
    assert to_figurine("bxc6") == "bxc6"