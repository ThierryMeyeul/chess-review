"""Liste des coups, en deux colonnes.

Un coup blanc et un coup noir par ligne, comme une feuille de partie. La
version précédente empilait un demi-coup par ligne, ce qui doublait la hauteur
et cassait la lecture par paires à laquelle tout joueur est habitué.

Le badge est réduit à son symbole. Écrire « Occasion manquée » en toutes
lettres dans une colonne de 80 pixels est illisible ; le libellé complet reste
disponible en infobulle et dans le panneau de détail.
"""

from __future__ import annotations

import chess
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtCore import QRectF, QSize as _QSize
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap, Qt as _Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
)

from src.core.classify import GameReport, MoveClass
from src.ui.badges import BadgeIcons
from src.ui.board_widget import COULEURS_BADGE, GLYPHES_BADGE
from src.ui.figurine import to_figurine
from src.ui.pieces import JEU_INTEGRE, PieceSet

ROLE_COUP = Qt.ItemDataRole.UserRole + 1

TAILLE_PIECE = 19

COLONNE_NUMERO = 0
COLONNE_BLANC = 1
COLONNE_NOIR = 2


class MoveDelegate(QStyledItemDelegate):
    """Dessine un coup : pièce, texte, puis badge.

    Un QTableWidgetItem n'accepte qu'une seule icône, or il en faut deux — la
    pièce jouée et la qualité du coup. D'où ce délégué, qui reprend le rendu
    complet de la cellule.

    La pièce provient du même jeu que l'échiquier, comme dans le bandeau des
    captures : les glyphes typographiques n'y ressemblaient à rien et
    ignoraient le thème choisi.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._piece_set = PieceSet(JEU_INTEGRE)
        self._badges = BadgeIcons()

    def set_piece_set(self, key: str) -> None:
        self._piece_set = PieceSet(key)

    def paint(self, painter, option, index) -> None:
        donnees = index.data(ROLE_COUP)
        if donnees is None:
            super().paint(painter, option, index)
            return

        symbole, texte, classification = donnees

        style = option.widget.style() if option.widget else None
        if style is not None:
            style.drawPrimitive(
                QStyle.PrimitiveElement.PE_PanelItemViewItem,
                option,
                painter,
                option.widget,
            )

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = option.rect
        taille = min(TAILLE_PIECE, rect.height() - 2)
        x = rect.left() + 6.0
        y = rect.top() + (rect.height() - taille) / 2.0

        if symbole:
            piece = chess.Piece.from_symbol(symbole)
            self._piece_set.draw(painter, piece, QRectF(x, y, taille, taille))
            x += taille + 2.0

        couleur = (
            QColor(COULEURS_BADGE[classification])
            if classification is not None
            else QColor(option.palette.text().color())
        )
        painter.setPen(couleur)
        painter.setFont(option.font)

        largeur_badge = taille + 4.0 if classification is not None else 0.0
        zone_texte = rect.adjusted(
            int(x - rect.left()), 0, int(-largeur_badge - 4), 0
        )
        painter.drawText(
            zone_texte,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            texte,
        )

        if classification is not None:
            moteur = self._badges.renderer(classification)
            bx = rect.right() - taille - 4.0
            if moteur is not None:
                moteur.render(painter, QRectF(bx, y, taille, taille))
            else:
                painter.drawText(
                    QRectF(bx, rect.top(), taille, rect.height()),
                    int(Qt.AlignmentFlag.AlignCenter),
                    GLYPHES_BADGE.get(classification, ""),
                )

        painter.restore()


class MoveListWidget(QTableWidget):
    """Feuille de partie cliquable. Émet le demi-coup sélectionné."""

    ply_selected = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(0, 3, parent)
        self._plies: dict[tuple[int, int], int] = {}
        self._maj_en_cours = False
        self._badges = BadgeIcons()
        self._icones: dict[MoveClass, QIcon] = {}
        self._delegate = MoveDelegate(self)
        for colonne in (COLONNE_BLANC, COLONNE_NOIR):
            self.setItemDelegateForColumn(colonne, self._delegate)

        self.setHorizontalHeaderLabels(["#", "Blancs", "Noirs"])
        self.verticalHeader().setVisible(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        entete = self.horizontalHeader()
        entete.setSectionResizeMode(COLONNE_NUMERO, QHeaderView.ResizeMode.Fixed)
        entete.setSectionResizeMode(COLONNE_BLANC, QHeaderView.ResizeMode.Stretch)
        entete.setSectionResizeMode(COLONNE_NOIR, QHeaderView.ResizeMode.Stretch)
        self.setColumnWidth(COLONNE_NUMERO, 44)

        self.itemSelectionChanged.connect(self._on_selection)

    # -- remplissage ------------------------------------------------------

    def populate(self, moves: list[chess.Move], report: GameReport | None) -> None:
        """Remplit la feuille. `report` peut être absent avant l'analyse."""
        self._maj_en_cours = True
        self.clearContents()
        self._plies.clear()

        lignes = (len(moves) + 1) // 2
        self.setRowCount(lignes)

        board = chess.Board()
        police_coup = QFont("monospace")
        police_coup.setPointSize(11)

        for index, move in enumerate(moves):
            ply = index + 1
            ligne = index // 2
            colonne = COLONNE_BLANC if board.turn == chess.WHITE else COLONNE_NOIR

            if colonne == COLONNE_BLANC:
                numero = QTableWidgetItem(f"{board.fullmove_number}.")
                numero.setFlags(Qt.ItemFlag.ItemIsEnabled)
                numero.setForeground(QBrush(QColor("#888F9A")))
                numero.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self.setItem(ligne, COLONNE_NUMERO, numero)

            san = board.san(move)
            board.push(move)  # la pièce d'arrivée se lit après le coup

            classification = None
            if report is not None and index < len(report.moves):
                classification = report.moves[index].classification

            piece = board.piece_at(move.to_square)
            # Pas de figurine pour un pion — sa colonne de départ tient ce rôle
            # — ni pour un roque, dont la notation se suffit à elle-même. Sur
            # une promotion, c'est la pièce obtenue qui est montrée.
            symbole = ""
            if (
                piece is not None
                and piece.piece_type != chess.PAWN
                and not san.startswith("O-O")
            ):
                symbole = piece.symbol()
            texte = san
            if symbole and texte[0] in "KQRBN":
                texte = texte[1:]
            if symbole and "=" in texte:
                # L'icône montre déjà la pièce obtenue : « =D » ferait doublon.
                # Le suffixe d'échec ou de mat, lui, doit rester.
                avant, _, apres = texte.partition("=")
                texte = avant + apres[1:]

            cellule = QTableWidgetItem()
            cellule.setFont(police_coup)
            cellule.setData(ROLE_COUP, (symbole, texte, classification))
            if classification is not None:
                cellule.setToolTip(classification.label)
            self.setItem(ligne, colonne, cellule)
            self._plies[(ligne, colonne)] = ply

        # Une case vide et non sélectionnable quand les noirs n'ont pas répondu.
        if len(moves) % 2 == 1:
            vide = QTableWidgetItem("")
            vide.setFlags(Qt.ItemFlag.NoItemFlags)
            self.setItem(lignes - 1, COLONNE_NOIR, vide)

        self.resizeRowsToContents()
        self._ajuster_hauteur()
        self._maj_en_cours = False

    def set_piece_set(self, key: str) -> None:
        self._delegate.set_piece_set(key)
        self.viewport().update()

    def _icone(self, classification: MoveClass) -> QIcon | None:
        """Icône mise en cache, rendue une fois en pixmap."""
        if classification in self._icones:
            return self._icones[classification]

        moteur = self._badges.renderer(classification)
        if moteur is None:
            return None

        pixmap = QPixmap(_QSize(18, 18))
        pixmap.fill(_Qt.GlobalColor.transparent)
        peintre = QPainter(pixmap)
        moteur.render(peintre)
        peintre.end()

        icone = QIcon(pixmap)
        self._icones[classification] = icone
        return icone

    def _ajuster_hauteur(self) -> None:
        """Plafonne la hauteur au contenu réel.

        Sans ça, le tableau réclame toute la place de sa colonne et laisse une
        zone vide sous le dernier coup. La contrainte est un maximum, pas une
        taille fixe : sur une partie longue, la mise en page réduit le tableau
        et la barre de défilement reprend son rôle.
        """
        hauteur = self.horizontalHeader().height() + 2 * self.frameWidth()
        for ligne in range(self.rowCount()):
            hauteur += self.rowHeight(ligne)
        self.setMaximumHeight(max(hauteur, 80))

    @staticmethod
    def _texte(san: str, classification: MoveClass | None) -> str:
        """Coup suivi de son symbole, jamais du libellé complet."""
        if classification is None:
            return san
        symbole = GLYPHES_BADGE.get(classification, "")
        return f"{san} {symbole}".strip()

    # -- sélection --------------------------------------------------------

    def select_ply(self, ply: int) -> None:
        """Sélectionne un demi-coup sans réémettre de signal."""
        self._maj_en_cours = True
        if ply <= 0:
            self.clearSelection()
        else:
            for (ligne, colonne), valeur in self._plies.items():
                if valeur == ply:
                    self.setCurrentCell(ligne, colonne)
                    self.scrollToItem(
                        self.item(ligne, colonne),
                        QAbstractItemView.ScrollHint.EnsureVisible,
                    )
                    break
        self._maj_en_cours = False

    def _on_selection(self) -> None:
        if self._maj_en_cours:
            return
        cellule = self.currentItem()
        if cellule is None:
            return
        ply = self._plies.get((cellule.row(), cellule.column()))
        if ply is not None:
            self.ply_selected.emit(ply)

    def sizeHint(self) -> QSize:
        return QSize(320, 480)