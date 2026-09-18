"""Fenêtre principale.

Assemble l'échiquier, la feuille de partie et l'analyse. Aucune logique
d'échecs ici : tout vient de src/core.

Les animations sont faites en Python et non en CSS, Qt ne connaissant pas les
transitions : ouverture en fondu, compteurs de précision qui montent
progressivement, panneau de détail qui se réaffiche en fondu à chaque coup.
"""

from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import chess
import chess.engine
import chess.pgn
from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QVariantAnimation,
    Slot,
)
from PySide6.QtGui import QAction, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.core.classify import ClassifierConfig, MoveClass, classify_move
from src.core.database import DatabaseError, GameRepository
from src.core.engine import EngineConfig, Line, MoveAnalysis, PositionAnalysis
from src.core.navigation import GameNavigator
from src.core.openings import load_default
from src.ui.board_widget import COULEURS_BADGE, BoardWidget
from src.ui.captured_widget import CapturedWidget, apply_summary
from src.ui.eval_bar import EvalBar
from src.ui.fetch_dialog import ChessComDialog
from src.ui.library_dialog import LibraryDialog
from src.ui.live_analysis import LiveAnalyser, LiveEval
from src.ui.move_list import MoveListWidget
from src.ui.settings_dialog import Settings, SettingsDialog
from src.ui.sound import SoundPlayer
from src.ui.style import ThemeMode, apply_theme
from src.ui.worker import AnalysisController, AnalysisWorker

PARTIE_EXEMPLE = (
    "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Bxc6 dxc6 5. Nxe5 Qd4 6. Ng4 Qxe4+ "
    "7. Qe2 Qxe2+ 8. Kxe2 Bxg4+"
)


class PgnDialog(QDialog):
    """Petite boîte pour coller un PGN."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Coller un PGN")
        self.resize(540, 340)

        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(
            "Colle ici le PGN copié depuis chess.com ou lichess.org…"
        )
        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        boutons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primaire")
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(self.edit)
        layout.addWidget(boutons)

    def pgn(self) -> str:
        return self.edit.toPlainText().strip()


class CompteurAnime(QLabel):
    """Nombre qui monte jusqu'à sa valeur au lieu d'apparaître d'un coup."""

    def __init__(self, suffixe: str = " %", parent=None) -> None:
        super().__init__("—", parent)
        self.setObjectName("grandChiffre")
        self._suffixe = suffixe
        self._valeur = 0.0
        self._anime = True
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(600)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_value)

    def set_animate(self, actif: bool) -> None:
        self._anime = actif

    def set_value(self, valeur: float | None) -> None:
        self._animation.stop()
        if valeur is None:
            self._valeur = 0.0
            self.setText("—")
            return
        if not self._anime:
            self._valeur = valeur
            self._afficher(valeur)
            return
        self._animation.setStartValue(float(self._valeur))
        self._animation.setEndValue(float(valeur))
        self._animation.start()
        self._valeur = valeur

    def _on_value(self, valeur) -> None:
        self._afficher(float(valeur))

    def _afficher(self, valeur: float) -> None:
        self.setText(f"{valeur:.1f}{self._suffixe}")


def carte(titre: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    """Panneau arrondi réutilisable."""
    cadre = QFrame()
    cadre.setObjectName("carte")
    layout = QVBoxLayout(cadre)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(8)
    if titre:
        etiquette = QLabel(titre)
        etiquette.setObjectName("sousTitre")
        layout.addWidget(etiquette)
    return cadre, layout


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Chess Review")
        self.resize(1240, 800)

        self._settings = Settings()
        self._book = load_default()
        self._navigator = GameNavigator([])
        self._sound = SoundPlayer(parent=self)
        self._controller = AnalysisController(self)
        self._depot: GameRepository | None = None
        self._game_id: int | None = None
        self._book_plies = 0
        self._ply_precedent = 0

        # Mode exploration : coups joués à la main depuis une position de la
        # partie. La partie elle-même n'est jamais modifiée.
        self._explore_depuis: int | None = None
        self._explore_board = chess.Board()
        self._explore_coups: list[chess.Move] = []
        # Évaluation de la position affichée en exploration. Sert de point de
        # comparaison pour juger le coup suivant.
        self._eval_courante: LiveEval | None = None
        self._explore_avant: tuple[chess.Board, chess.Move, LiveEval] | None = None
        self._explore_dernier: chess.Move | None = None

        self._live = LiveAnalyser(self)
        self._live.result.connect(self._on_live_result)
        self._live.failed.connect(self._on_live_failed)

        self._controller.progress.connect(self._on_progress)
        self._controller.finished.connect(self._on_finished)
        self._controller.failed.connect(self._on_failed)
        self._controller.state_changed.connect(self._on_state_changed)

        self._build_ui()
        self._build_shortcuts()
        self._appliquer_reglages()
        self._connecter_base(silencieux=True)
        self.load_pgn(PARTIE_EXEMPLE)
        self._fondu_entree()

    # -- construction -----------------------------------------------------

    def _build_ui(self) -> None:
        self.board_widget = BoardWidget()
        self.board_widget.set_interactive(True)
        self.board_widget.move_played.connect(self._on_move_played)
        self.eval_bar = EvalBar()
        self.eval_bar.set_board(self.board_widget)

        self._build_toolbar()

        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.btn_debut = QPushButton("⏮")
        self.btn_precedent = QPushButton("◀")
        self.btn_suivant = QPushButton("▶")
        self.btn_fin = QPushButton("⏭")
        self.btn_faute_precedente = QPushButton("◀ Faute")
        self.btn_faute_suivante = QPushButton("Faute ▶")

        for bouton in (self.btn_debut, self.btn_precedent, self.btn_suivant, self.btn_fin):
            bouton.setObjectName("navigation")
            nav.addWidget(bouton)
        nav.addStretch()
        nav.addWidget(self.btn_faute_precedente)
        nav.addWidget(self.btn_faute_suivante)

        self.btn_debut.clicked.connect(lambda: self._goto(self._navigator.first()))
        self.btn_precedent.clicked.connect(lambda: self._goto(self._navigator.previous()))
        self.btn_suivant.clicked.connect(lambda: self._goto(self._navigator.next()))
        self.btn_fin.clicked.connect(lambda: self._goto(self._navigator.last()))
        self.btn_faute_precedente.clicked.connect(self._faute_precedente)
        self.btn_faute_suivante.clicked.connect(self._faute_suivante)

        self.captures_haut = CapturedWidget()
        self.captures_bas = CapturedWidget()

        plateau = QHBoxLayout()
        plateau.setSpacing(8)
        plateau.addWidget(self.eval_bar)
        plateau.addWidget(self.board_widget, stretch=1)

        # Les bandeaux sont alignés sur l'échiquier et non sur la jauge : ils
        # sont décalés de sa largeur plus l'espacement.
        marge = self.eval_bar.width() + 8

        colonne_plateau = QVBoxLayout()
        colonne_plateau.setSpacing(6)
        colonne_plateau.setContentsMargins(0, 0, 0, 0)
        for bandeau, position in ((self.captures_haut, 0), (None, 1), (self.captures_bas, 2)):
            if bandeau is None:
                colonne_plateau.addLayout(plateau, stretch=1)
                continue
            ligne = QHBoxLayout()
            ligne.setContentsMargins(marge, 0, 0, 0)
            ligne.addWidget(bandeau)
            colonne_plateau.addLayout(ligne)

        gauche = QWidget()
        layout_gauche = QVBoxLayout(gauche)
        layout_gauche.setContentsMargins(14, 14, 8, 14)
        layout_gauche.setSpacing(12)
        layout_gauche.addLayout(colonne_plateau, stretch=1)
        layout_gauche.addLayout(nav)

        droite = self._build_panneau_droit()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(gauche)
        splitter.addWidget(droite)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        self.setCentralWidget(splitter)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(200)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().showMessage("Prêt")

    def _build_toolbar(self) -> None:
        barre = self.addToolBar("Principal")
        barre.setMovable(False)

        def action(texte, slot, raccourci=None, infobulle=None):
            acte = QAction(texte, self)
            acte.triggered.connect(slot)
            if raccourci:
                acte.setShortcut(QKeySequence(raccourci))
            if infobulle:
                acte.setToolTip(infobulle)
            barre.addAction(acte)
            return acte

        self.action_ouvrir = action("Ouvrir", self._ouvrir_fichier, "Ctrl+O")
        self.action_coller = action("Coller", self._coller_pgn, "Ctrl+V")
        self.action_chesscom = action(
            "chess.com", self._ouvrir_chesscom, None, "Récupérer tes parties récentes"
        )
        self.action_bibliotheque = action(
            "Bibliothèque", self._ouvrir_bibliotheque, "Ctrl+L"
        )

        barre.addSeparator()
        self.action_analyser = action("Analyser", self._analyser, "Ctrl+R")
        self.action_annuler = action("Annuler", self._controller.cancel)
        self.action_annuler.setEnabled(False)

        barre.addSeparator()
        self.action_retourner = action("Retourner", self._retourner, "Ctrl+F")

        espace = QWidget()
        espace.setSizePolicy(
            espace.sizePolicy().horizontalPolicy().Expanding,
            espace.sizePolicy().verticalPolicy().Preferred,
        )
        barre.addWidget(espace)
        self.action_reglages = action("Réglages", self._ouvrir_reglages, "Ctrl+,")

    def _build_panneau_droit(self) -> QWidget:
        entete, layout_entete = carte()
        self.label_ouverture = QLabel("—")
        self.label_ouverture.setObjectName("titre")
        self.label_ouverture.setWordWrap(True)
        self.label_joueurs = QLabel("—")
        self.label_joueurs.setObjectName("sousTitre")
        self.label_joueurs.setWordWrap(True)
        layout_entete.addWidget(self.label_ouverture)
        layout_entete.addWidget(self.label_joueurs)

        precision, layout_precision = carte()
        self.compteur_blancs = CompteurAnime()
        self.compteur_noirs = CompteurAnime()

        colonne_blancs = QVBoxLayout()
        titre_blancs = QLabel("Blancs")
        titre_blancs.setObjectName("sousTitre")
        colonne_blancs.addWidget(titre_blancs)
        colonne_blancs.addWidget(self.compteur_blancs)

        colonne_noirs = QVBoxLayout()
        titre_noirs = QLabel("Noirs")
        titre_noirs.setObjectName("sousTitre")
        colonne_noirs.addWidget(titre_noirs)
        colonne_noirs.addWidget(self.compteur_noirs)

        ligne_precision = QHBoxLayout()
        ligne_precision.addLayout(colonne_blancs)
        ligne_precision.addStretch()
        ligne_precision.addLayout(colonne_noirs)
        layout_precision.addLayout(ligne_precision)

        self.liste_coups = MoveListWidget()
        self.liste_coups.ply_selected.connect(self._goto)

        self.bandeau, layout_bandeau = carte()
        self.label_exploration = QLabel("—")
        self.label_exploration.setWordWrap(True)
        self.btn_retour_partie = QPushButton("Revenir à la partie")
        self.btn_retour_partie.setObjectName("primaire")
        self.btn_retour_partie.clicked.connect(self._quitter_exploration)
        self.btn_annuler_coup = QPushButton("Annuler le coup")
        self.btn_annuler_coup.clicked.connect(self._annuler_coup_explore)

        ligne_bandeau = QHBoxLayout()
        ligne_bandeau.addWidget(self.btn_annuler_coup)
        ligne_bandeau.addWidget(self.btn_retour_partie)
        layout_bandeau.addWidget(self.label_exploration)
        layout_bandeau.addLayout(ligne_bandeau)
        self.bandeau.setVisible(False)

        detail, layout_detail = carte()
        self.label_detail = QLabel(" ")
        self.label_detail.setWordWrap(True)
        self.label_detail.setMinimumHeight(76)
        self.label_detail.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._effet_detail = QGraphicsOpacityEffect(self.label_detail)
        self.label_detail.setGraphicsEffect(self._effet_detail)
        self._effet_detail.setOpacity(1.0)
        self._fondu_detail = QPropertyAnimation(self._effet_detail, b"opacity", self)
        self._fondu_detail.setDuration(180)
        self._fondu_detail.setEasingCurve(QEasingCurve.Type.OutCubic)
        layout_detail.addWidget(self.label_detail)

        droite = QWidget()
        layout = QVBoxLayout(droite)
        layout.setContentsMargins(8, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(entete)
        layout.addWidget(precision)
        layout.addWidget(self.liste_coups, stretch=1)
        layout.addWidget(self.bandeau)
        layout.addWidget(detail)
        return droite

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=self.btn_precedent.click)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=self.btn_suivant.click)
        QShortcut(QKeySequence(Qt.Key.Key_Home), self, activated=self.btn_debut.click)
        QShortcut(QKeySequence(Qt.Key.Key_End), self, activated=self.btn_fin.click)
        QShortcut(QKeySequence(Qt.Key.Key_Down), self, activated=self._faute_suivante)
        QShortcut(QKeySequence(Qt.Key.Key_Up), self, activated=self._faute_precedente)
        QShortcut(
            QKeySequence(Qt.Key.Key_Escape), self, activated=self._quitter_exploration
        )

    def _fondu_entree(self) -> None:
        if not self._settings.animations:
            return
        effet = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effet)
        self._entree = QPropertyAnimation(effet, b"opacity", self)
        self._entree.setDuration(320)
        self._entree.setStartValue(0.0)
        self._entree.setEndValue(1.0)
        self._entree.setEasingCurve(QEasingCurve.Type.OutCubic)
        # L'effet est retiré à la fin : le garder coûte un rendu hors écran
        # permanent, ce qui ralentit tout le reste de la session.
        self._entree.finished.connect(lambda: self.setGraphicsEffect(None))
        self._entree.start()

    # -- réglages ---------------------------------------------------------

    def _appliquer_reglages(self) -> None:
        s = self._settings
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, s.theme_mode)

        self.board_widget.set_theme(s.board_theme)
        self.board_widget.set_animate(s.animations)
        self.board_widget.set_show_badges(s.badges)
        self.eval_bar.set_animate(s.animations)
        self.compteur_blancs.set_animate(s.animations)
        self.compteur_noirs.set_animate(s.animations)

        self._sound.set_enabled(s.sound_enabled and self._sound.available)
        self._sound.set_volume(s.volume / 100.0)

        self._demarrer_live()

    def _demarrer_live(self) -> None:
        """Moteur d'analyse continue, distinct de celui qui relit la partie.

        Profondeur volontairement plus faible : il doit répondre en une
        fraction de seconde à chaque coup joué, pas produire un verdict.
        """
        s = self._settings
        self._live.start(
            engine_path=s.engine_path or None,
            config=EngineConfig(
                depth=max(8, min(s.depth, 18)),
                threads=s.threads,
                hash_mb=min(s.hash_mb, 256),
                multipv=1,
            ),
        )

    def _ouvrir_reglages(self) -> None:
        dialogue = SettingsDialog(self._settings, self)
        dialogue.applied.connect(self._appliquer_reglages)
        dialogue.applied.connect(lambda: self._connecter_base(silencieux=True))
        dialogue.exec()

    # -- base de données --------------------------------------------------

    def _connecter_base(self, silencieux: bool = False) -> None:
        config = self._settings.database_config()
        if self._depot is not None:
            self._depot.dispose()
            self._depot = None

        if not config.configured:
            self.action_bibliotheque.setEnabled(False)
            if not silencieux:
                self.statusBar().showMessage(
                    "Base non configurée — voir Réglages.", 6000
                )
            return

        try:
            depot = GameRepository(config.url)
            depot.create_all()
        except DatabaseError as exc:
            self._depot = None
            self.action_bibliotheque.setEnabled(False)
            if not silencieux:
                QMessageBox.warning(self, "Base de données", str(exc))
            else:
                self.statusBar().showMessage(f"Base indisponible : {exc}", 8000)
            return

        self._depot = depot
        self.action_bibliotheque.setEnabled(True)

    def _sauver_partie(self, game: chess.pgn.Game, pgn: str, **extra) -> None:
        """Enregistre la partie courante, si la base est là et l'option active."""
        if self._depot is None or not self._settings.autosave:
            return
        entetes = game.headers
        date = None
        brut = entetes.get("Date", "").replace(".", "-")
        try:
            date = datetime.strptime(brut, "%Y-%m-%d")
        except ValueError:
            date = None
        try:
            self._game_id = self._depot.save_game(
                pgn,
                white=entetes.get("White", "?"),
                black=entetes.get("Black", "?"),
                white_rating=int(entetes.get("WhiteElo", 0) or 0),
                black_rating=int(entetes.get("BlackElo", 0) or 0),
                result=entetes.get("Result", "*"),
                played_at=date,
                eco=self._eco,
                opening=self._opening_name,
                **extra,
            )
        except (DatabaseError, ValueError) as exc:
            self.statusBar().showMessage(f"Enregistrement impossible : {exc}", 6000)

    def _ouvrir_bibliotheque(self) -> None:
        if self._depot is None:
            return
        dialogue = LibraryDialog(self._depot, self)
        if dialogue.exec() != QDialog.DialogCode.Accepted:
            return
        identifiant = dialogue.selected_id()
        if identifiant is None:
            return

        partie = self._depot.get_game(identifiant)
        if partie is None or not self.load_pgn(partie.pgn, persist=False):
            return
        self._game_id = identifiant

        rapport = self._depot.latest_report(identifiant)
        if rapport is not None:
            self._appliquer_rapport(rapport)
            self.statusBar().showMessage("Analyse restaurée depuis la base.", 6000)
        else:
            self.statusBar().showMessage(
                "Partie chargée. Clique sur Analyser (Ctrl+R).", 6000
            )

    # -- chargement -------------------------------------------------------

    def load_pgn(self, texte: str, persist: bool = True) -> bool:
        game = chess.pgn.read_game(io.StringIO(texte))
        if game is None or not list(game.mainline_moves()):
            QMessageBox.warning(
                self, "PGN illisible", "Aucun coup n'a pu être lu dans ce PGN."
            )
            return False

        self._navigator = GameNavigator.from_pgn(game)
        self._game_id = None
        self._ply_precedent = 0

        plies, ouverture = self._book.walk(self._navigator.moves, game.board())
        self._book_plies = plies
        self._eco = ouverture.eco if ouverture else ""
        self._opening_name = ouverture.name if ouverture else ""
        self.label_ouverture.setText(
            str(ouverture) if ouverture else "Ouverture non identifiée"
        )

        entetes = game.headers
        blanc, noir = entetes.get("White", "?"), entetes.get("Black", "?")
        self.label_joueurs.setText(
            f"{blanc} — {noir}   ·   {entetes.get('Result', '*')}"
        )
        self.setWindowTitle(f"Chess Review — {blanc} vs {noir}")

        self._nom_blanc = blanc
        self._nom_noir = noir
        self._elo_blanc = int(entetes.get("WhiteElo", 0) or 0)
        self._elo_noir = int(entetes.get("BlackElo", 0) or 0)
        self._maj_noms_joueurs()

        self.compteur_blancs.set_value(None)
        self.compteur_noirs.set_value(None)
        self.eval_bar.set_evaluation(None)
        self.liste_coups.populate(self._navigator.moves, None)
        self._goto(0)

        if persist:
            self._sauver_partie(game, texte)
        return True

    def _appliquer_rapport(self, report) -> None:
        self._navigator.attach_report(report)
        self.liste_coups.populate(self._navigator.moves, report)
        self.compteur_blancs.set_value(report.white.accuracy)
        self.compteur_noirs.set_value(report.black.accuracy)
        self._goto(self._navigator.ply)

    # -- navigation -------------------------------------------------------

    def _goto(self, ply: int) -> None:
        if self._en_exploration:
            # Naviguer dans la partie met fin à la variante en cours.
            self._explore_depuis = None
            self._explore_coups = []
            self._explore_avant = None
            self._eval_courante = None
            self.bandeau.setVisible(False)

        precedent = self._ply_precedent
        self._navigator.goto(ply)
        ply = self._navigator.ply
        self._ply_precedent = ply
        coup = self._navigator.current

        meilleur = None
        if coup is not None:
            ligne = coup.analysis.before.best
            meilleur = ligne.move if ligne else None

        self.board_widget.set_position(
            self._navigator.board,
            lastmove=self._navigator.last_move,
            best_move=meilleur,
            classification=coup.classification if coup else None,
            animate=(ply == precedent + 1 and ply > 0),
        )

        if coup is None:
            self.eval_bar.set_evaluation(None)
        else:
            self.eval_bar.set_evaluation(
                coup.analysis.after.cp_white, coup.analysis.after.mate_white
            )

        self.liste_coups.select_ply(ply)
        self._maj_captures(self._navigator.board)

        self.btn_precedent.setEnabled(self._navigator.can_go_back)
        self.btn_debut.setEnabled(self._navigator.can_go_back)
        self.btn_suivant.setEnabled(self._navigator.can_go_forward)
        self.btn_fin.setEnabled(self._navigator.can_go_forward)

        self._maj_detail(coup)

        if ply > 0 and ply != precedent:
            self._sound.play_move(
                self._navigator.board_at(ply - 1),
                self._navigator.moves[ply - 1],
                self._navigator.board,
                coup.classification if coup else None,
            )

    def _maj_detail(self, coup) -> None:
        if coup is None:
            self._ecrire_detail(" ")
            return

        analyse = coup.analysis
        classification = coup.classification
        couleur = COULEURS_BADGE[classification]
        lignes = [
            f"<span style='color:{couleur};font-size:15px;font-weight:700'>"
            f"{classification.symbol or '•'} {classification.label}</span>"
            f"<span style='color:#8D94A0'>  ·  précision {coup.accuracy:.0f} %</span>"
        ]
        if classification is not MoveClass.BOOK:
            if not analyse.is_best and analyse.best_san:
                lignes.append(f"Le moteur préférait <b>{analyse.best_san}</b>.")
            mat = analyse.mate_for_mover
            if mat is not None:
                lignes.append(f"Mat annoncé en {abs(mat)}.")
            else:
                lignes.append(
                    f"Évaluation : {analyse.cp_before / 100:+.2f} → "
                    f"{analyse.cp_after / 100:+.2f}"
                    f"<span style='color:#8D94A0'>  (perte "
                    f"{analyse.centipawn_loss} cp)</span>"
                )
        self._ecrire_detail("<br>".join(lignes))

    def _ecrire_detail(self, html: str) -> None:
        self.label_detail.setText(html)
        if not self._settings.animations:
            return
        self._fondu_detail.stop()
        self._fondu_detail.setStartValue(0.35)
        self._fondu_detail.setEndValue(1.0)
        self._fondu_detail.start()

    def _faute_suivante(self) -> None:
        if self._navigator.next_mistake() is None:
            self.statusBar().showMessage("Plus de faute après ce coup", 3000)
        else:
            self._goto(self._navigator.ply)

    def _faute_precedente(self) -> None:
        if self._navigator.previous_mistake() is None:
            self.statusBar().showMessage("Aucune faute avant ce coup", 3000)
        else:
            self._goto(self._navigator.ply)

    def _maj_noms_joueurs(self) -> None:
        """Place chaque joueur du bon côté selon l'orientation."""
        blanc = (getattr(self, "_nom_blanc", "?"), getattr(self, "_elo_blanc", 0))
        noir = (getattr(self, "_nom_noir", "?"), getattr(self, "_elo_noir", 0))
        if self.board_widget.flipped:
            self.captures_haut.set_player(*blanc)
            self.captures_bas.set_player(*noir)
        else:
            self.captures_haut.set_player(*noir)
            self.captures_bas.set_player(*blanc)

    def _maj_captures(self, board: chess.Board) -> None:
        apply_summary(
            self.captures_haut,
            self.captures_bas,
            board,
            self.board_widget.flipped,
        )

    def _retourner(self) -> None:
        self.board_widget.flip()
        self.eval_bar.set_flipped(self.board_widget.flipped)
        self._maj_noms_joueurs()
        self._maj_captures(
            self._explore_board if self._en_exploration else self._navigator.board
        )

    # -- exploration ------------------------------------------------------

    @property
    def _en_exploration(self) -> bool:
        return self._explore_depuis is not None

    def _eval_de_la_partie(self) -> LiveEval | None:
        """Évaluation de la position courante telle que l'analyse l'a établie.

        Permet de juger le tout premier coup d'une variante sans relancer le
        moteur sur la position de départ.
        """
        coup = self._navigator.current
        if coup is None:
            return None
        apres = coup.analysis.after
        meilleur = apres.best
        return LiveEval(
            fen=self._navigator.board.fen(),
            cp_white=apres.cp_white,
            mate_white=apres.mate_white,
            best_san=meilleur.san if meilleur else "",
            best_uci=meilleur.move.uci() if meilleur else "",
            pv_san="",
            depth=apres.depth,
        )

    @Slot(object)
    def _on_move_played(self, move: chess.Move) -> None:
        """Un coup joué à la souris ouvre ou prolonge une variante."""
        if not self._en_exploration:
            self._explore_depuis = self._navigator.ply
            self._explore_board = self._navigator.board
            self._explore_coups = []
            self._eval_courante = self._eval_de_la_partie()

        avant = self._explore_board.copy()
        if move not in self._explore_board.legal_moves:
            return

        # Mémorisé avant de pousser : c'est ce couple qui permettra de juger
        # le coup quand l'évaluation de la nouvelle position arrivera.
        self._explore_avant = (
            (avant, move, self._eval_courante) if self._eval_courante else None
        )

        self._explore_board.push(move)
        self._explore_coups.append(move)

        self._sound.play_move(avant, move, self._explore_board, None)
        self._afficher_exploration(dernier=move, animer=True)

    def _annuler_coup_explore(self) -> None:
        if not self._en_exploration or not self._explore_coups:
            return
        self._explore_board.pop()
        self._explore_coups.pop()
        self._explore_avant = None
        self._eval_courante = None
        if not self._explore_coups:
            self._quitter_exploration()
            return
        self._afficher_exploration(dernier=self._explore_coups[-1], animer=False)
        self._live.request(self._explore_board)

    def _quitter_exploration(self) -> None:
        if not self._en_exploration:
            return
        retour = self._explore_depuis or 0
        self._explore_depuis = None
        self._explore_coups = []
        self._explore_avant = None
        self._eval_courante = None
        self._explore_dernier = None
        self._ply_precedent = retour
        self.bandeau.setVisible(False)
        self.board_widget.set_position(
            self._navigator.board_at(retour),
            lastmove=None,
            animate=False,
        )
        self._goto(retour)

    def _afficher_exploration(self, dernier: chess.Move | None, animer: bool) -> None:
        self.bandeau.setVisible(True)
        self.btn_annuler_coup.setEnabled(bool(self._explore_coups))

        depart = self._navigator.board_at(self._explore_depuis or 0)
        try:
            variante = depart.variation_san(self._explore_coups)
        except ValueError:
            variante = " ".join(c.uci() for c in self._explore_coups)
        self.label_exploration.setText(
            f"<b>Exploration</b> depuis le demi-coup {self._explore_depuis}<br>{variante}"
        )

        self._explore_dernier = dernier
        self._maj_captures(self._explore_board)
        self.board_widget.set_position(
            self._explore_board, lastmove=dernier, animate=animer
        )
        self.liste_coups.select_ply(0)
        self._ecrire_detail("Analyse en cours…")
        self._live.request(self._explore_board)

    @staticmethod
    def _position_depuis_eval(
        fen: str, evaluation: LiveEval, board: chess.Board
    ) -> PositionAnalysis:
        """Enveloppe une évaluation live dans la structure attendue par classify.

        Deux variantes identiques sont déclarées : une seule ferait passer la
        position pour un coup forcé. En contrepartie, l'écart entre variantes
        est nul, donc les badges « Trouvaille » et « Brillant » ne peuvent pas
        sortir en exploration — ils demandent une comparaison que le moteur
        continu ne calcule pas.
        """
        score = (
            chess.engine.Mate(evaluation.mate_white)
            if evaluation.mate_white is not None
            else chess.engine.Cp(evaluation.cp_white)
        )
        lignes: list[Line] = []
        if evaluation.best_uci:
            coup = chess.Move.from_uci(evaluation.best_uci)
            ligne = Line(
                move=coup, san=evaluation.best_san, score_white=score, pv=[coup]
            )
            lignes = [ligne, ligne]
        return PositionAnalysis(
            fen=fen, turn=board.turn, lines=lignes, depth=evaluation.depth
        )

    def _juger_coup_explore(
        self, evaluation: LiveEval
    ) -> tuple[MoveClass | None, str, chess.Move | None]:
        """Verdict sur le dernier coup joué à la main.

        Rend le badge, le texte HTML et le coup que le moteur recommandait —
        les trois servent, le badge et le coup allant sur l'échiquier.
        """
        if self._explore_avant is None:
            return None, "", None
        board_avant, move, eval_avant = self._explore_avant

        avant = self._position_depuis_eval(eval_avant.fen, eval_avant, board_avant)
        apres_board = board_avant.copy()
        apres_board.push(move)
        apres = self._position_depuis_eval(evaluation.fen, evaluation, apres_board)
        if not avant.lines or not apres.lines:
            return None, "", None

        analyse = MoveAnalysis(
            ply=0,
            move_number=board_avant.fullmove_number,
            turn=board_avant.turn,
            move=move,
            san=board_avant.san(move),
            fen_before=eval_avant.fen,
            before=avant,
            after=apres,
        )
        classification = classify_move(analyse, config=ClassifierConfig())
        couleur = COULEURS_BADGE[classification]

        verdict = (
            f"<span style='color:{couleur};font-size:15px;font-weight:700'>"
            f"{classification.symbol or '•'} {analyse.san} — {classification.label}"
            f"</span>"
        )
        if not analyse.is_best and eval_avant.best_san:
            verdict += (
                f"<br><span style='color:#8D94A0'>Le moteur préférait</span> "
                f"<b>{eval_avant.best_san}</b>"
                f"<span style='color:#8D94A0'>  ·  perte "
                f"{analyse.centipawn_loss} cp</span>"
            )

        recommande = (
            chess.Move.from_uci(eval_avant.best_uci) if eval_avant.best_uci else None
        )
        return classification, verdict, recommande

    @Slot(object)
    def _on_live_result(self, evaluation: LiveEval) -> None:
        """Résultat du moteur continu. Ignoré si on a quitté l'exploration."""
        if not self._en_exploration or evaluation.fen != self._explore_board.fen():
            return

        self.eval_bar.set_evaluation(evaluation.cp_white, evaluation.mate_white)

        lignes = []
        classification, verdict, recommande = self._juger_coup_explore(evaluation)
        if verdict:
            lignes.append(verdict)

        # Sans verdict (variante partie d'une position non analysée), on montre
        # au moins le meilleur coup depuis la position actuelle.
        if recommande is None and evaluation.best_uci:
            recommande = chess.Move.from_uci(evaluation.best_uci)

        # Redessin sans animation : la pièce a déjà glissé, il ne s'agit que
        # d'ajouter la flèche et la pastille maintenant qu'on sait quoi afficher.
        self.board_widget.set_position(
            self._explore_board,
            lastmove=self._explore_dernier,
            best_move=recommande,
            classification=classification,
            animate=False,
        )

        lignes.append(
            "<span style='color:#8D94A0'>Évaluation</span> "
            f"<b>{evaluation.texte}</b>"
            f"<span style='color:#8D94A0'>  ·  profondeur {evaluation.depth}</span>"
        )
        if evaluation.pv_san:
            lignes.append(
                f"<span style='color:#8D94A0'>Suite :</span> {evaluation.pv_san}"
            )
        self._ecrire_detail("<br>".join(lignes))

        # Devient la référence pour juger le coup suivant de la variante.
        self._eval_courante = evaluation

    @Slot(str)
    def _on_live_failed(self, message: str) -> None:
        self.statusBar().showMessage(f"Analyse continue indisponible : {message}", 8000)

    # -- import -----------------------------------------------------------

    def _ouvrir_fichier(self) -> None:
        chemin, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un PGN", str(Path.home()), "Parties (*.pgn);;Tous (*)"
        )
        if chemin:
            self.load_pgn(Path(chemin).read_text(encoding="utf-8", errors="replace"))

    def _coller_pgn(self) -> None:
        dialogue = PgnDialog(self)
        if dialogue.exec() == QDialog.DialogCode.Accepted and dialogue.pgn():
            self.load_pgn(dialogue.pgn())

    def _ouvrir_chesscom(self) -> None:
        dialogue = ChessComDialog(self)
        if dialogue.exec() != QDialog.DialogCode.Accepted:
            return
        partie = dialogue.selected_game()
        if partie is None or not partie.pgn:
            return

        if not self.load_pgn(partie.pgn, persist=False):
            return

        game = chess.pgn.read_game(io.StringIO(partie.pgn))
        self._sauver_partie(
            game,
            partie.pgn,
            source="chess.com",
            source_url=partie.url or None,
            time_class=partie.time_class,
        )

        couleur = dialogue.selected_color()
        if couleur is not None:
            self.board_widget.set_orientation(couleur)
            self.eval_bar.set_flipped(self.board_widget.flipped)
            self._maj_noms_joueurs()
            self._maj_captures(self._navigator.board)
        self.statusBar().showMessage("Partie chargée. Analyser avec Ctrl+R.", 6000)

    # -- analyse ----------------------------------------------------------

    def _analyser(self) -> None:
        if self._controller.running or not len(self._navigator):
            return
        s = self._settings
        worker = AnalysisWorker(
            moves=self._navigator.moves,
            root_board=chess.Board(),
            engine_config=EngineConfig(
                depth=s.depth, threads=s.threads, hash_mb=s.hash_mb, multipv=2
            ),
            book_plies=self._book_plies,
            engine_path=s.engine_path or None,
        )
        self._controller.start(worker)

    @Slot(int, int)
    def _on_progress(self, fait: int, total: int) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(fait)
        self.statusBar().showMessage(f"Analyse en cours… {fait}/{total}")

    @Slot(object)
    def _on_finished(self, report) -> None:
        self._appliquer_rapport(report)
        fautes = len(report.mistakes())
        message = f"Analyse terminée — {fautes} coup(s) à revoir"

        if self._depot is not None and self._game_id is not None and self._settings.autosave:
            try:
                self._depot.save_analysis(
                    self._game_id,
                    report,
                    depth=self._settings.depth,
                    book_plies=self._book_plies,
                )
                message += " · enregistrée"
            except DatabaseError as exc:
                message += f" · non enregistrée ({exc})"

        self.statusBar().showMessage(message, 10000)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.statusBar().showMessage("Analyse interrompue", 5000)
        QMessageBox.critical(
            self,
            "Échec de l'analyse",
            f"{message}\n\nSi Stockfish est introuvable, indique son chemin "
            "dans Réglages → Analyse.",
        )

    @Slot(bool)
    def _on_state_changed(self, en_cours: bool) -> None:
        for action in (
            self.action_analyser,
            self.action_ouvrir,
            self.action_coller,
            self.action_chesscom,
            self.action_bibliotheque,
        ):
            action.setEnabled(not en_cours)
        if not en_cours and self._depot is None:
            self.action_bibliotheque.setEnabled(False)
        self.action_annuler.setEnabled(en_cours)
        self.progress.setVisible(en_cours)
        if not en_cours:
            self.statusBar().showMessage("Prêt", 3000)

    # -- fermeture --------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._live.stop()
        if self._controller.running:
            self._controller.cancel()
            self._controller.wait()
        if self._depot is not None:
            self._depot.dispose()
        super().closeEvent(event)


def run(pgn_path: str | None = None) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Chess Review")
    app.setApplicationDisplayName("Chess Review")
    apply_theme(app, ThemeMode.SYSTEM)

    fenetre = MainWindow()
    if pgn_path:
        chemin = Path(pgn_path).expanduser()
        if chemin.is_file():
            fenetre.load_pgn(chemin.read_text(encoding="utf-8", errors="replace"))
        else:
            fenetre.statusBar().showMessage(f"Fichier introuvable : {chemin}", 8000)

    fenetre.show()
    return app.exec()