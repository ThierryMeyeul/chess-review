#!/usr/bin/env python3
"""Génère l'icône de l'application dans assets/.

    python scripts/make_icon.py

Produit assets/icon.svg puis les déclinaisons PNG attendues par les
environnements de bureau. Le rendu passe par Qt, déjà installé : pas de
dépendance à ImageMagick ni Inkscape.

Le motif : un damier 8x8 complet en fond, assombri sur les bords, et un
cavalier Cburnett dessiné par-dessus — le même jeu de pièces que l'échiquier
par défaut de l'application.

Le piège de ce dessin est l'épaisseur du trait. Cburnett est conçu pour être
tracé à 1,5 unité dans un repère de 45 ; mis à l'échelle de l'icône, ce trait
deviendrait un gros contour noir. Il est donc ramené à 0,72 unité locale, ce
qui donne quatre pixels sur 256 — assez pour détacher la pièce du damier, pas
assez pour l'empâter.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.paths import PROJECT_ROOT

TAILLES = (16, 24, 32, 48, 64, 128, 256, 512)

# Couleurs de l'échiquier par défaut de l'application.
CASE_SOMBRE = "#6E8F4E"
CASE_CLAIRE = "#E9EBD2"
BORD = "#3C5029"
PIECE = "#FCFCF6"
PIECE_BAS = "#DEDECF"
TRAIT = "#26331B"

# Tracés du cavalier Cburnett, tels qu'embarqués par python-chess, exprimés
# dans un repère de 45 unités. Reproduits ici plutôt que redessinés : c'est le
# jeu que l'application affiche par défaut, donc l'icône et l'échiquier se
# ressemblent, et un cavalier convaincant ne s'improvise pas.
# Cburnett : GPLv2+ / CC BY-SA 3.0.
CORPS = "M 22,10 C 32.5,11 38.5,18 38,39 L 15,39 C 15,30 25,32.5 23,18"
TETE = (
    "M 24,18 C 24.38,20.91 18.45,25.37 16,27 C 13,29 13.18,31.34 11,31 "
    "C 9.958,30.06 12.41,27.96 11,28 C 10,28 11.19,29.23 10,30 "
    "C 9,30 5.997,31 6,26 C 6,24 12,14 12,14 C 12,14 13.89,12.1 14,10.5 "
    "C 13.27,9.506 13.5,8.5 13.5,7.5 C 14.5,6.5 16.5,10 16.5,10 L 18.5,10 "
    "C 18.5,10 19.28,8.008 21,7 C 22,7 22,10 22,10"
)
NASEAU = "M 9.5 25.5 A 0.5 0.5 0 1 1 8.5,25.5 A 0.5 0.5 0 1 1 9.5 25.5 z"
OEIL = "M 15 15.5 A 0.5 1.5 0 1 1 14,15.5 A 0.5 1.5 0 1 1 15 15.5 z"

# Le cavalier occupe 32 unités sur 45 ; cette échelle le porte à 176 pixels
# sur 256, centré un peu bas pour l'équilibre optique.
ECHELLE = 5.5
DECALAGE_X = 7.0
DECALAGE_Y = 13.5
EPAISSEUR = 0.72  # en unités locales : 4 pixels une fois mis à l'échelle


def damier() -> str:
    """Huit rangées de huit cases, les claires seules étant dessinées."""
    cote = 256.0 / 8.0
    cases = []
    for ligne in range(8):
        for colonne in range(8):
            if (ligne + colonne) % 2 == 0:
                cases.append(
                    f'<rect x="{colonne * cote:.0f}" y="{ligne * cote:.0f}" '
                    f'width="{cote:.0f}" height="{cote:.0f}"/>'
                )
    return "\n      ".join(cases)


def construire_svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="piece" x1="0" y1="0" x2="0.25" y2="1">
      <stop offset="0" stop-color="{PIECE}"/>
      <stop offset="1" stop-color="{PIECE_BAS}"/>
    </linearGradient>
    <radialGradient id="vignette" cx="0.5" cy="0.42" r="0.78">
      <stop offset="0.45" stop-color="#000000" stop-opacity="0"/>
      <stop offset="1" stop-color="#000000" stop-opacity="0.34"/>
    </radialGradient>
    <clipPath id="coins">
      <rect width="256" height="256" rx="52" ry="52"/>
    </clipPath>
  </defs>

  <g clip-path="url(#coins)">
    <rect width="256" height="256" fill="{CASE_SOMBRE}"/>
    <g fill="{CASE_CLAIRE}">
      {damier()}
    </g>

    <!-- Assombrissement des bords : le damier reste lisible en périphérie
         mais cesse de concurrencer la pièce au centre. -->
    <rect width="256" height="256" fill="url(#vignette)"/>

    <g transform="translate({DECALAGE_X} {DECALAGE_Y}) scale({ECHELLE})">
      <!-- Ombre portée : mêmes tracés, décalés, avant la pièce. -->
      <g transform="translate(0.7 1.1)" fill="#101A0B" opacity="0.32"
         stroke="#101A0B" stroke-opacity="0.32" stroke-width="{EPAISSEUR}"
         stroke-linecap="round" stroke-linejoin="round">
        <path d="{CORPS}"/>
        <path d="{TETE}"/>
      </g>

      <g fill="url(#piece)" stroke="{TRAIT}" stroke-width="{EPAISSEUR}"
         stroke-linecap="round" stroke-linejoin="round">
        <path d="{CORPS}"/>
        <path d="{TETE}"/>
      </g>
      <path d="{NASEAU}" fill="{TRAIT}" stroke="{TRAIT}"
            stroke-width="{EPAISSEUR}" stroke-linejoin="round"/>
      <path d="{OEIL}" fill="{TRAIT}" stroke="{TRAIT}"
            stroke-width="{EPAISSEUR}" stroke-linejoin="round"
            transform="rotate(30 14.5 15.5)"/>
    </g>

    <rect x="2" y="2" width="252" height="252" rx="50" ry="50"
          fill="none" stroke="{BORD}" stroke-width="4" stroke-opacity="0.55"/>
  </g>
</svg>
"""


def main() -> int:
    from PySide6.QtCore import QByteArray, QSize, Qt
    from PySide6.QtGui import QGuiApplication, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer

    # QPainterPath et QPixmap exigent une application Qt, même sans fenêtre.
    application = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])

    destination = PROJECT_ROOT / "assets"
    destination.mkdir(parents=True, exist_ok=True)

    svg = construire_svg()
    chemin_svg = destination / "icon.svg"
    chemin_svg.write_text(svg, encoding="utf-8")
    print(f"{chemin_svg}  ({len(svg)} octets)")

    moteur = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not moteur.isValid():
        print("SVG invalide", file=sys.stderr)
        return 1

    for taille in TAILLES:
        pixmap = QPixmap(QSize(taille, taille))
        pixmap.fill(Qt.GlobalColor.transparent)
        peintre = QPainter(pixmap)
        peintre.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        peintre.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        moteur.render(peintre)
        peintre.end()
        pixmap.save(str(destination / f"icon-{taille}.png"), "PNG")

    del application
    print(f"{len(TAILLES)} PNG de 16 à 512 px générés dans {destination}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())