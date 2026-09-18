"""Point d'entrée en ligne de commande.

Installé sous le nom `chess-review` par pyproject.toml. Contrairement à
app.py, il ne suppose rien sur le répertoire courant : le .env est cherché à
la racine du projet et non là où la commande a été tapée.
"""

from __future__ import annotations

import argparse
import os
import sys

# Avant tout import de Qt : son moteur multimédia FFmpeg annonce sur la sortie
# d'erreur chaque fichier audio qu'il ouvre. Sans intérêt pour l'utilisateur,
# et illisible au milieu d'une vraie trace d'erreur.
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.ffmpeg=false")


def main(argv: list[str] | None = None) -> int:
    analyseur = argparse.ArgumentParser(
        prog="chess-review",
        description="Analyse tes parties d'échecs avec Stockfish.",
    )
    analyseur.add_argument(
        "pgn", nargs="?", help="fichier PGN à ouvrir au démarrage"
    )
    analyseur.add_argument(
        "--version", action="store_true", help="affiche la version et quitte"
    )
    analyseur.add_argument(
        "--check",
        action="store_true",
        help="vérifie l'installation (moteur, ouvertures, sons, base) et quitte",
    )
    options = analyseur.parse_args(argv)

    if options.version:
        print(f"chess-review {VERSION}")
        return 0

    from dotenv import load_dotenv

    from src.core.paths import env_file

    load_dotenv(env_file())

    if options.check:
        return _diagnostic()

    from src.ui.main_window import run

    return run(pgn_path=options.pgn)


VERSION = "1.0.0"


def _diagnostic() -> int:
    """Vérifie que tout est en place. Utile après une installation."""
    from pathlib import Path

    from src.core.paths import PROJECT_ROOT, openings_dir, sounds_dir

    lignes: list[tuple[str, bool, str]] = []

    try:
        from src.core.engine import find_stockfish

        chemin = find_stockfish()
        lignes.append(("Stockfish", True, chemin))
    except Exception as exc:
        lignes.append(("Stockfish", False, str(exc)))

    tsv = list(openings_dir().glob("*.tsv"))
    lignes.append(
        (
            "Ouvertures",
            bool(tsv),
            f"{len(tsv)} fichier(s) dans {openings_dir()}"
            if tsv
            else "absentes — lance scripts/fetch_openings.py",
        )
    )

    wav = list(sounds_dir().glob("*.wav"))
    lignes.append(
        (
            "Sons",
            bool(wav),
            f"{len(wav)} fichier(s)" if wav else "absents — lance scripts/make_sounds.py",
        )
    )

    env = Path(PROJECT_ROOT / ".env")
    lignes.append(("Fichier .env", env.is_file(), str(env)))

    try:
        from src.core.database import DatabaseConfig, GameRepository

        config = DatabaseConfig.from_env()
        if not config.configured:
            lignes.append(("Base de données", False, "non configurée dans .env"))
        else:
            depot = GameRepository(config.url)
            depot.ping()
            stats = depot.stats()
            depot.dispose()
            lignes.append(
                (
                    "Base de données",
                    True,
                    f"{config.url_masquee} · {stats['games']} partie(s)",
                )
            )
    except Exception as exc:
        lignes.append(("Base de données", False, str(exc).split("\n")[0][:90]))

    print(f"chess-review {VERSION}\nracine : {PROJECT_ROOT}\n")
    for nom, ok, detail in lignes:
        print(f"  {'✓' if ok else '✗'}  {nom:<16} {detail}")

    # La base et le .env sont facultatifs : seul le moteur est indispensable.
    return 0 if lignes[0][1] else 1


if __name__ == "__main__":
    sys.exit(main())