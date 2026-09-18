import sys, chess, chess.svg
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtCore import QByteArray

board = chess.Board()
for c in ("e4", "e5", "Nf3", "Nc6", "Bb5"):
    board.push_san(c)

app = QApplication(sys.argv)
win = QMainWindow()
svg = QSvgWidget()
svg.load(QByteArray(chess.svg.board(board, size=500, lastmove=board.peek()).encode()))
win.setCentralWidget(svg)
win.resize(520, 540)
win.show()
sys.exit(app.exec())

