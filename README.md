# Chess Review

Application de bureau pour analyser ses parties d'échecs avec Stockfish, en
français. Récupère les parties depuis chess.com, les classe coup par coup,
et conserve les analyses dans MySQL pour ne jamais recalculer deux fois.

![Capture](assets/icon.svg)

## Ce qu'elle fait

- **Analyse complète** d'une partie avec Stockfish : badge par coup, précision
  par camp, graphe d'évaluation cliquable
- **Onze catégories** de coups — brillant, trouvaille, meilleur, excellent,
  bon, théorique, forcé, imprécision, erreur, occasion manquée, gaffe
- **Détection des ouvertures** par position, transpositions comprises
- **Échiquier d'analyse** : joue tes propres coups depuis n'importe quelle
  position et obtiens le verdict en direct
- **Import chess.com** par pseudo, avec filtres de cadence
- **Persistance MySQL** : les analyses sont réutilisées, jamais recalculées
- Thème clair / sombre / système, jeux de pièces interchangeables, sons

## Installation

Il faut Python 3.10 ou plus, Stockfish, et MySQL ou MariaDB.

```bash
sudo apt install stockfish mariadb-server   # Debian, Ubuntu, Kali

git clone https://github.com/ThierryMeyeul/chess-review.git
cd chess-review
python3 -m venv .venv
bash scripts/install.sh
```

Le script installe les dépendances, crée la commande `chess-review`, ajoute
l'entrée du menu d'applications, génère l'icône et termine par un diagnostic.

### Base de données

```sql
CREATE DATABASE chess_review CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'chess'@'localhost' IDENTIFIED BY 'un-mot-de-passe';
GRANT ALL PRIVILEGES ON chess_review.* TO 'chess'@'localhost';
```

Copie `.env.example` en `.env` et complète-le. Les tables se créent au premier
lancement. La base est optionnelle : sans elle, l'application fonctionne mais
ne mémorise rien.

### Ressources optionnelles

```bash
python scripts/fetch_openings.py      # base d'ouvertures Lichess
python scripts/make_sounds.py         # sons synthétisés
python scripts/fetch_pieces.py --all  # jeux de pièces
python scripts/fetch_cgr_assets.py    # icônes de badges et jeux supplémentaires
```

Voir [NOTICE.md](NOTICE.md) pour l'origine et la licence de chacune.

## Utilisation

```bash
chess-review                 # lance l'application
chess-review partie.pgn      # ouvre un fichier
chess-review --check         # diagnostic d'installation
```

Raccourcis : flèches pour naviguer, Haut/Bas pour sauter de faute en faute,
Ctrl+R pour analyser, Ctrl+Maj+R pour forcer une réanalyse, Ctrl+L pour la
bibliothèque, Ctrl+F pour retourner l'échiquier, Échap pour quitter
l'exploration.

## Architecture

```
src/core/    logique pure, sans Qt — testée
  engine.py      encapsulation de Stockfish
  classify.py    attribution des badges et calcul de précision
  openings.py    détection de la théorie
  material.py    matériel capturé
  navigation.py  parcours d'une partie
  fetch.py       client de l'API chess.com
  database.py    persistance SQLAlchemy
src/ui/      interface PySide6
tests/       suite pytest
```

La séparation est stricte : `src/core` n'importe jamais Qt, ce qui rend toute
la logique testable sans ouvrir de fenêtre. `database.py` tourne sur MySQL en
production et sur SQLite en mémoire pendant les tests, et `fetch.py` accepte
une session HTTP injectable — la suite complète s'exécute donc sans serveur ni
réseau.

```bash
python -m pytest
```

## Sur la classification

Les seuils viennent de
[vietan0/chess-game-review](https://github.com/vietan0/chess-game-review) :
cinq grilles en centipions choisies selon l'ampleur de l'évaluation de départ,
avec une variante selon que le joueur perdait déjà. Les quatre combinaisons
mat/évaluation sont portées de la même source.

La détection du brillant, de la trouvaille et de l'occasion manquée vient de
[GuillaumeSD/Chesskit](https://github.com/GuillaumeSD/Chesskit), ces trois
badges étant absents de la première. Elles se désactivent dans les réglages,
ce qui ramène exactement aux huit catégories d'origine.

La courbe de précision est celle de chess-game-review, nettement plus sévère
que celle de Lichess et alignée sur les scores de chess.com.

Deux ajouts qui ne viennent d'aucune des deux : « meilleur » est réservé au
coup que Stockfish recommande, et les positions terminales reçoivent une
évaluation au lieu de zéro.

## Licence

GPL-3.0, par obligation : le projet dépend de python-chess et de Stockfish,
tous deux sous cette licence.
