"""Affichage de l'échiquier.

python-chess rend la position en SVG ; les flèches et les pastilles de badge
sont dessinées par-dessus avec QPainter.

Pourquoi ne pas laisser python-chess dessiner les flèches : ses pointes sont
énormes et leur taille n'est pas paramétrable. Reprendre le tracé en main coûte
une trentaine de lignes et donne le contrôle sur l'épaisseur, la pointe et la
transparence.

Sur les pièces : python-chess embarque le jeu Cburnett et ne permet pas d'en
changer — il n'y a pas de paramètre pour ça, le SVG des pièces est encodé dans
la bibliothèque. Le jeu « Neo » de chess.com est par ailleurs propriétaire et
ne peut pas être redistribué. Changer de jeu supposerait de fournir douze
fichiers SVG d'un set libre et de réécrire le rendu des pièces.
"""

from __future__ import annotations

import math
import re

import chess
import chess.svg
from PySide6.QtCore import (
    QByteArray,
    Signal,
    QEasingCurve,
    QPointF,
    QRectF,
    QSize,
    Qt,
    QVariantAnimation,
)
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.core.classify import MoveClass
from src.ui.badges import BadgeIcons
from src.ui.pieces import JEU_INTEGRE, PieceSet
from src.ui.theme import DEFAULT_THEME_KEY, BoardTheme, get_theme

# Couleur de la pastille selon la qualité du coup joué.
# Couleurs officielles, reprises de la configuration Tailwind de
# chess-game-review — elles-mêmes alignées sur celles de chess.com.
COULEURS_BADGE = {
    MoveClass.BRILLIANT: "#26C2A3",
    MoveClass.GREAT: "#749BBF",
    MoveClass.BEST: "#81B64C",
    MoveClass.EXCELLENT: "#81B64C",
    MoveClass.GOOD: "#95B776",
    MoveClass.BOOK: "#D5A47D",
    MoveClass.FORCED: "#96AF8B",
    MoveClass.INACCURACY: "#F7C631",
    MoveClass.MISTAKE: "#FFA459",
    MoveClass.MISS: "#FF7769",
    MoveClass.BLUNDER: "#FA412D",
}

# Glyphe affiché dans la pastille. Volontairement du texte et non des icônes :
# aucune ressource externe à embarquer, et ça reste lisible à petite taille.
GLYPHES_BADGE = {
    MoveClass.BRILLIANT: "!!",
    MoveClass.GREAT: "!",
    MoveClass.BEST: "★",
    MoveClass.EXCELLENT: "✓",
    MoveClass.GOOD: "✓",
    MoveClass.BOOK: "♦",
    MoveClass.FORCED: "→",
    MoveClass.INACCURACY: "?!",
    MoveClass.MISTAKE: "?",
    MoveClass.MISS: "✗",
    MoveClass.BLUNDER: "??",
}

COTE_MINIMUM = 320

# Proportions du tracé des flèches, en fraction d'une case.
EPAISSEUR_FLECHE = 0.13
LONGUEUR_POINTE = 0.28
LARGEUR_POINTE = 0.26
RECUL_DEPART = 0.30

# Durée du glissement d'une pièce. Au-delà de ~250 ms la navigation devient
# pénible quand on enchaîne les coups à la flèche du clavier.
DUREE_ANIMATION_MS = 170

# Aides visuelles du mode interactif.
# Passée à chess.svg via `fill` : la case est peinte SOUS les pièces. Un
# rectangle dessiné par-dessus le SVG masquerait la pièce sélectionnée.
COULEUR_SELECTION = "#F5F682"
COULEUR_CIBLE = "#14161A55"
RAYON_CIBLE = 0.16
EPAISSEUR_ANNEAU = 0.09


class PromotionDialog(QDialog):
    """Choix de la pièce de promotion."""

    PIECES = (
        (chess.QUEEN, "Dame"),
        (chess.ROOK, "Tour"),
        (chess.BISHOP, "Fou"),
        (chess.KNIGHT, "Cavalier"),
    )

    def __init__(self, couleur: chess.Color, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Promotion")
        self._choix = chess.QUEEN

        ligne = QHBoxLayout()
        for piece_type, libelle in self.PIECES:
            symbole = chess.Piece(piece_type, couleur).unicode_symbol()
            bouton = QPushButton(f"{symbole}\n{libelle}")
            bouton.setMinimumSize(72, 64)
            bouton.clicked.connect(lambda _=False, p=piece_type: self._choisir(p))
            ligne.addWidget(bouton)

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        boutons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addLayout(ligne)
        layout.addWidget(boutons)

    def _choisir(self, piece_type: chess.PieceType) -> None:
        self._choix = piece_type
        self.accept()

    @property
    def piece_type(self) -> chess.PieceType:
        return self._choix


class BoardWidget(QWidget):
    """Échiquier carré, en lecture seule ou jouable."""

    move_played = Signal(object)  # chess.Move

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(COTE_MINIMUM, COTE_MINIMUM)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._renderer = QSvgRenderer(self)
        self._board = chess.Board()
        self._lastmove: chess.Move | None = None
        self._best_move: chess.Move | None = None
        self._classification: MoveClass | None = None
        self._flipped = False
        self._theme: BoardTheme = get_theme(DEFAULT_THEME_KEY)
        self._show_badges = True

        # Les pièces sont dessinées par nous, pas par le SVG de l'échiquier :
        # c'est ce qui permet d'en changer le jeu.
        self._piece_set = PieceSet(JEU_INTEGRE)
        self._badges = BadgeIcons()
        self._display_board = chess.Board()

        self._interactive = False
        self._selection: chess.Square | None = None
        self._cibles: dict[chess.Square, bool] = {}  # case -> est une prise

        self._animate = True
        self._animation: QVariantAnimation | None = None
        self._anim_progress = 1.0
        self._anim_move: chess.Move | None = None
        self._anim_piece: chess.Piece | None = None

        # Déduits du SVG à chaque rendu : la marge des coordonnées a changé
        # entre versions de python-chess, on ne la code pas en dur.
        self._viewbox = 390.0
        self._margin = 15.0

        self._render()

    # -- API --------------------------------------------------------------

    def set_position(
        self,
        board: chess.Board,
        lastmove: chess.Move | None = None,
        best_move: chess.Move | None = None,
        classification: MoveClass | None = None,
        animate: bool = False,
    ) -> None:
        """Affiche une position, le coup joué et éventuellement le coup du moteur."""
        self._stop_animation()
        self._board = board
        self._lastmove = lastmove
        self._best_move = best_move
        self._classification = classification

        if animate and self._animate and lastmove is not None:
            self._start_animation(lastmove)
        else:
            self._render()

    def flip(self) -> None:
        self._flipped = not self._flipped
        self._render()

    @property
    def flipped(self) -> bool:
        return self._flipped

    def set_orientation(self, color: chess.Color) -> None:
        self._flipped = color == chess.BLACK
        self._render()

    def set_piece_set(self, key: str) -> None:
        self._piece_set = PieceSet(key)
        self.update()

    def reload_badges(self) -> None:
        self._badges = BadgeIcons()
        self.update()

    @property
    def piece_set(self) -> str:
        return self._piece_set.key

    def set_theme(self, theme: BoardTheme | str) -> None:
        self._theme = get_theme(theme) if isinstance(theme, str) else theme
        self._render()

    @property
    def theme(self) -> BoardTheme:
        return self._theme

    def set_show_badges(self, actif: bool) -> None:
        self._show_badges = actif
        self.update()

    def set_interactive(self, actif: bool) -> None:
        """Autorise le jeu à la souris sur la position affichée."""
        self._interactive = actif
        self._effacer_selection()
        self.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor if actif else Qt.CursorShape.ArrowCursor)
        )

    @property
    def interactive(self) -> bool:
        return self._interactive

    def _effacer_selection(self) -> None:
        avait = self._selection is not None
        self._selection = None
        self._cibles = {}
        if avait:
            self._render()
        else:
            self.update()

    # -- souris -----------------------------------------------------------

    def _square_at(self, x: float, y: float) -> chess.Square | None:
        """Case sous un point du widget, ou None si on est dans la marge."""
        cote = float(min(self.width(), self.height()))
        x0 = (self.width() - cote) / 2.0
        y0 = (self.height() - cote) / 2.0
        echelle = cote / self._viewbox
        marge = self._margin * echelle
        taille = chess.svg.SQUARE_SIZE * echelle

        colonne = int((x - x0 - marge) // taille)
        ligne = int((y - y0 - marge) // taille)
        if not (0 <= colonne <= 7 and 0 <= ligne <= 7):
            return None

        fichier = 7 - colonne if self._flipped else colonne
        rangee = ligne if self._flipped else 7 - ligne
        return chess.square(fichier, rangee)

    def mousePressEvent(self, event) -> None:
        if not self._interactive:
            return super().mousePressEvent(event)

        point = event.position()
        case = self._square_at(point.x(), point.y())
        if case is None:
            self._effacer_selection()
            return

        # Deuxième clic : on tente le coup.
        if self._selection is not None and case in self._cibles:
            self._jouer(self._selection, case)
            return

        piece = self._board.piece_at(case)
        if piece is not None and piece.color == self._board.turn:
            self._selection = case
            self._cibles = {
                coup.to_square: self._board.is_capture(coup)
                for coup in self._board.legal_moves
                if coup.from_square == case
            }
            self._render()
            return

        self._effacer_selection()

    def _jouer(self, depart: chess.Square, arrivee: chess.Square) -> None:
        coup = chess.Move(depart, arrivee)
        piece = self._board.piece_at(depart)

        # Une promotion sans pièce indiquée n'est pas un coup légal : il faut
        # demander laquelle avant de valider.
        derniere_rangee = 7 if self._board.turn == chess.WHITE else 0
        if (
            piece is not None
            and piece.piece_type == chess.PAWN
            and chess.square_rank(arrivee) == derniere_rangee
        ):
            dialogue = PromotionDialog(self._board.turn, self)
            if dialogue.exec() != QDialog.DialogCode.Accepted:
                self._effacer_selection()
                return
            coup = chess.Move(depart, arrivee, promotion=dialogue.piece_type)

        if coup in self._board.legal_moves:
            self._effacer_selection()
            self.move_played.emit(coup)
        else:
            self._effacer_selection()

    def set_animate(self, actif: bool) -> None:
        self._animate = actif
        if not actif:
            self._stop_animation()
            self._render()

    # -- animation --------------------------------------------------------

    def _start_animation(self, move: chess.Move) -> None:
        """Fait glisser la pièce de sa case de départ à sa case d'arrivée.

        Le fond est rendu sans la pièce concernée : elle est dessinée à part,
        à une position interpolée. Sans ce retrait on la verrait en double.
        """
        piece = self._board.piece_at(move.to_square)
        if piece is None:
            self._render()
            return

        self._anim_piece = piece
        self._anim_move = move
        self._anim_progress = 0.0

        fond = self._board.copy()
        fond.remove_piece_at(move.to_square)
        self._render(board_override=fond)

        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(DUREE_ANIMATION_MS)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.valueChanged.connect(self._on_anim_value)
        animation.finished.connect(self._on_anim_finished)
        self._animation = animation
        animation.start()

    def _on_anim_value(self, valeur) -> None:
        self._anim_progress = float(valeur)
        self.update()

    def _on_anim_finished(self) -> None:
        self._animation = None
        self._anim_move = None
        self._anim_progress = 1.0
        self._render()

    def _stop_animation(self) -> None:
        if self._animation is not None:
            self._animation.stop()
            self._animation = None
        self._anim_move = None
        self._anim_progress = 1.0

    # -- rendu du fond ----------------------------------------------------

    def _render(self, board_override: chess.Board | None = None) -> None:
        plateau = board_override if board_override is not None else self._board
        self._display_board = plateau
        check = self._board.king(self._board.turn) if self._board.is_check() else None

        remplissage = (
            {self._selection: COULEUR_SELECTION} if self._selection is not None else {}
        )

        # Échiquier vide : cases, coordonnées, surbrillances et case de départ.
        # Les pièces sont ajoutées dans paintEvent, depuis le jeu choisi.
        svg = chess.svg.board(
            chess.Board(None),
            orientation=chess.BLACK if self._flipped else chess.WHITE,
            lastmove=self._lastmove,
            check=check,
            fill=remplissage,
            colors=self._theme.colors(),
            size=None,  # c'est paintEvent qui décide de la taille
        )

        correspondance = re.search(r'viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+)', svg)
        if correspondance:
            self._viewbox = float(correspondance.group(1))
            self._margin = (self._viewbox - 8 * chess.svg.SQUARE_SIZE) / 2.0

        self._renderer.load(QByteArray(svg.encode("utf-8")))
        self.update()

    # -- géométrie --------------------------------------------------------

    def _square_center(
        self, square: chess.Square, x0: float, y0: float, cote: float
    ) -> QPointF:
        """Centre d'une case, en coordonnées du widget."""
        echelle = cote / self._viewbox
        marge = self._margin * echelle
        taille = chess.svg.SQUARE_SIZE * echelle

        fichier = chess.square_file(square)
        rangee = chess.square_rank(square)
        colonne = 7 - fichier if self._flipped else fichier
        ligne = rangee if self._flipped else 7 - rangee

        return QPointF(
            x0 + marge + (colonne + 0.5) * taille,
            y0 + marge + (ligne + 0.5) * taille,
        )

    def _square_size(self, cote: float) -> float:
        return chess.svg.SQUARE_SIZE * cote / self._viewbox

    # -- peinture ---------------------------------------------------------

    def paintEvent(self, event) -> None:
        if not self._renderer.isValid():
            return

        cote = float(min(self.width(), self.height()))
        x0 = (self.width() - cote) / 2.0
        y0 = (self.height() - cote) / 2.0

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        self._renderer.render(painter, QRectF(x0, y0, cote, cote))

        taille_case = self._square_size(cote)

        self._draw_pieces(painter, x0, y0, cote, taille_case)

        if self._selection is not None:
            self._draw_cibles(painter, x0, y0, cote, taille_case)

        if self._anim_move is not None and self._anim_piece is not None:
            depart = self._square_center(self._anim_move.from_square, x0, y0, cote)
            arrivee = self._square_center(self._anim_move.to_square, x0, y0, cote)
            t = self._anim_progress
            centre = QPointF(
                depart.x() + (arrivee.x() - depart.x()) * t,
                depart.y() + (arrivee.y() - depart.y()) * t,
            )
            self._piece_set.draw(
                painter,
                self._anim_piece,
                QRectF(
                    centre.x() - taille_case / 2.0,
                    centre.y() - taille_case / 2.0,
                    taille_case,
                    taille_case,
                ),
            )

        # Le coup du moteur passe dessous : c'est une suggestion, pas le sujet.
        if self._best_move is not None and self._best_move != self._lastmove:
            self._draw_arrow(
                painter,
                self._square_center(self._best_move.from_square, x0, y0, cote),
                self._square_center(self._best_move.to_square, x0, y0, cote),
                QColor("#95bb4a"),
                taille_case,
                alpha=150,
            )

        if self._lastmove is not None and self._classification is not None:
            couleur = QColor(COULEURS_BADGE.get(self._classification, "#95bb4a"))
            self._draw_arrow(
                painter,
                self._square_center(self._lastmove.from_square, x0, y0, cote),
                self._square_center(self._lastmove.to_square, x0, y0, cote),
                couleur,
                taille_case,
                alpha=225,
            )
            if self._show_badges:
                self._draw_badge(
                    painter,
                    self._square_center(self._lastmove.to_square, x0, y0, cote),
                    taille_case,
                    self._classification,
                )

        painter.end()

    def _draw_arrow(
        self,
        painter: QPainter,
        depart: QPointF,
        arrivee: QPointF,
        couleur: QColor,
        taille_case: float,
        alpha: int = 225,
    ) -> None:
        """Flèche à pointe discrète, façon chess.com."""
        vecteur = arrivee - depart
        longueur = math.hypot(vecteur.x(), vecteur.y())
        if longueur < 1.0:
            return

        unitaire = QPointF(vecteur.x() / longueur, vecteur.y() / longueur)
        perpendiculaire = QPointF(-unitaire.y(), unitaire.x())

        # On recule le départ pour ne pas recouvrir la pièce qui a bougé.
        origine = depart + unitaire * (taille_case * RECUL_DEPART)
        longueur_pointe = taille_case * LONGUEUR_POINTE
        base_pointe = arrivee - unitaire * longueur_pointe

        teinte = QColor(couleur)
        teinte.setAlpha(alpha)

        # Si le recul dépasse la longueur totale, on ne garde que la pointe.
        reste = QPointF(base_pointe.x() - origine.x(), base_pointe.y() - origine.y())
        if math.hypot(reste.x(), reste.y()) > 1.0:
            stylo = QPen(teinte, taille_case * EPAISSEUR_FLECHE)
            stylo.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(stylo)
            painter.drawLine(origine, base_pointe)

        demi = taille_case * LARGEUR_POINTE / 2.0
        pointe = QPolygonF(
            [
                arrivee,
                base_pointe + perpendiculaire * demi,
                base_pointe - perpendiculaire * demi,
            ]
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(teinte)
        painter.drawPolygon(pointe)

    def _draw_pieces(
        self,
        painter: QPainter,
        x0: float,
        y0: float,
        cote: float,
        taille_case: float,
    ) -> None:
        """Pose chaque pièce sur sa case, depuis le jeu sélectionné."""
        for case, piece in self._display_board.piece_map().items():
            centre = self._square_center(case, x0, y0, cote)
            self._piece_set.draw(
                painter,
                piece,
                QRectF(
                    centre.x() - taille_case / 2.0,
                    centre.y() - taille_case / 2.0,
                    taille_case,
                    taille_case,
                ),
            )

    def _draw_cibles(
        self,
        painter: QPainter,
        x0: float,
        y0: float,
        cote: float,
        taille_case: float,
    ) -> None:
        """Destinations possibles du coup en préparation.

        Un point plein pour une case vide, un anneau pour une prise : c'est la
        convention de tous les sites d'échecs, et elle évite de masquer la
        pièce que l'on s'apprête à capturer. La case de départ, elle, est
        peinte sous les pièces par le SVG.
        """
        for case, est_prise in self._cibles.items():
            point = self._square_center(case, x0, y0, cote)
            if est_prise:
                epaisseur = taille_case * EPAISSEUR_ANNEAU
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor(COULEUR_CIBLE), epaisseur))
                rayon = (taille_case - epaisseur) / 2.0
                painter.drawEllipse(point, rayon, rayon)
            else:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(COULEUR_CIBLE))
                rayon = taille_case * RAYON_CIBLE
                painter.drawEllipse(point, rayon, rayon)

    def _draw_badge(
        self,
        painter: QPainter,
        centre_case: QPointF,
        taille_case: float,
        classification: MoveClass,
    ) -> None:
        """Pastille de qualité, posée sur le coin supérieur droit de la case."""
        rayon = taille_case * 0.26
        centre = QPointF(
            centre_case.x() + taille_case * 0.40,
            centre_case.y() - taille_case * 0.40,
        )

        # Icône dédiée si elle a été installée, sinon le cercle dessiné.
        icone = self._badges.renderer(classification)
        if icone is not None:
            icone.render(
                painter,
                QRectF(
                    centre.x() - rayon, centre.y() - rayon, rayon * 2.0, rayon * 2.0
                ),
            )
            return

        painter.setPen(QPen(QColor("#FFFFFF"), max(1.0, taille_case * 0.045)))
        painter.setBrush(QColor(COULEURS_BADGE.get(classification, "#95bb4a")))
        painter.drawEllipse(centre, rayon, rayon)

        glyphe = GLYPHES_BADGE.get(classification, "")
        if not glyphe:
            return

        police = QFont(self.font())
        police.setBold(True)
        # Deux caractères tiennent moins bien qu'un seul : on réduit un peu.
        facteur = 0.68 if len(glyphe) > 1 else 0.95
        police.setPointSizeF(max(5.0, rayon * facteur))
        painter.setFont(police)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(
            QRectF(
                centre.x() - rayon,
                centre.y() - rayon,
                rayon * 2.0,
                rayon * 2.0,
            ),
            Qt.AlignmentFlag.AlignCenter,
            glyphe,
        )

    # -- dimensionnement --------------------------------------------------

    def sizeHint(self) -> QSize:
        return QSize(560, 560)

    def minimumSizeHint(self) -> QSize:
        return QSize(COTE_MINIMUM, COTE_MINIMUM)