"""Réglages de l'application.

Tout ce qui se configure est ici, réparti en quatre onglets. Les valeurs sont
conservées dans QSettings, sauf les identifiants de base de données qui sont
lus depuis .env en priorité : un mot de passe n'a rien à faire dans un fichier
de configuration versionnable ni dans le registre de l'utilisateur.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.database import DatabaseConfig, DatabaseError, GameRepository
from src.core.engine import EngineNotFound, find_stockfish
from src.ui.pieces import JEU_INTEGRE, installed_sets
from src.ui.style import ThemeMode
from src.ui.theme import THEMES

ORGANISATION = "chess-review"
APPLICATION = "chess-review"


class Settings:
    """Accès typé aux préférences. Une clé, un défaut, un seul endroit."""

    def __init__(self) -> None:
        self._s = QSettings(ORGANISATION, APPLICATION)

    # -- apparence --------------------------------------------------------

    @property
    def theme_mode(self) -> ThemeMode:
        try:
            return ThemeMode(self._s.value("ui/theme", "system", str))
        except ValueError:
            return ThemeMode.SYSTEM

    @theme_mode.setter
    def theme_mode(self, mode: ThemeMode) -> None:
        self._s.setValue("ui/theme", mode.value)

    @property
    def board_theme(self) -> str:
        return self._s.value("ui/board_theme", "green", str)

    @board_theme.setter
    def board_theme(self, cle: str) -> None:
        self._s.setValue("ui/board_theme", cle)

    @property
    def piece_set(self) -> str:
        return self._s.value("ui/piece_set", JEU_INTEGRE, str)

    @piece_set.setter
    def piece_set(self, cle: str) -> None:
        self._s.setValue("ui/piece_set", cle)

    @property
    def animations(self) -> bool:
        return self._s.value("ui/animations", True, bool)

    @animations.setter
    def animations(self, actif: bool) -> None:
        self._s.setValue("ui/animations", actif)

    @property
    def badges(self) -> bool:
        return self._s.value("ui/badges", True, bool)

    @badges.setter
    def badges(self, actif: bool) -> None:
        self._s.setValue("ui/badges", actif)

    # -- analyse ----------------------------------------------------------

    @property
    def depth(self) -> int:
        return int(self._s.value("engine/depth", 16))

    @depth.setter
    def depth(self, valeur: int) -> None:
        self._s.setValue("engine/depth", valeur)

    @property
    def threads(self) -> int:
        return int(self._s.value("engine/threads", 1))

    @threads.setter
    def threads(self, valeur: int) -> None:
        self._s.setValue("engine/threads", valeur)

    @property
    def hash_mb(self) -> int:
        return int(self._s.value("engine/hash", 128))

    @hash_mb.setter
    def hash_mb(self, valeur: int) -> None:
        self._s.setValue("engine/hash", valeur)

    @property
    def engine_path(self) -> str:
        return self._s.value("engine/path", "", str)

    @engine_path.setter
    def engine_path(self, chemin: str) -> None:
        self._s.setValue("engine/path", chemin)

    @property
    def detect_special(self) -> bool:
        return self._s.value("engine/detect_special", True, bool)

    @detect_special.setter
    def detect_special(self, actif: bool) -> None:
        self._s.setValue("engine/detect_special", actif)

    @property
    def autosave(self) -> bool:
        return self._s.value("db/autosave", True, bool)

    @autosave.setter
    def autosave(self, actif: bool) -> None:
        self._s.setValue("db/autosave", actif)

    # -- son --------------------------------------------------------------

    @property
    def sound_enabled(self) -> bool:
        return self._s.value("sound/enabled", True, bool)

    @sound_enabled.setter
    def sound_enabled(self, actif: bool) -> None:
        self._s.setValue("sound/enabled", actif)

    @property
    def volume(self) -> int:
        return int(self._s.value("sound/volume", 60))

    @volume.setter
    def volume(self, valeur: int) -> None:
        self._s.setValue("sound/volume", valeur)

    # -- base de données --------------------------------------------------

    def database_config(self) -> DatabaseConfig:
        """Les variables d'environnement priment sur les réglages stockés."""
        depuis_env = DatabaseConfig.from_env()
        if depuis_env.configured and os.environ.get("DB_USER"):
            return depuis_env
        return DatabaseConfig(
            host=self._s.value("db/host", "localhost", str),
            port=int(self._s.value("db/port", 3306)),
            database=self._s.value("db/name", "chess_review", str),
            user=self._s.value("db/user", "", str),
            password=self._s.value("db/password", "", str),
        )

    def set_database_config(self, config: DatabaseConfig) -> None:
        self._s.setValue("db/host", config.host)
        self._s.setValue("db/port", config.port)
        self._s.setValue("db/name", config.database)
        self._s.setValue("db/user", config.user)
        self._s.setValue("db/password", config.password)

    @property
    def db_from_env(self) -> bool:
        return bool(os.environ.get("DB_USER"))


class SettingsDialog(QDialog):
    """Quatre onglets : apparence, analyse, base de données, son."""

    applied = Signal()

    def __init__(self, settings: Settings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Réglages")
        self.setMinimumWidth(520)
        self._settings = settings
        self._build_ui()
        self._charger()

    # -- construction -----------------------------------------------------

    def _build_ui(self) -> None:
        onglets = QTabWidget()
        onglets.addTab(self._onglet_apparence(), "Apparence")
        onglets.addTab(self._onglet_analyse(), "Analyse")
        onglets.addTab(self._onglet_base(), "Base de données")
        onglets.addTab(self._onglet_son(), "Son")

        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply
        )
        boutons.accepted.connect(self._valider)
        boutons.rejected.connect(self.reject)
        boutons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(
            self._appliquer
        )
        boutons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primaire")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        layout.addWidget(onglets)
        layout.addWidget(boutons)

    def _onglet_apparence(self) -> QWidget:
        self.combo_theme = QComboBox()
        for mode in ThemeMode:
            self.combo_theme.addItem(mode.label, mode.value)

        self.combo_echiquier = QComboBox()
        for theme in THEMES:
            self.combo_echiquier.addItem(theme.name, theme.key)

        self.combo_pieces = QComboBox()
        for info in installed_sets():
            self.combo_pieces.addItem(f"{info.name}  ·  {info.license}", info.key)
        self.combo_pieces.setToolTip(
            "Ajoute d'autres jeux avec : python scripts/fetch_pieces.py"
        )

        self.check_animations = QCheckBox("Animer les coups et la jauge")
        self.check_badges = QCheckBox("Pastilles de qualité sur l'échiquier")

        formulaire = QFormLayout()
        formulaire.setSpacing(12)
        formulaire.addRow("Thème de l'application", self.combo_theme)
        formulaire.addRow("Couleurs de l'échiquier", self.combo_echiquier)
        formulaire.addRow("Jeu de pièces", self.combo_pieces)
        formulaire.addRow("", self.check_animations)
        formulaire.addRow("", self.check_badges)

        note = QLabel(
            "Le thème « Système » suit le réglage clair/sombre de ton bureau.\n"
            "Les jeux de pièces se téléchargent avec scripts/fetch_pieces.py ; "
            "vérifie leur licence si ton usage n'est pas personnel."
        )
        note.setObjectName("sousTitre")
        note.setWordWrap(True)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addLayout(formulaire)
        layout.addWidget(note)
        layout.addStretch()
        return page

    def _onglet_analyse(self) -> QWidget:
        self.spin_depth = QSpinBox()
        self.spin_depth.setRange(8, 28)
        self.spin_depth.setToolTip(
            "Le coût grimpe à peu près exponentiellement.\n"
            "16 relit une partie en quelques dizaines de secondes."
        )

        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, 32)
        self.spin_threads.setToolTip(
            "Nombre de cœurs alloués à Stockfish. Laisse-en au système."
        )

        self.spin_hash = QSpinBox()
        self.spin_hash.setRange(16, 4096)
        self.spin_hash.setSingleStep(64)
        self.spin_hash.setSuffix(" Mo")

        self.check_special = QCheckBox(
            "Badges Brillant, Trouvaille et Occasion manquée"
        )
        self.check_special.setToolTip(
            "Décoché, la classification se limite aux huit catégories de\n"
            "chess-game-review : meilleur, excellent, bon, théorique, forcé,\n"
            "imprécision, erreur, gaffe."
        )

        self.edit_moteur = QLineEdit()
        self.edit_moteur.setPlaceholderText("détection automatique")

        self.btn_detecter = QPushButton("Détecter")
        self.btn_detecter.clicked.connect(self._detecter_moteur)
        self.label_moteur = QLabel(" ")
        self.label_moteur.setObjectName("sousTitre")

        ligne_moteur = QHBoxLayout()
        ligne_moteur.addWidget(self.edit_moteur, stretch=1)
        ligne_moteur.addWidget(self.btn_detecter)

        formulaire = QFormLayout()
        formulaire.setSpacing(12)
        formulaire.addRow("Profondeur", self.spin_depth)
        formulaire.addRow("Threads", self.spin_threads)
        formulaire.addRow("Table de hachage", self.spin_hash)
        formulaire.addRow("", self.check_special)
        formulaire.addRow("Binaire Stockfish", ligne_moteur)
        formulaire.addRow("", self.label_moteur)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addLayout(formulaire)
        layout.addStretch()
        return page

    def _onglet_base(self) -> QWidget:
        self.edit_hote = QLineEdit()
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.edit_base = QLineEdit()
        self.edit_utilisateur = QLineEdit()
        self.edit_motdepasse = QLineEdit()
        self.edit_motdepasse.setEchoMode(QLineEdit.EchoMode.Password)

        self.check_autosave = QCheckBox(
            "Enregistrer automatiquement les parties et leurs analyses"
        )

        self.btn_tester = QPushButton("Tester la connexion")
        self.btn_tester.clicked.connect(self._tester_base)
        self.btn_creer = QPushButton("Créer les tables")
        self.btn_creer.clicked.connect(self._creer_tables)

        self.label_base = QLabel(" ")
        self.label_base.setObjectName("sousTitre")
        self.label_base.setWordWrap(True)

        ligne_boutons = QHBoxLayout()
        ligne_boutons.addWidget(self.btn_tester)
        ligne_boutons.addWidget(self.btn_creer)
        ligne_boutons.addStretch()

        formulaire = QFormLayout()
        formulaire.setSpacing(12)
        formulaire.addRow("Hôte", self.edit_hote)
        formulaire.addRow("Port", self.spin_port)
        formulaire.addRow("Base", self.edit_base)
        formulaire.addRow("Utilisateur", self.edit_utilisateur)
        formulaire.addRow("Mot de passe", self.edit_motdepasse)
        formulaire.addRow("", self.check_autosave)

        groupe = QGroupBox("Connexion MySQL")
        interne = QVBoxLayout(groupe)
        interne.addLayout(formulaire)
        interne.addLayout(ligne_boutons)
        interne.addWidget(self.label_base)

        self.note_env = QLabel(
            "Astuce : place DB_USER et DB_PASSWORD dans le fichier .env. "
            "Ils prendront le dessus sur ces champs, et resteront hors du dépôt."
        )
        self.note_env.setObjectName("sousTitre")
        self.note_env.setWordWrap(True)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(groupe)
        layout.addWidget(self.note_env)
        layout.addStretch()
        return page

    def _onglet_son(self) -> QWidget:
        self.check_son = QCheckBox("Activer les sons")
        self.slider_volume = QSlider(Qt.Orientation.Horizontal)
        self.slider_volume.setRange(0, 100)
        self.label_volume = QLabel("60 %")
        self.slider_volume.valueChanged.connect(
            lambda v: self.label_volume.setText(f"{v} %")
        )

        ligne = QHBoxLayout()
        ligne.addWidget(self.slider_volume, stretch=1)
        ligne.addWidget(self.label_volume)

        formulaire = QFormLayout()
        formulaire.setSpacing(12)
        formulaire.addRow("", self.check_son)
        formulaire.addRow("Volume", ligne)

        note = QLabel(
            "Les sons sont synthétisés par scripts/make_sounds.py. "
            "Tu peux remplacer les fichiers de assets/sounds/ par les tiens."
        )
        note.setObjectName("sousTitre")
        note.setWordWrap(True)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addLayout(formulaire)
        layout.addWidget(note)
        layout.addStretch()
        return page

    # -- chargement et sauvegarde -----------------------------------------

    def _charger(self) -> None:
        s = self._settings
        self.combo_theme.setCurrentIndex(
            max(0, self.combo_theme.findData(s.theme_mode.value))
        )
        self.combo_echiquier.setCurrentIndex(
            max(0, self.combo_echiquier.findData(s.board_theme))
        )
        self.combo_pieces.setCurrentIndex(
            max(0, self.combo_pieces.findData(s.piece_set))
        )
        self.check_animations.setChecked(s.animations)
        self.check_badges.setChecked(s.badges)

        self.spin_depth.setValue(s.depth)
        self.spin_threads.setValue(s.threads)
        self.spin_hash.setValue(s.hash_mb)
        self.edit_moteur.setText(s.engine_path)
        self.check_special.setChecked(s.detect_special)

        config = s.database_config()
        self.edit_hote.setText(config.host)
        self.spin_port.setValue(config.port)
        self.edit_base.setText(config.database)
        self.edit_utilisateur.setText(config.user)
        self.edit_motdepasse.setText(config.password)
        self.check_autosave.setChecked(s.autosave)

        if s.db_from_env:
            for champ in (
                self.edit_hote,
                self.spin_port,
                self.edit_base,
                self.edit_utilisateur,
                self.edit_motdepasse,
            ):
                champ.setEnabled(False)
            self.note_env.setText(
                "Ces champs sont fournis par le fichier .env et ne sont pas "
                "modifiables ici. Édite .env pour les changer."
            )

        self.check_son.setChecked(s.sound_enabled)
        self.slider_volume.setValue(s.volume)
        self.label_volume.setText(f"{s.volume} %")

    def _config_saisie(self) -> DatabaseConfig:
        return DatabaseConfig(
            host=self.edit_hote.text().strip() or "localhost",
            port=self.spin_port.value(),
            database=self.edit_base.text().strip(),
            user=self.edit_utilisateur.text().strip(),
            password=self.edit_motdepasse.text(),
        )

    def _appliquer(self) -> None:
        s = self._settings
        s.theme_mode = ThemeMode(self.combo_theme.currentData())
        s.board_theme = self.combo_echiquier.currentData()
        s.piece_set = self.combo_pieces.currentData() or JEU_INTEGRE
        s.animations = self.check_animations.isChecked()
        s.badges = self.check_badges.isChecked()

        s.depth = self.spin_depth.value()
        s.threads = self.spin_threads.value()
        s.hash_mb = self.spin_hash.value()
        s.engine_path = self.edit_moteur.text().strip()
        s.detect_special = self.check_special.isChecked()

        if not s.db_from_env:
            s.set_database_config(self._config_saisie())
        s.autosave = self.check_autosave.isChecked()

        s.sound_enabled = self.check_son.isChecked()
        s.volume = self.slider_volume.value()

        self.applied.emit()

    def _valider(self) -> None:
        self._appliquer()
        self.accept()

    # -- actions ----------------------------------------------------------

    def _detecter_moteur(self) -> None:
        try:
            chemin = find_stockfish(self.edit_moteur.text().strip() or None)
        except EngineNotFound as exc:
            self.label_moteur.setText(str(exc))
            return
        self.edit_moteur.setText(chemin)
        self.label_moteur.setText(f"Trouvé : {chemin}")

    def _depot(self) -> GameRepository:
        config = (
            self._settings.database_config()
            if self._settings.db_from_env
            else self._config_saisie()
        )
        return GameRepository(config.url)

    def _tester_base(self) -> None:
        self.label_base.setText("Connexion en cours…")
        try:
            depot = self._depot()
            depot.ping()
            stats = depot.stats()
            depot.dispose()
        except DatabaseError as exc:
            self.label_base.setText(f"Échec : {exc}")
            return
        except Exception as exc:
            self.label_base.setText(f"Échec : {exc}")
            return
        self.label_base.setText(
            f"Connexion réussie. {stats['games']} partie(s), "
            f"{stats['analyses']} analyse(s)."
        )

    def _creer_tables(self) -> None:
        try:
            depot = self._depot()
            depot.create_all()
            depot.dispose()
        except Exception as exc:
            self.label_base.setText(f"Échec : {exc}")
            return
        self.label_base.setText("Tables créées ou déjà présentes.")