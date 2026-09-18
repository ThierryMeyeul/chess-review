"""Apparence de l'application.

Une seule source de vérité pour les couleurs : la palette. La feuille de style
est générée à partir d'elle, ce qui évite les codes hexadécimaux éparpillés
dans l'interface et rend un nouveau thème trivial à ajouter.

Qt ne gère pas les transitions CSS. Les animations visibles dans
l'application sont donc toutes faites en Python, avec QPropertyAnimation —
voir board_widget, eval_bar et main_window.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette


class ThemeMode(Enum):
    SYSTEM = "system"
    DARK = "dark"
    LIGHT = "light"

    @property
    def label(self) -> str:
        return {"system": "Système", "dark": "Sombre", "light": "Clair"}[self.value]


@dataclass(frozen=True)
class Palette:
    """Jeu de couleurs complet de l'interface."""

    nom: str
    fond: str            # fond de fenêtre
    surface: str         # panneaux
    surface_haute: str   # champs, éléments surélevés
    bordure: str
    texte: str
    texte_faible: str
    accent: str
    accent_texte: str
    survol: str
    selection: str
    ombre: str

    # Badges, repris de board_widget pour rester cohérents
    succes: str = "#95BB4A"
    alerte: str = "#F7C631"
    danger: str = "#FA412D"


SOMBRE = Palette(
    nom="dark",
    fond="#14161A",
    surface="#1B1E24",
    surface_haute="#23272F",
    bordure="#2E333C",
    texte="#E7E9EC",
    texte_faible="#8D94A0",
    accent="#7FA650",
    accent_texte="#10140C",
    survol="#2A2F38",
    selection="#33404A",
    ombre="#00000066",
)

CLAIR = Palette(
    nom="light",
    fond="#F4F5F7",
    surface="#FFFFFF",
    surface_haute="#FAFBFC",
    bordure="#DDE1E6",
    texte="#1C2026",
    texte_faible="#6B7280",
    accent="#5E8C31",
    accent_texte="#FFFFFF",
    survol="#EDEFF2",
    selection="#DCE7CE",
    ombre="#00000018",
)


def systeme_est_sombre() -> bool:
    """Détecte le thème du système.

    Qt 6.5 expose colorScheme() ; en dessous, on déduit du fond de la palette.
    """
    try:
        style_hints = QGuiApplication.styleHints()
        scheme = style_hints.colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except (AttributeError, TypeError):
        pass

    palette = QGuiApplication.palette()
    fond = palette.color(QPalette.ColorRole.Window)
    return fond.lightness() < 128


def resolve(mode: ThemeMode) -> Palette:
    if mode is ThemeMode.DARK:
        return SOMBRE
    if mode is ThemeMode.LIGHT:
        return CLAIR
    return SOMBRE if systeme_est_sombre() else CLAIR


def _melange(couleur: str, vers: str, facteur: float) -> str:
    """Interpolation entre deux couleurs, pour les états intermédiaires."""
    a, b = QColor(couleur), QColor(vers)
    return QColor(
        int(a.red() + (b.red() - a.red()) * facteur),
        int(a.green() + (b.green() - a.green()) * facteur),
        int(a.blue() + (b.blue() - a.blue()) * facteur),
    ).name()


def stylesheet(p: Palette) -> str:
    """Feuille de style complète de l'application."""
    accent_survol = _melange(p.accent, "#FFFFFF", 0.18)
    accent_presse = _melange(p.accent, "#000000", 0.18)

    return f"""
* {{
    outline: 0;
}}

QWidget {{
    background-color: {p.fond};
    color: {p.texte};
    font-size: 13px;
}}

QLabel {{
    background: transparent;
}}

QMainWindow, QDialog {{
    background-color: {p.fond};
}}

/* ---------- Barre d'outils ---------- */

QToolBar {{
    background-color: {p.surface};
    border: none;
    border-bottom: 1px solid {p.bordure};
    padding: 6px 10px;
    spacing: 4px;
}}

QToolBar QToolButton {{
    background-color: transparent;
    color: {p.texte};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 7px 13px;
    font-weight: 500;
}}

QToolBar QToolButton:hover {{
    background-color: {p.survol};
    border-color: {p.bordure};
}}

QToolBar QToolButton:pressed {{
    background-color: {p.selection};
}}

QToolBar QToolButton:disabled {{
    color: {p.texte_faible};
}}

QToolBar::separator {{
    background-color: {p.bordure};
    width: 1px;
    margin: 6px 8px;
}}

/* ---------- Panneaux ---------- */

QFrame#carte {{
    background-color: {p.surface};
    border: 1px solid {p.bordure};
    border-radius: 14px;
}}

QLabel#titre {{
    font-size: 15px;
    font-weight: 600;
    color: {p.texte};
}}

QLabel#sousTitre {{
    color: {p.texte_faible};
    font-size: 12px;
}}

QLabel#grandChiffre {{
    font-size: 30px;
    font-weight: 700;
    letter-spacing: -0.5px;
}}

QLabel#sousTitre {{
    letter-spacing: 0.4px;
}}

QLabel#chipEval {{
    background-color: {p.surface_haute};
    border: 1px solid {p.bordure};
    border-radius: 6px;
    padding: 2px 0;
}}

/* ---------- Champs ---------- */

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background-color: {p.surface_haute};
    border: 1px solid {p.bordure};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {p.accent};
    selection-color: {p.accent_texte};
}}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border-color: {p.accent};
}}

QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled {{
    color: {p.texte_faible};
    background-color: {p.fond};
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox QAbstractItemView {{
    background-color: {p.surface_haute};
    border: 1px solid {p.bordure};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {p.selection};
}}

QSpinBox::up-button, QSpinBox::down-button {{
    width: 16px;
    background-color: transparent;
    border: none;
}}

/* ---------- Boutons ---------- */

QPushButton {{
    background-color: {p.surface_haute};
    color: {p.texte};
    border: 1px solid {p.bordure};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 500;
}}

QPushButton:hover {{
    background-color: {p.survol};
}}

QPushButton:pressed {{
    background-color: {p.selection};
}}

QPushButton:disabled {{
    color: {p.texte_faible};
    background-color: {p.fond};
}}

QPushButton#primaire {{
    background-color: {p.accent};
    color: {p.accent_texte};
    border: none;
    font-weight: 600;
    padding: 8px 18px;
}}

QPushButton#primaire:hover {{
    background-color: {accent_survol};
}}

QPushButton#primaire:pressed {{
    background-color: {accent_presse};
}}

QPushButton#navigation {{
    padding: 6px 10px;
    font-size: 14px;
    min-width: 38px;
}}

/* ---------- Cases à cocher ---------- */

QCheckBox {{
    spacing: 8px;
    background: transparent;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1px solid {p.bordure};
    background-color: {p.surface_haute};
}}

QCheckBox::indicator:checked {{
    background-color: {p.accent};
    border-color: {p.accent};
}}

/* ---------- Liste des coups ---------- */

QTableWidget {{
    background-color: {p.surface};
    alternate-background-color: {p.surface_haute};
    border: 1px solid {p.bordure};
    border-radius: 10px;
    gridline-color: transparent;
    selection-background-color: transparent;
}}

QTableWidget::item {{
    padding: 6px 8px;
    border: none;
    border-radius: 6px;
}}

QTableWidget::item:hover {{
    background-color: {p.survol};
}}

QTableWidget::item:selected {{
    background-color: {p.selection};
    color: {p.texte};
}}

QHeaderView::section {{
    background-color: {p.surface};
    color: {p.texte_faible};
    border: none;
    border-bottom: 1px solid {p.bordure};
    padding: 6px;
    font-weight: 600;
}}

QListWidget {{
    background-color: {p.surface};
    border: 1px solid {p.bordure};
    border-radius: 10px;
    padding: 4px;
}}

QListWidget::item {{
    padding: 7px 10px;
    border-radius: 7px;
}}

QListWidget::item:hover {{
    background-color: {p.survol};
}}

QListWidget::item:selected {{
    background-color: {p.selection};
    color: {p.texte};
}}

/* ---------- Onglets ---------- */

QTabWidget::pane {{
    background-color: {p.surface};
    border: 1px solid {p.bordure};
    border-radius: 10px;
    top: -1px;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {p.texte_faible};
    padding: 8px 18px;
    margin-right: 2px;
    border-radius: 8px;
    font-weight: 500;
}}

QTabBar::tab:hover {{
    background-color: {p.survol};
    color: {p.texte};
}}

QTabBar::tab:selected {{
    background-color: {p.surface};
    color: {p.texte};
    border: 1px solid {p.bordure};
}}

/* ---------- Barre de progression ---------- */

QProgressBar {{
    background-color: {p.surface_haute};
    border: none;
    border-radius: 6px;
    height: 8px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: {p.accent};
    border-radius: 6px;
}}

/* ---------- Barres de défilement ---------- */

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}}

QScrollBar::handle:vertical {{
    background-color: {p.bordure};
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {p.texte_faible};
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px 4px;
}}

QScrollBar::handle:horizontal {{
    background-color: {p.bordure};
    border-radius: 5px;
    min-width: 30px;
}}

/* ---------- Divers ---------- */

QSplitter::handle {{
    background-color: transparent;
    width: 8px;
}}

QSplitter::handle:hover {{
    background-color: {p.bordure};
}}

QStatusBar {{
    background-color: {p.surface};
    border-top: 1px solid {p.bordure};
    color: {p.texte_faible};
}}

QStatusBar::item {{
    border: none;
}}

QToolTip {{
    background-color: {p.surface_haute};
    color: {p.texte};
    border: 1px solid {p.bordure};
    border-radius: 6px;
    padding: 5px 8px;
}}

QMessageBox {{
    background-color: {p.surface};
}}

QGroupBox {{
    border: 1px solid {p.bordure};
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {p.texte_faible};
}}
"""


def apply_theme(app, mode: ThemeMode) -> Palette:
    """Applique un thème à l'application entière et rend la palette utilisée."""
    palette = resolve(mode)
    app.setStyle("Fusion")  # base neutre, identique sur toutes les plateformes
    app.setStyleSheet(stylesheet(palette))
    return palette