# Ressources tierces

Aucune des ressources ci-dessous n'est incluse dans ce dépôt : les scripts
les téléchargent à l'installation. Cette page existe pour que leur origine et
leur licence restent traçables.

## Moteur et bibliothèques

| Composant | Licence |
|---|---|
| [Stockfish](https://stockfishchess.org/) | GPL-3.0 |
| [python-chess](https://github.com/niklasf/python-chess) | GPL-3.0 |
| [PySide6 / Qt](https://www.qt.io/) | LGPL-3.0 |
| SQLAlchemy, PyMySQL, requests, python-dotenv | MIT / BSD |

## Base d'ouvertures

`scripts/fetch_openings.py` récupère les fichiers TSV de
[lichess-org/chess-openings](https://github.com/lichess-org/chess-openings),
domaine public (CC0).

`scripts/fetch_cgr_assets.py --openings` récupère `openings.tsv` de
[vietan0/chess-game-review](https://github.com/vietan0/chess-game-review), MIT.

## Jeux de pièces

`scripts/fetch_pieces.py` télécharge depuis
[lichess-org/lila](https://github.com/lichess-org/lila/tree/master/public/piece).
Les licences diffèrent selon le jeu et sont recopiées dans
`assets/pieces/<jeu>/LICENSE.txt` :

- Merida, Cburnett, Governor : GPLv2+
- Chessnut : Apache 2.0
- Alpha : usage personnel non commercial
- Staunty, Gioco, Fresca, Cardinal, Maestro, California, Tatiana : CC BY-NC-SA 4.0

Le jeu par défaut est Cburnett, embarqué par python-chess (GPLv2+ / CC BY-SA 3.0).

## Icônes de badges et sons

`scripts/fetch_cgr_assets.py --badges` et `scripts/fetch_sounds.py` extraient
des ressources de vietan0/chess-game-review (MIT). Attention : les noms de
fichiers — `move-self`, `move-check`, `neo`, `classic` — sont ceux des jeux de
chess.com, et l'origine réelle de ces images et de ces sons est incertaine
malgré la licence du dépôt source. À utiliser en connaissance de cause.

`scripts/make_sounds.py` produit une alternative synthétisée, sans ambiguïté
de licence, et couvre en plus les cas « gaffe » et « fin de partie ».

## Icône de l'application

`scripts/make_icon.py` la génère. Les tracés du cavalier proviennent du jeu
Cburnett (GPLv2+ / CC BY-SA 3.0), auteur Colin M.L. Burnett.
