#!/usr/bin/env python3
"""Télécharge les sons de coups depuis le dépôt chess-game-review.

    python scripts/fetch_sounds.py

Le dépôt source (vietan0/chess-game-review) est sous licence MIT, mais les noms
des fichiers — move-self, move-check, capture — sont exactement ceux du jeu de
sons de chess.com. Leur origine réelle est donc incertaine : à toi de juger si
ton usage le permet. Rien n'est embarqué dans ce dépôt.

Les fichiers sont convertis en WAV, par ffmpeg s'il est installé, sinon par
soundfile (installable avec pip, sans dépendance système). Ce n'est pas
cosmétique : Qt lit le mp3 via FFmpeg, qui déverse sur la sortie d'erreur le
détail de chaque fichier ouvert puis un avertissement d'horodatage à chaque
lecture. En WAV, Qt utilise QSoundEffect, qui décode lui-même — sortie propre
et latence moindre.

Les sons synthétisés par scripts/make_sounds.py restent l'option sans
ambiguïté, et couvrent en plus les cas « gaffe » et « fin de partie » que ce
jeu-ci ne fournit pas.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.paths import sounds_dir

URL = (
    "https://raw.githubusercontent.com/vietan0/chess-game-review/main/src/sounds/{f}.mp3"
)

# Leur nom de fichier -> le nôtre.
CORRESPONDANCE = {
    "move-self": "move",
    "capture": "capture",
    "move-check": "check",
    "castle": "castle",
    "promote": "promote",
}


def _convertir_ffmpeg(mp3: Path, wav: Path) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    resultat = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", str(mp3),
            "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
            str(wav),
        ],
        capture_output=True,
    )
    return resultat.returncode == 0 and wav.is_file()


def _convertir_soundfile(mp3: Path, wav: Path) -> bool:
    """Décodage sans dépendance système.

    libsndfile 1.1 et suivantes lisent le mp3 ; le paquet soundfile embarque sa
    propre copie de la bibliothèque, donc rien à installer hors de pip.
    """
    try:
        import soundfile as sf
    except ImportError:
        return False
    try:
        donnees, taux = sf.read(str(mp3))
        sf.write(str(wav), donnees, taux, subtype="PCM_16")
    except Exception:
        return False
    return wav.is_file()


def convertir(mp3: Path) -> tuple[bool, str]:
    """mp3 -> wav 16 bits, par ffmpeg ou par soundfile.

    Rend (succès, méthode). Le mp3 est supprimé en cas de réussite : sinon il
    resterait prioritaire au chargement et FFmpeg reprendrait la main.
    """
    wav = mp3.with_suffix(".wav")

    for methode, fonction in (
        ("ffmpeg", _convertir_ffmpeg),
        ("soundfile", _convertir_soundfile),
    ):
        if fonction(mp3, wav):
            mp3.unlink()
            return True, methode

    return False, ""


def main() -> int:
    destination = sounds_dir()
    destination.mkdir(parents=True, exist_ok=True)
    print(f"Téléchargement dans {destination}\n")

    reussis = 0
    for source, cible in CORRESPONDANCE.items():
        print(f"  {cible:<10} ", end="", flush=True)
        for tentative in range(1, 4):
            try:
                reponse = requests.get(URL.format(f=source), timeout=60)
                reponse.raise_for_status()
            except requests.RequestException as exc:
                if tentative == 3:
                    print(f"échec ({type(exc).__name__})")
                    break
                print(f"·", end="", flush=True)
                continue
            mp3 = destination / f"{cible}.mp3"
            mp3.write_bytes(reponse.content)
            taille = len(reponse.content) // 1024
            converti, methode = convertir(mp3)
            if converti:
                print(f"{taille} Ko → wav ({methode})")
            else:
                print(f"{taille} Ko (mp3, non converti)")
            reussis += 1
            break

    print(f"\n{reussis}/{len(CORRESPONDANCE)} son(s) installé(s).")
    if reussis and any(destination.glob("*.mp3")):
        print(
            "\nAucun convertisseur trouvé : les sons restent en mp3 et Qt\n"
            "affichera des messages FFmpeg au démarrage. Installe l'un ou\n"
            "l'autre, puis relance ce script :\n"
            "    pip install soundfile      (dans le venv, rien en système)\n"
            "    sudo apt install ffmpeg"
        )
    if reussis:
        print("« gaffe » et « fin de partie » restent ceux de make_sounds.py.")
    return 0 if reussis else 1


if __name__ == "__main__":
    raise SystemExit(main())