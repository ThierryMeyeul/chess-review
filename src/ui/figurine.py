"""Notation figurine.

Remplace la lettre de pièce d'un coup par son symbole : Cf3 devient ♞f3. C'est
la notation des revues d'échecs, et elle a l'avantage d'être indépendante de la
langue — un lecteur anglophone écrit Nf3 là où un francophone écrit Cf3, mais
♞f3 se lit partout.

Les symboles pleins sont utilisés pour les deux camps. La colonne de la feuille
de partie indique déjà qui joue, et alterner entre glyphes creux et pleins
entrerait en conflit avec la couleur du badge appliquée au texte.
"""

from __future__ import annotations

SYMBOLES = {
    "K": "♚",
    "Q": "♛",
    "R": "♜",
    "B": "♝",
    "N": "♞",
}


def to_figurine(san: str) -> str:
    """Convertit un coup en notation figurine.

    Seules la lettre initiale et celle d'une promotion sont remplacées : un
    « B » de case (comme dans « Bxb5 ») n'existe pas, les colonnes étant en
    minuscules, donc il n'y a pas d'ambiguïté à lever.
    """
    if not san:
        return san

    # Le roque n'a pas de lettre de pièce.
    if san.startswith("O-O"):
        return san

    sortie = san
    initiale = sortie[0]
    if initiale in SYMBOLES:
        sortie = SYMBOLES[initiale] + sortie[1:]

    if "=" in sortie:
        avant, _, apres = sortie.partition("=")
        if apres and apres[0] in SYMBOLES:
            sortie = f"{avant}={SYMBOLES[apres[0]]}{apres[1:]}"

    return sortie