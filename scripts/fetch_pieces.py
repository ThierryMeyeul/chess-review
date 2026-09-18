#!/usr/bin/env python3
"""Télécharge des jeux de pièces dans assets/pieces/.

    python scripts/fetch_pieces.py              # les quatre jeux recommandés
    python scripts/fetch_pieces.py --all        # les douze
    python scripts/fetch_pieces.py merida alpha # une sélection
    python scripts/fetch_pieces.py --list       # ce qui est disponible

Les fichiers viennent du dépôt de Lichess. Leurs licences diffèrent d'un jeu à
l'autre et sont recopiées dans assets/pieces/<jeu>/LICENSE.txt : plusieurs sont
en CC BY-NC-SA, donc réservés à un usage non commercial. Rien n'est embarqué
dans le dépôt du projet, c'est à toi de télécharger ce que tu veux utiliser.

Le jeu de python-chess (Cburnett) reste disponible sans rien télécharger.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ui.pieces import CODES_FICHIERS, JEUX_TELECHARGEABLES, pieces_dir

URL = "https://raw.githubusercontent.com/lichess-org/lila/master/public/piece/{jeu}/{code}.svg"
RECOMMANDES = ("merida", "staunty", "alpha", "chessnut")


def telecharger(jeu: str) -> bool:
    info = JEUX_TELECHARGEABLES.get(jeu)
    if info is None:
        print(f"  {jeu} : inconnu")
        return False

    destination = pieces_dir() / jeu
    destination.mkdir(parents=True, exist_ok=True)

    print(f"  {jeu} … ", end="", flush=True)
    for code in CODES_FICHIERS.values():
        # Trois essais : sur une connexion instable, un seul fichier qui
        # expire faisait perdre les onze autres déjà téléchargés.
        for tentative in range(1, 4):
            try:
                reponse = requests.get(URL.format(jeu=jeu, code=code), timeout=60)
                reponse.raise_for_status()
                break
            except requests.RequestException as exc:
                if tentative == 3:
                    print(f"échec sur {code} ({type(exc).__name__})")
                    return False
                print("·", end="", flush=True)
        (destination / f"{code}.svg").write_text(reponse.text, encoding="utf-8")

    (destination / "LICENSE.txt").write_text(
        f"{info.name}\nAuteur : {info.author}\nLicence : {info.license}\n"
        "Source : https://github.com/lichess-org/lila/tree/master/public/piece\n",
        encoding="utf-8",
    )
    print(f"12 pièces · {info.license}")
    return True


def main() -> int:
    arguments = sys.argv[1:]

    if "--list" in arguments:
        print("Jeux disponibles :\n")
        for cle, info in JEUX_TELECHARGEABLES.items():
            marque = "*" if cle in RECOMMANDES else " "
            print(f" {marque} {cle:<12} {info.license:<22} {info.author}")
        print("\n* = téléchargés par défaut · --all pour tout prendre")
        return 0

    if "--all" in arguments:
        jeux = list(JEUX_TELECHARGEABLES)
    else:
        jeux = [a for a in arguments if not a.startswith("-")] or list(RECOMMANDES)
    print(f"Téléchargement dans {pieces_dir()}\n")

    reussis = sum(telecharger(jeu) for jeu in jeux)
    print(f"\n{reussis}/{len(jeux)} jeu(x) installé(s).")
    print("Choisis-le dans Réglages → Apparence.")
    return 0 if reussis else 1


if __name__ == "__main__":
    raise SystemExit(main())