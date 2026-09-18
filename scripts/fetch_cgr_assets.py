#!/usr/bin/env python3
"""Récupère les icônes de badges et les jeux de pièces de chess-game-review.

    python scripts/fetch_cgr_assets.py             # icônes + pièces
    python scripts/fetch_cgr_assets.py --badges    # icônes seules
    python scripts/fetch_cgr_assets.py --pieces    # pièces seules
    python scripts/fetch_cgr_assets.py --openings  # base d'ouvertures seule

Le dépôt source (vietan0/chess-game-review, MIT) stocke ses icônes comme des
composants React : du JSX, pas des fichiers SVG. Ce script en extrait le SVG et
le convertit en fichier autonome — c'est l'essentiel de son travail.

Les jeux de pièces s'appellent « classic », « neo » et « ocean », qui sont les
noms des jeux de chess.com. Leur origine est donc douteuse malgré la licence du
dépôt : à toi de juger si ton usage le permet. Les jeux libres restent
disponibles via scripts/fetch_pieces.py.
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ui.pieces import pieces_dir
from src.core.paths import PROJECT_ROOT, openings_dir

ARCHIVE = "https://codeload.github.com/vietan0/chess-game-review/zip/refs/heads/main"
RACINE = "chess-game-review-main/"

# Leur nom d'icône -> la valeur de notre MoveClass.
BADGES = {
    "Brilliant": "brillant",
    "Great": "trouvaille",
    "Best": "meilleur",
    "Excellent": "excellent",
    "Good": "bon",
    "Book": "theorique",
    "Inaccuracy": "imprecision",
    "Mistake": "erreur",
    "Miss": "occasion_manquee",
    "Blunder": "gaffe",
    "Forced": "force",
}

# Leur nom de fichier -> le nôtre, convention Lichess.
PIECES = {
    "wp": "wP", "wn": "wN", "wb": "wB", "wr": "wR", "wq": "wQ", "wk": "wK",
    "bp": "bP", "bn": "bN", "bb": "bB", "br": "bR", "bq": "bQ", "bk": "bK",
}

JEUX = ("neo", "classic", "ocean")

# Attributs JSX en camelCase à ramener en kebab-case pour du SVG autonome.
CAMEL = (
    "fillRule", "clipRule", "strokeWidth", "strokeLinecap", "strokeLinejoin",
    "strokeMiterlimit", "strokeDasharray", "stopColor", "stopOpacity",
    "fillOpacity", "strokeOpacity", "clipPath", "textAnchor", "fontSize",
    "fontFamily", "fontWeight",
)


def badges_dir() -> Path:
    return PROJECT_ROOT / "assets" / "badges"


def _style_jsx(correspondance: re.Match) -> str:
    """Convertit un objet de style JSX en attribut style CSS."""
    declarations = []
    for morceau in correspondance.group(1).split(","):
        if ":" not in morceau:
            continue
        cle, valeur = morceau.split(":", 1)
        cle = re.sub(r"(?<!^)(?=[A-Z])", "-", cle.strip()).lower()
        valeur = valeur.strip().strip("'\"")
        if cle and valeur:
            declarations.append(f"{cle}:{valeur}")
    return 'style="' + ";".join(declarations) + '"'


def jsx_vers_svg(source: str) -> str | None:
    """Extrait le SVG d'un composant React et le rend autonome.

    Trois transformations : on isole la balise <svg>, on convertit les
    accolades JSX (`height={24}`) en attributs classiques, et on ramène les
    noms camelCase à la notation à tirets qu'attend le SVG.
    """
    debut = source.find("<svg")
    fin = source.rfind("</svg>")
    if debut == -1 or fin == -1:
        return None

    svg = source[debut : fin + len("</svg>")]
    svg = svg.replace("{...props}", "")

    # style={{ opacity: 0.3, fill: '#FF7769' }} -> style="opacity:0.3;fill:#FF7769"
    # À faire avant le cas général : les accolades imbriquées lui échappent.
    svg = re.sub(r"style=\{\{(.*?)\}\}", _style_jsx, svg, flags=re.S)

    # height={24} -> height="24" ; opacity={0.3} -> opacity="0.3"
    svg = re.sub(r'(\w[\w:-]*)=\{["\']?([^}"\']*)["\']?\}', r'\1="\2"', svg)

    for nom in CAMEL:
        kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", nom).lower()
        svg = svg.replace(f"{nom}=", f"{kebab}=")

    # Les attributs React sans équivalent SVG.
    svg = re.sub(r'\s(?:aria-label|role)="[^"]*"', "", svg)

    if "xmlns=" not in svg:
        svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return re.sub(r"\n\s*\n", "\n", svg).strip()


def telecharger_archive() -> zipfile.ZipFile:
    print("Téléchargement de l'archive du dépôt… ", end="", flush=True)
    reponse = requests.get(ARCHIVE, timeout=180)
    reponse.raise_for_status()
    print(f"{len(reponse.content) // 1024} Ko")
    return zipfile.ZipFile(io.BytesIO(reponse.content))


def extraire_badges(archive: zipfile.ZipFile) -> int:
    destination = badges_dir()
    destination.mkdir(parents=True, exist_ok=True)
    print(f"\nIcônes de badges vers {destination}")

    faits = 0
    for nom_source, nom_cible in BADGES.items():
        chemin = f"{RACINE}src/icons/move-classifications/{nom_source}.tsx"
        try:
            source = archive.read(chemin).decode("utf-8")
        except KeyError:
            print(f"  {nom_cible:<18} absent du dépôt")
            continue

        svg = jsx_vers_svg(source)
        if svg is None:
            print(f"  {nom_cible:<18} conversion impossible")
            continue

        (destination / f"{nom_cible}.svg").write_text(svg, encoding="utf-8")
        print(f"  {nom_cible:<18} {len(svg)} octets")
        faits += 1
    return faits


def extraire_pieces(archive: zipfile.ZipFile) -> int:
    print(f"\nJeux de pièces vers {pieces_dir()}")
    faits = 0
    for jeu in JEUX:
        destination = pieces_dir() / f"cgr-{jeu}"
        destination.mkdir(parents=True, exist_ok=True)

        complet = True
        for source, cible in PIECES.items():
            chemin = f"{RACINE}public/pieces/{jeu}/{source}.png"
            try:
                (destination / f"{cible}.png").write_bytes(archive.read(chemin))
            except KeyError:
                complet = False
                break

        if complet:
            (destination / "LICENSE.txt").write_text(
                "Extrait de vietan0/chess-game-review (MIT).\n"
                "Les noms « classic », « neo » et « ocean » sont ceux des jeux de\n"
                "chess.com : l'origine réelle de ces images est incertaine.\n",
                encoding="utf-8",
            )
            print(f"  cgr-{jeu:<14} 12 pièces")
            faits += 1
        else:
            print(f"  cgr-{jeu:<14} incomplet, ignoré")
    return faits


def extraire_ouvertures(archive: zipfile.ZipFile) -> int:
    """Base d'ouvertures de chess-game-review.

    Ses trois premières colonnes — eco, name, pgn — sont exactement celles
    qu'attend OpeningBook ; les colonnes uci et epd supplémentaires sont
    ignorées sans gêne. Elle cohabite avec les fichiers Lichess : les positions
    se complètent, et la plus courte l'emporte en cas de doublon.
    """
    destination = openings_dir()
    destination.mkdir(parents=True, exist_ok=True)
    print(f"\nOuvertures vers {destination}")

    try:
        contenu = archive.read(f"{RACINE}src/openings.tsv").decode("utf-8")
    except KeyError:
        print("  absente du dépôt")
        return 0

    cible = destination / "cgr.tsv"
    cible.write_text(contenu, encoding="utf-8")
    print(f"  cgr.tsv           {len(contenu.splitlines()) - 1} lignes")
    return 1


def main() -> int:
    arguments = sys.argv[1:]
    cibles = {a for a in arguments if a.startswith("--")}
    tout = not cibles
    badges = tout or "--badges" in cibles
    pieces = tout or "--pieces" in cibles
    ouvertures = tout or "--openings" in cibles

    try:
        archive = telecharger_archive()
    except requests.RequestException as exc:
        print(f"échec : {exc}")
        return 1

    total = 0
    if badges:
        total += extraire_badges(archive)
    if pieces:
        total += extraire_pieces(archive)
    if ouvertures:
        total += extraire_ouvertures(archive)

    print(f"\n{total} élément(s) installé(s).")
    if badges:
        print("Les icônes remplacent les symboles texte sur l'échiquier.")
    if pieces:
        print("Les jeux apparaissent dans Réglages → Apparence.")
    if ouvertures:
        print("La base d'ouvertures est fusionnée avec celle de Lichess.")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())