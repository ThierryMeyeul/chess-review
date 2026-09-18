#!/usr/bin/env python3
"""Génère les sons de l'application dans assets/sounds/.

    python scripts/make_sounds.py

Les sons de chess.com sont leur propriété et ne peuvent pas être redistribués.
Plutôt que de les copier, on les synthétise : quelques sinusoïdes amorties et
un peu de bruit suffisent à produire des clics de pièce convaincants, en pure
bibliothèque standard, sans aucune dépendance ni question de licence.

Si tu possèdes tes propres fichiers, dépose-les dans assets/sounds/ sous les
mêmes noms : le lecteur les utilisera à la place.
"""

from __future__ import annotations

import math
import random
import struct
import wave
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.paths import sounds_dir

DESTINATION = sounds_dir()
TAUX = 44_100
AMPLITUDE = 0.55


def enveloppe(t: float, duree: float, attaque: float = 0.004, decroissance: float = 18.0) -> float:
    """Attaque très brève puis décroissance exponentielle : un clic, pas une note."""
    if t < attaque:
        return t / attaque
    return math.exp(-decroissance * (t - attaque) / duree)


def synthetiser(
    duree: float,
    partiels: list[tuple[float, float]],
    bruit: float = 0.0,
    decroissance: float = 18.0,
    glissando: float = 1.0,
) -> bytes:
    """Somme de partiels amortis, avec une pincée de bruit pour l'attaque.

    `partiels` est une liste de (fréquence en Hz, poids).
    `glissando` multiplie la fréquence à la fin du son : 1.0 = fixe,
    >1 = montant, <1 = descendant.
    """
    total = sum(poids for _, poids in partiels) or 1.0
    echantillons = int(TAUX * duree)
    trames = bytearray()
    aleatoire = random.Random(1234)  # graine fixe : sons reproductibles

    for n in range(echantillons):
        t = n / TAUX
        avancement = n / max(1, echantillons - 1)
        facteur = 1.0 + (glissando - 1.0) * avancement

        valeur = 0.0
        for frequence, poids in partiels:
            valeur += poids * math.sin(2.0 * math.pi * frequence * facteur * t)
        valeur /= total

        if bruit > 0.0:
            # Le bruit ne dure que l'attaque : c'est lui qui donne le « toc ».
            valeur += bruit * (aleatoire.random() * 2.0 - 1.0) * math.exp(-90.0 * t)

        valeur *= AMPLITUDE * enveloppe(t, duree, decroissance=decroissance)
        valeur = max(-1.0, min(1.0, valeur))
        trames += struct.pack("<h", int(valeur * 32_767))

    return bytes(trames)


def ecrire(nom: str, donnees: bytes) -> None:
    chemin = DESTINATION / f"{nom}.wav"
    with wave.open(str(chemin), "wb") as fichier:
        fichier.setnchannels(1)
        fichier.setsampwidth(2)
        fichier.setframerate(TAUX)
        fichier.writeframes(donnees)
    print(f"{chemin}  ({len(donnees) // 1024} Ko)")


SONS = {
    # Déplacement simple : bois sec, médium.
    "move": dict(duree=0.09, partiels=[(420, 1.0), (840, 0.35), (1260, 0.12)], bruit=0.30),
    # Prise : plus grave et plus mat, on entend le choc.
    "capture": dict(
        duree=0.12, partiels=[(240, 1.0), (360, 0.5), (700, 0.2)], bruit=0.45, decroissance=14.0
    ),
    # Échec : clair et montant, ça doit alerter.
    "check": dict(
        duree=0.16, partiels=[(880, 1.0), (1320, 0.4)], bruit=0.08, glissando=1.35
    ),
    # Roque : deux pièces qui bougent, donc plus long et plus rond.
    "castle": dict(duree=0.14, partiels=[(330, 1.0), (495, 0.6)], bruit=0.25, decroissance=12.0),
    # Promotion : montée franche.
    "promote": dict(
        duree=0.24, partiels=[(520, 1.0), (780, 0.35)], bruit=0.05, glissando=1.8, decroissance=8.0
    ),
    # Faute : descente grave, sans agressivité.
    "blunder": dict(
        duree=0.26, partiels=[(300, 1.0), (450, 0.3)], bruit=0.04, glissando=0.55, decroissance=7.0
    ),
    # Fin de partie.
    "end": dict(
        duree=0.34, partiels=[(392, 1.0), (523, 0.7), (659, 0.5)], bruit=0.02, decroissance=5.0
    ),
}


def main() -> int:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for nom, reglages in SONS.items():
        ecrire(nom, synthetiser(**reglages))
    print(f"\n{len(SONS)} sons générés dans {DESTINATION}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())