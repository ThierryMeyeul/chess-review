#!/usr/bin/env python3
"""Télécharge la base d'ouvertures Lichess dans data/openings/.

    python scripts/fetch_openings.py

Cinq fichiers TSV, environ 500 Ko au total. À relancer seulement si tu veux
une version à jour — la théorie d'ouverture ne bouge pas vite.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.openings import LICHESS_TSV_URL, TSV_NAMES, OpeningBook
from src.core.paths import openings_dir

DESTINATION = openings_dir()


def main() -> int:
    DESTINATION.mkdir(parents=True, exist_ok=True)

    for name in TSV_NAMES:
        url = LICHESS_TSV_URL.format(name=name)
        cible = DESTINATION / f"{name}.tsv"
        print(f"Téléchargement de {name}.tsv ... ", end="", flush=True)
        try:
            reponse = requests.get(url, timeout=30)
            reponse.raise_for_status()
        except requests.RequestException as exc:
            print(f"échec ({exc})")
            return 1
        cible.write_text(reponse.text, encoding="utf-8")
        print(f"{len(reponse.text) // 1024} Ko")

    book = OpeningBook.from_directory(DESTINATION)
    print(f"\nBase chargée : {len(book)} positions indexées.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())