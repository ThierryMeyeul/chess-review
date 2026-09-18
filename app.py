#!/usr/bin/env python3
"""Lancement depuis la racine du projet.

    python app.py [partie.pgn]

Identique à la commande `chess-review` une fois le projet installé.
"""

from __future__ import annotations

import sys

from src.cli import main

if __name__ == "__main__":
    sys.exit(main())