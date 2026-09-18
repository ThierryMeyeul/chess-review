"""Thèmes de couleurs de l'échiquier.

Seules les cases sont thémées. Le jeu de pièces, lui, est celui de
python-chess (Cburnett, sous licence libre) : il est encodé en dur dans la
bibliothèque et n'est pas paramétrable. Voir la note dans board_widget.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoardTheme:
    key: str
    name: str
    light: str
    dark: str
    light_lastmove: str
    dark_lastmove: str
    margin: str
    coord: str

    def colors(self) -> dict[str, str]:
        """Format attendu par chess.svg.board(colors=...)."""
        return {
            "square light": self.light,
            "square dark": self.dark,
            "square light lastmove": self.light_lastmove,
            "square dark lastmove": self.dark_lastmove,
            "margin": self.margin,
            "coord": self.coord,
            "inner border": self.margin,
            "outer border": self.margin,
        }


THEMES: tuple[BoardTheme, ...] = (
    BoardTheme(
        key="green",
        name="Vert (chess.com)",
        light="#EBECD0",
        dark="#739552",
        light_lastmove="#F5F682",
        dark_lastmove="#B9CA43",
        margin="#302E2B",
        coord="#EBECD0",
    ),
    BoardTheme(
        key="brown",
        name="Bois (lichess)",
        light="#F0D9B5",
        dark="#B58863",
        light_lastmove="#CDD26A",
        dark_lastmove="#AAA23A",
        margin="#2F2B26",
        coord="#F0D9B5",
    ),
    BoardTheme(
        key="blue",
        name="Bleu",
        light="#DEE3E6",
        dark="#8CA2AD",
        light_lastmove="#CDD26A",
        dark_lastmove="#AAA23A",
        margin="#2A3138",
        coord="#DEE3E6",
    ),
    BoardTheme(
        key="slate",
        name="Ardoise",
        light="#C9CBCF",
        dark="#5D6773",
        light_lastmove="#D6D98C",
        dark_lastmove="#9AA34F",
        margin="#23262B",
        coord="#C9CBCF",
    ),
)

DEFAULT_THEME_KEY = "green"


def get_theme(key: str) -> BoardTheme:
    """Rend un thème par sa clé, ou le thème par défaut si la clé est inconnue."""
    for theme in THEMES:
        if theme.key == key:
            return theme
    return THEMES[0]