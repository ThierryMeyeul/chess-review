"""Classification des coups en badges.

Stockfish ne rend que des évaluations. Les catégories « brillant », « erreur »,
« occasion manquée » sont des heuristiques construites par-dessus. Elles sont
ici explicites et réglables, contrairement aux sites qui les gardent opaques.

Toutes les mesures sont faites du point de vue du joueur qui a joué le coup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import chess

from src.core.engine import MoveAnalysis, score_to_cp, win_probability

# --------------------------------------------------------------------------
# Catégories
# --------------------------------------------------------------------------


class MoveClass(Enum):
    """Les dix badges, du meilleur au pire."""

    BRILLIANT = "brillant"
    GREAT = "trouvaille"
    BEST = "meilleur"
    EXCELLENT = "excellent"
    GOOD = "bon"
    BOOK = "theorique"
    FORCED = "force"
    INACCURACY = "imprecision"
    MISTAKE = "erreur"
    MISS = "occasion_manquee"
    BLUNDER = "gaffe"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def symbol(self) -> str:
        return _SYMBOLS[self]

    @property
    def is_mistake(self) -> bool:
        """Vrai pour les catégories qui méritent qu'on s'y arrête."""
        return self in (
            MoveClass.INACCURACY,
            MoveClass.MISTAKE,
            MoveClass.MISS,
            MoveClass.BLUNDER,
        )


_LABELS = {
    MoveClass.BRILLIANT: "Brillant",
    MoveClass.GREAT: "Trouvaille",
    MoveClass.BEST: "Meilleur",
    MoveClass.EXCELLENT: "Excellent",
    MoveClass.GOOD: "Bon",
    MoveClass.BOOK: "Théorique",
    MoveClass.FORCED: "Forcé",
    MoveClass.INACCURACY: "Imprécision",
    MoveClass.MISTAKE: "Erreur",
    MoveClass.MISS: "Occasion manquée",
    MoveClass.BLUNDER: "Gaffe",
}

_SYMBOLS = {
    MoveClass.BRILLIANT: "!!",
    MoveClass.GREAT: "!",
    MoveClass.BEST: "",
    MoveClass.EXCELLENT: "",
    MoveClass.GOOD: "",
    MoveClass.BOOK: "",
    MoveClass.FORCED: "",
    MoveClass.INACCURACY: "?!",
    MoveClass.MISTAKE: "?",
    MoveClass.MISS: "?",
    MoveClass.BLUNDER: "??",
}


# --------------------------------------------------------------------------
# Réglages
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassifierConfig:
    """Seuils de classification.

    Les seuils portent sur la chute de probabilité de victoire (0..1) et non
    sur les centipions : perdre 100 centipions n'a pas le même poids en
    position égale et en position déjà gagnée.
    """

    excellent_max_drop: float = 0.02
    good_max_drop: float = 0.05
    inaccuracy_max_drop: float = 0.10
    mistake_max_drop: float = 0.20
    # au-delà : gaffe

    # Badges absents de chess-game-review, ajoutés par-dessus sa logique.
    # Les désactiver donne exactement ses huit catégories.
    detect_special: bool = True

    # « Occasion manquée » : on gâche une position déjà nettement gagnante.
    miss_min_win_prob: float = 0.75

    # « Trouvaille » : le coup joué est le seul à tenir la position, ou il
    # renverse l'issue de la partie. Second critère repris de Chesskit : faire
    # basculer la barre des 50 % est plus parlant qu'un simple écart.
    great_min_gap: float = 0.10
    great_min_swing: float = 0.10        # gain minimal pour un renversement
    great_max_alternative: float = 0.97  # alternative déjà totalement gagnante

    # Mats. Les centipions ne disent rien d'un mat : plafonnés à ±1000, un
    # mat en 1 et un mat en 15 deviennent identiques. Ces seuils comparent les
    # distances au mat plutôt que les évaluations.
    mate_delay_excellent: int = 3   # repousser le mat de 3 coups reste excellent
    mate_delay_good: int = 7
    mate_lost_blunder_cp: int = 0   # mat perdu ET position perdue
    mate_lost_miss_cp: int = 300    # mat perdu, avantage modeste conservé
    mate_lost_mistake_cp: int = 500
    mated_blunder_cp: int = -400    # se faire mater depuis une position tenable
    mated_mistake_cp: int = -600

    # « Brillant » : sacrifice matériel avec compensation démontrable.
    brilliant_min_sacrifice: float = 2.0   # en pions — une pièce, pas un pion
    brilliant_min_cp_after: int = 0        # rester au moins à égalité
    brilliant_max_cp_before: int = 600     # pas déjà gagné d'office
    brilliant_min_gap: float = 0.05        # nettement mieux que l'alternative


PIECE_VALUES = {
    chess.PAWN: 1.0,
    chess.KNIGHT: 3.0,
    chess.BISHOP: 3.0,
    chess.ROOK: 5.0,
    chess.QUEEN: 9.0,
    chess.KING: 0.0,
}


# --------------------------------------------------------------------------
# Mesures intermédiaires
# --------------------------------------------------------------------------


def material_balance(board: chess.Board, color: chess.Color) -> float:
    """Balance matérielle en pions, du point de vue de `color`."""
    total = 0.0
    for piece_type, valeur in PIECE_VALUES.items():
        total += valeur * len(board.pieces(piece_type, color))
        total -= valeur * len(board.pieces(piece_type, not color))
    return total


def sacrifice_amount(analysis: MoveAnalysis, profondeur: int = 4) -> float:
    """Matériel concédé par le coup, une fois la variante principale déroulée.

    Deux raffinements par rapport au décompte immédiat. D'abord on pousse la
    réponse adverse : sans elle un sacrifice ressemble à un coup neutre,
    puisque la pièce est encore là. Ensuite on déroule quelques demi-coups de
    la variante principale, parce qu'un sacrifice se solde souvent une ou deux
    reprises plus tard — un décompte à un seul coup confond « je donne une
    pièce » et « je donne une pièce que je reprends aussitôt ».
    """
    board = chess.Board(analysis.fen_before)
    joueur = analysis.turn
    avant = material_balance(board, joueur)

    board.push(analysis.move)
    meilleure_reponse = analysis.after.best
    if meilleure_reponse is None:
        return avant - material_balance(board, joueur)

    pire = avant - material_balance(board, joueur)
    for coup in meilleure_reponse.pv[:profondeur]:
        if coup not in board.legal_moves:
            break
        board.push(coup)
        pire = max(pire, avant - material_balance(board, joueur))

    return pire


def is_simple_recapture(
    analysis: MoveAnalysis, previous: MoveAnalysis | None
) -> bool:
    """Le coup ne fait-il que reprendre sur la case où l'adversaire vient de
    capturer ?

    Reprendre une pièce est souvent le seul coup sensé, donc l'écart avec la
    deuxième variante est énorme — ce qui décrocherait une « Trouvaille » pour
    un coup que n'importe quel débutant trouve. Critère emprunté à Chesskit.
    """
    if previous is None:
        return False
    if analysis.move.to_square != previous.move.to_square:
        return False
    plateau = chess.Board(previous.fen_before)
    return plateau.is_capture(previous.move)


def offers_material(analysis: MoveAnalysis) -> bool:
    """La pièce qui vient de bouger est-elle immédiatement reprise ?

    C'est ce qui distingue un sacrifice d'une pièce qui pendait déjà. Sans ce
    test, laisser un cavalier en prise et jouer ailleurs compte comme un
    sacrifice : la perte est réelle, mais elle précède le coup.
    """
    reponse = analysis.after.best
    if reponse is None:
        return False
    return reponse.move.to_square == analysis.move.to_square


def best_line_gap(analysis: MoveAnalysis) -> float:
    """Écart de probabilité de victoire entre la meilleure et la deuxième ligne.

    Un écart large signifie qu'il n'y avait qu'un seul coup jouable.
    """
    lignes = analysis.before.lines
    if len(lignes) < 2:
        return 0.0

    def proba(ligne) -> float:
        cp = score_to_cp(ligne.score_white)
        if analysis.turn == chess.BLACK:
            cp = -cp
        return win_probability(cp)

    return max(0.0, proba(lignes[0]) - proba(lignes[1]))


# Coefficients de la courbe de précision. Celle de Lichess
# (103.1668 · e^(−0.04354·Δ) − 3.1669) est nettement plus indulgente et rendait
# des scores supérieurs d'une quinzaine de points à ceux de chess.com. Ceux-ci
# viennent de chess-game-review et collent aux valeurs de chess.com.
# Version des règles de classification. À incrémenter dès qu'un verdict peut
# changer : les analyses enregistrées sous une version antérieure sont alors
# recalculées au lieu d'être réaffichées telles quelles.
RULES_VERSION = 3

ACCURACY_A = 99.99
ACCURACY_B = -0.14


def move_accuracy(drop: float) -> float:
    """Précision d'un coup en pourcentage.

    `drop` est la chute de probabilité de victoire (0..1). Un coup qui améliore
    la position vaut 100 : on ne récompense pas au-delà du parfait, et un gain
    signifie surtout que le moteur voyait moins loin avant.
    """
    import math

    if drop <= 0:
        return 100.0
    valeur = ACCURACY_A * math.exp(ACCURACY_B * (drop * 100.0))
    return max(0.0, min(100.0, valeur))


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def is_brilliant(analysis: MoveAnalysis, config: ClassifierConfig) -> bool:
    """Sacrifice matériel avec compensation démontrable.

    Cinq conditions, dans l'ordre du moins au plus coûteux à évaluer :

    1. Le coup est strictement celui du moteur. « Quasi optimal » ne suffit
       pas : dans une position où dix coups se valent, larguer une pièce
       passerait le filtre.
    2. La position n'était pas déjà gagnée. Sacrifier quand on a une tour
       d'avance n'a rien de remarquable.
    3. C'est bien ce coup qui offre le matériel — la meilleure réponse
       adverse reprend sur la case d'arrivée. Sans ça, une pièce qui pendait
       déjà serait comptée comme un sacrifice.
    4. Le matériel concédé vaut au moins une pièce mineure.
    5. La compensation existe : soit le coup mène au mat, soit il laisse au
       moins l'égalité ET il est nettement meilleur que l'alternative.

    Le point 5 est la traduction de « sacrifier pour obtenir quelque chose ».
    Un sacrifice qui laisse la position au même niveau qu'un coup tranquille
    n'est pas une trouvaille, c'est un choix.
    """
    if analysis.before.is_forced or not analysis.is_best:
        return False
    if analysis.cp_before > config.brilliant_max_cp_before:
        return False
    if not offers_material(analysis):
        return False
    if sacrifice_amount(analysis) < config.brilliant_min_sacrifice:
        return False

    mat = analysis.mate_for_mover
    if mat is not None:
        return mat > 0  # sacrifice qui mate : compensation maximale

    if analysis.cp_after < config.brilliant_min_cp_after:
        return False
    return best_line_gap(analysis) >= config.brilliant_min_gap


def changes_outcome(analysis: MoveAnalysis, config: ClassifierConfig) -> bool:
    """Le coup fait-il basculer l'issue de la partie ?

    Traverser la barre des 50 % avec un gain net : c'est le moment où une
    partie perdue redevient jouable, ou l'inverse.
    """
    avant = analysis.win_prob_before
    apres = analysis.win_prob_after
    if apres - avant < config.great_min_swing:
        return False
    return (avant < 0.5) != (apres < 0.5)


def is_great(
    analysis: MoveAnalysis,
    config: ClassifierConfig,
    previous: MoveAnalysis | None = None,
) -> bool:
    """Coup remarquable sans sacrifice : seul coup jouable, ou renversement.

    Trois garde-fous repris de Chesskit : une simple reprise ne compte pas, un
    coup qui laisse la position perdue non plus, et si l'alternative était déjà
    totalement gagnante il n'y avait aucun mérite à trouver celui-ci.
    """
    if analysis.before.is_forced or not analysis.is_best:
        return False
    if is_simple_recapture(analysis, previous):
        return False
    if analysis.win_prob_after < 0.5 and not changes_outcome(analysis, config):
        return False

    lignes = analysis.before.lines
    if len(lignes) >= 2:
        alternative = win_probability(
            score_to_cp(lignes[1].score_white)
            * (1 if analysis.turn == chess.WHITE else -1)
        )
        if alternative > config.great_max_alternative:
            return False

    return best_line_gap(analysis) >= config.great_min_gap or changes_outcome(
        analysis, config
    )


# --------------------------------------------------------------------------
# Classification portée de chess-game-review
# --------------------------------------------------------------------------

# Cinq grilles de seuils, choisies selon l'ampleur de l'évaluation de départ,
# avec une variante selon que le joueur perdait déjà. L'idée : une même perte
# de 200 centipions est une erreur en position égale, mais seulement une
# imprécision quand on gagnait largement — ou qu'on était déjà perdu.
# Ordre de chaque grille : [best, excellent, good, inaccuracy, mistake].
SEUILS_CGR = (
    # |éval| <= 50
    {"perdant": (0, -25, -50, -150, -250), "gagnant": (0, -25, -50, -150, -250)},
    # <= 300
    {"perdant": (0, -50, -100, -200, -300), "gagnant": (0, -50, -100, -150, -250)},
    # <= 400
    {"perdant": (0, -75, -150, -250, -400), "gagnant": (0, -75, -150, -200, -300)},
    # <= 500
    {"perdant": (0, -150, -200, -400, -600), "gagnant": (0, -75, -150, -200, -300)},
    # au-delà
    {"perdant": (0, -150, -200, -400, -600), "gagnant": (0, -150, -200, -300, -400)},
)

BORNES_CGR = (50, 300, 400, 500)


def _grille(cp_avant: int, perdant: bool) -> tuple[int, ...]:
    ampleur = abs(cp_avant)
    index = next(
        (i for i, borne in enumerate(BORNES_CGR) if ampleur <= borne), len(BORNES_CGR)
    )
    return SEUILS_CGR[index]["perdant" if perdant else "gagnant"]


def _depuis_grille(delta: int, seuils: tuple[int, ...]) -> MoveClass:
    if delta >= seuils[0]:
        return MoveClass.BEST
    if delta > seuils[1]:
        return MoveClass.EXCELLENT
    if delta > seuils[2]:
        return MoveClass.GOOD
    if delta > seuils[3]:
        return MoveClass.INACCURACY
    if delta > seuils[4]:
        return MoveClass.MISTAKE
    return MoveClass.BLUNDER


def _deux_evaluations(cp_avant: int, cp_apres: int, blancs: bool) -> MoveClass:
    """Les deux positions ont une évaluation chiffrée."""
    delta = (cp_apres - cp_avant) if blancs else (cp_avant - cp_apres)
    perdait = (cp_avant < 0) if blancs else (cp_avant > 0)
    meme_signe = cp_avant * cp_apres > 0

    if not perdait and meme_signe:
        # Totalement gagnant avant et après : l'imprécision est le pire verdict.
        if abs(cp_avant) > 700 and abs(cp_apres) > 400:
            if delta >= -50:
                return MoveClass.BEST
            if delta > -150:
                return MoveClass.EXCELLENT
            if delta > -200:
                return MoveClass.GOOD
            return MoveClass.INACCURACY

        # Gagnant largement, puis avantage résiduel : gaffe d'office.
        if abs(cp_avant) > 600 and abs(cp_apres) < 200:
            return MoveClass.BLUNDER

    if perdait and meme_signe:
        # Perdu avant et après : on ne s'acharne pas.
        if abs(cp_avant) > 600 and abs(cp_apres) > 900:
            if delta >= -50:
                return MoveClass.BEST
            if delta > -150:
                return MoveClass.EXCELLENT
            if delta > -200:
                return MoveClass.GOOD
            return MoveClass.INACCURACY

    return _depuis_grille(delta, _grille(cp_avant, perdait))


def _deux_mats(mat_avant: int, mat_apres: int, blancs: bool) -> MoveClass:
    """Un mat était annoncé avant et après le coup."""
    if (mat_avant > 0) != (mat_apres > 0):
        return MoveClass.BLUNDER  # le mat a changé de camp

    ecart = abs(mat_avant) - abs(mat_apres)
    # Pour le camp qui subit le mat, le repousser est un progrès.
    if (mat_avant > 0) != blancs:
        ecart = -ecart

    if ecart >= 0:
        return MoveClass.BEST
    if ecart >= -7:
        return MoveClass.EXCELLENT
    return MoveClass.GOOD


def _evaluation_vers_mat(cp_avant: int, mat_apres: int, blancs: bool) -> MoveClass:
    """Position chiffrée avant, mat annoncé après."""
    mateur_blanc = mat_apres > 0
    if blancs:
        if mateur_blanc:
            # Les blancs jouent et obtiennent le mat : rien à reprocher.
            return MoveClass.BEST
        if cp_avant >= -400:
            return MoveClass.BLUNDER
        if cp_avant >= -600:
            return MoveClass.MISTAKE
        if cp_avant >= -1200:
            return MoveClass.INACCURACY
        return MoveClass.GOOD

    if not mateur_blanc:
        return MoveClass.BEST
    if cp_avant <= 400:
        return MoveClass.BLUNDER
    if cp_avant <= 600:
        return MoveClass.MISTAKE
    if cp_avant <= 1200:
        return MoveClass.INACCURACY
    return MoveClass.GOOD


def _mat_vers_evaluation(mat_avant: int, cp_apres: int, blancs: bool) -> MoveClass:
    """Un mat était annoncé, il a été gâché."""
    if blancs:
        if mat_avant < 0:
            return MoveClass.BEST  # les blancs échappent au mat adverse
        if cp_apres <= 300:
            return MoveClass.BLUNDER
        if cp_apres <= 500:
            return MoveClass.MISTAKE
        return MoveClass.INACCURACY

    if mat_avant > 0:
        return MoveClass.BEST
    if cp_apres >= -300:
        return MoveClass.BLUNDER
    if cp_apres >= -500:
        return MoveClass.MISTAKE
    return MoveClass.INACCURACY


def _vers_nulle(cp_avant: int, blancs: bool) -> MoveClass:
    """Le coup mène à la nulle : la sanction dépend de ce qu'on abandonne."""
    avantage = cp_avant if blancs else -cp_avant
    if avantage <= 100:
        return MoveClass.GOOD
    if avantage <= 200:
        return MoveClass.INACCURACY
    if avantage <= 300:
        return MoveClass.MISTAKE
    return MoveClass.BLUNDER


def classify_by_eval(analysis: MoveAnalysis) -> MoveClass:
    """Classification portée de chess-game-review.

    Quatre combinaisons selon que chaque position est chiffrée ou annonce un
    mat, plus le cas de la partie qui se termine. Contrairement à une mesure en
    probabilité de victoire, les seuils restent en centipions mais changent de
    grille selon le contexte.
    """
    blancs = analysis.turn == chess.WHITE

    issue = analysis.after.outcome_white
    if issue == 0.5:
        return _vers_nulle(analysis.before.cp_white, blancs)
    if issue is not None:
        # Mat délivré : le camp qui vient de jouer a gagné.
        gagnant_blanc = issue == 1.0
        return MoveClass.BEST if gagnant_blanc == blancs else MoveClass.BLUNDER

    mat_avant = analysis.before.mate_white
    mat_apres = analysis.after.mate_white

    if mat_avant is not None and mat_apres is not None:
        return _deux_mats(mat_avant, mat_apres, blancs)
    if mat_avant is None and mat_apres is not None:
        return _evaluation_vers_mat(analysis.before.cp_white, mat_apres, blancs)
    if mat_avant is not None:
        return _mat_vers_evaluation(mat_avant, analysis.after.cp_white, blancs)

    return _deux_evaluations(
        analysis.before.cp_white, analysis.after.cp_white, blancs
    )


def classify_mate(
    analysis: MoveAnalysis, config: ClassifierConfig
) -> MoveClass | None:
    """Verdict sur les coups où un mat forcé entre en jeu.

    Rend `None` si aucun mat n'est impliqué, laissant la main aux seuils
    ordinaires. Cette branche existe parce que la conversion en centipions
    écrase l'information : un mat en 1 et un mat en 15 valent tous deux le
    plafond, donc repousser un mat forcé de quatorze coups passerait pour un
    coup parfait.
    """
    avant = analysis.mate_for_mover_before
    apres = analysis.mate_for_mover

    # Le joueur disposait d'un mat forcé.
    if avant is not None and avant > 0:
        if apres is not None and apres > 0:
            retard = apres - avant
            if retard <= 0:
                return MoveClass.BEST  # mat aussi rapide, voire plus
            if retard <= config.mate_delay_excellent:
                return MoveClass.EXCELLENT
            if retard <= config.mate_delay_good:
                return MoveClass.GOOD
            return MoveClass.INACCURACY

        # Mat envolé : ce qui reste décide de la gravité.
        cp = analysis.cp_after
        if cp <= config.mate_lost_blunder_cp:
            return MoveClass.BLUNDER
        if cp <= config.mate_lost_miss_cp:
            return MoveClass.MISS
        if cp <= config.mate_lost_mistake_cp:
            return MoveClass.MISTAKE
        return MoveClass.INACCURACY

    # Le joueur se faisait déjà mater.
    if avant is not None and avant < 0:
        if apres is not None and apres < 0:
            # Repousser l'échéance est méritoire, l'accélérer est véniel :
            # la partie était perdue dans les deux cas.
            return (
                MoveClass.EXCELLENT if abs(apres) >= abs(avant) else MoveClass.GOOD
            )
        return MoveClass.EXCELLENT  # mat évité

    # Aucun mat avant, mais le joueur se fait mater après.
    if apres is not None and apres < 0:
        cp = analysis.cp_before
        if cp >= config.mated_blunder_cp:
            return MoveClass.BLUNDER
        if cp >= config.mated_mistake_cp:
            return MoveClass.MISTAKE
        return MoveClass.INACCURACY

    return None


def classify_move(
    analysis: MoveAnalysis,
    *,
    is_book: bool = False,
    config: ClassifierConfig | None = None,
    previous: MoveAnalysis | None = None,
) -> MoveClass:
    """Attribue un badge à un coup.

    `is_book` vient de la base d'ouvertures, pas du moteur : Stockfish ne sait
    pas ce qu'est la théorie.
    """
    config = config or ClassifierConfig()

    # Ordre de chess-game-review : coup forcé, puis théorie, puis évaluation.
    if analysis.before.is_forced:
        return MoveClass.FORCED
    if is_book:
        return MoveClass.BOOK

    # Les trois badges distinctifs n'existent pas chez eux — leur classify.ts
    # ne les produit jamais, seules les icônes sont présentes. On les garde en
    # couche optionnelle, avant le verdict chiffré qu'ils remplaceraient.
    if config.detect_special:
        if is_brilliant(analysis, config):
            return MoveClass.BRILLIANT
        if is_great(analysis, config, previous):
            return MoveClass.GREAT

    # Le coup en tête de la recherche est le meilleur, point. Les seuils
    # chiffrés ne peuvent pas trancher ce cas : les deux positions sont
    # analysées séparément, donc la seconde voit un demi-coup de plus et rend
    # souvent une évaluation légèrement moins favorable. Le delta devient
    # négatif et le coup parfait se retrouve classé « excellent ».
    if analysis.is_best:
        return MoveClass.BEST

    verdict = classify_by_eval(analysis)

    # « Meilleur » est réservé au coup que le moteur recommande. La grille de
    # seuils l'attribue dès que l'évaluation ne baisse pas, ce qui arrive
    # constamment en position gagnée : trois coups différents y conservent tous
    # l'avantage, mais un seul est le meilleur. Sans ce plafond, la moitié
    # d'une finale gagnée décrocherait le badge.
    if (
        verdict is MoveClass.BEST
        and analysis.before.best is not None
        and not analysis.is_best
    ):
        return MoveClass.EXCELLENT

    # « Occasion manquée » précise la gaffe commise en position gagnante.
    # Absent de leur code, ajouté pour la même raison que les deux précédents.
    if (
        config.detect_special
        and verdict is MoveClass.BLUNDER
        and analysis.win_prob_before >= config.miss_min_win_prob
    ):
        return MoveClass.MISS

    return verdict


# --------------------------------------------------------------------------
# Rapport de partie
# --------------------------------------------------------------------------


@dataclass
class ClassifiedMove:
    analysis: MoveAnalysis
    classification: MoveClass
    accuracy: float

    @property
    def san(self) -> str:
        return self.analysis.san

    @property
    def turn(self) -> chess.Color:
        return self.analysis.turn

    def __str__(self) -> str:
        numero = self.analysis.move_number
        prefixe = f"{numero}." if self.turn == chess.WHITE else f"{numero}..."
        return f"{prefixe} {self.san}{self.classification.symbol} — {self.classification.label}"


@dataclass
class PlayerReport:
    color: chess.Color
    accuracy: float
    counts: dict[MoveClass, int] = field(default_factory=dict)

    @property
    def mistakes(self) -> int:
        return sum(n for c, n in self.counts.items() if c.is_mistake)


@dataclass
class GameReport:
    moves: list[ClassifiedMove]
    white: PlayerReport
    black: PlayerReport

    def for_color(self, color: chess.Color) -> PlayerReport:
        return self.white if color == chess.WHITE else self.black

    def mistakes(self, color: chess.Color | None = None) -> list[ClassifiedMove]:
        """Les coups à revoir, éventuellement filtrés par camp."""
        return [
            m
            for m in self.moves
            if m.classification.is_mistake and (color is None or m.turn == color)
        ]


def build_report(
    analyses: list[MoveAnalysis],
    *,
    book_plies: int = 0,
    config: ClassifierConfig | None = None,
) -> GameReport:
    """Classe tous les coups et agrège les statistiques par camp.

    `book_plies` est le nombre de demi-coups encore dans la théorie ; ils sont
    marqués « Théorique » mais comptent dans la précision, puisqu'un coup de
    livre est par définition un bon coup.
    """
    config = config or ClassifierConfig()

    classes: list[ClassifiedMove] = []
    for index, analysis in enumerate(analyses):
        est_theorique = analysis.ply <= book_plies
        classification = classify_move(
            analysis,
            is_book=est_theorique,
            config=config,
            previous=analyses[index - 1] if index else None,
        )
        classes.append(
            ClassifiedMove(
                analysis=analysis,
                classification=classification,
                accuracy=move_accuracy(analysis.win_prob_drop),
            )
        )

    def rapport(color: chess.Color) -> PlayerReport:
        coups = [m for m in classes if m.turn == color]
        # Les coups théoriques entrent dans la moyenne, comme chez chess.com :
        # les exclure faisait grimper le score de plusieurs points sur les
        # parties à longue ouverture connue.
        notes = [m.accuracy for m in coups]
        compte: dict[MoveClass, int] = {}
        for m in coups:
            compte[m.classification] = compte.get(m.classification, 0) + 1
        return PlayerReport(
            color=color,
            accuracy=round(sum(notes) / len(notes), 1) if notes else 100.0,
            counts=compte,
        )

    return GameReport(
        moves=classes,
        white=rapport(chess.WHITE),
        black=rapport(chess.BLACK),
    )
