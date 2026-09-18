"""Lecture des sons de coups.

QSoundEffect est fait pour ça : il garde l'échantillon décodé en mémoire et le
rejoue sans latence, contrairement à QMediaPlayer qui redécode à chaque appel
et introduit un décalage audible.

Le lecteur est volontairement tolérant : fichiers manquants, backend audio
absent, session sans serveur de son — rien de tout cela ne doit faire tomber
l'application. Un échec de lecture est silencieux, au sens propre.
"""

from __future__ import annotations

from pathlib import Path

import chess
from PySide6.QtCore import QObject, QUrl

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QSoundEffect

    AUDIO_DISPONIBLE = True
except ImportError:  # PySide6 installé sans QtMultimedia
    QSoundEffect = None  # type: ignore[assignment]
    QMediaPlayer = None  # type: ignore[assignment]
    QAudioOutput = None  # type: ignore[assignment]
    AUDIO_DISPONIBLE = False

from src.core.classify import MoveClass
from src.core.paths import sounds_dir

NOMS = ("move", "capture", "check", "castle", "promote", "blunder", "end")


def sound_for_move(
    board_before: chess.Board,
    move: chess.Move,
    board_after: chess.Board,
    classification: MoveClass | None = None,
) -> str:
    """Choisit le son correspondant à un coup.

    L'ordre des tests compte : un mat est d'abord une fin de partie, un échec
    prime sur une prise, et une faute grave remplace le son de déplacement
    ordinaire — sinon on n'entend jamais qu'on vient de se tromper.
    """
    if board_after.is_game_over():
        return "end"
    if board_after.is_check():
        return "check"
    if classification in (MoveClass.BLUNDER, MoveClass.MISS):
        return "blunder"
    if move.promotion is not None:
        return "promote"
    if board_before.is_castling(move):
        return "castle"
    if board_before.is_capture(move):
        return "capture"
    return "move"


class SoundPlayer(QObject):
    """Banque d'échantillons chargée une fois au démarrage."""

    def __init__(
        self,
        directory: str | Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._enabled = True
        self._volume = 0.6
        self._effects: dict[str, object] = {}
        self._outputs: dict[str, object] = {}
        self._directory = Path(directory) if directory else sounds_dir()
        self._load()

    def _load(self) -> None:
        """Charge un échantillon par nom, en préférant le mp3 au wav.

        QSoundEffect garde le son décodé en mémoire et le rejoue sans latence,
        mais ne lit que du WAV. Pour les mp3 il faut un QMediaPlayer, plus
        lourd — d'où les deux chemins de code. Les mp3 passent en premier :
        c'est le jeu téléchargé, plus travaillé que les sons synthétisés.
        """
        if not AUDIO_DISPONIBLE:
            return
        for nom in NOMS:
            mp3 = self._directory / f"{nom}.mp3"
            wav = self._directory / f"{nom}.wav"

            if mp3.is_file() and QMediaPlayer is not None:
                sortie = QAudioOutput(self)
                sortie.setVolume(self._volume)
                lecteur = QMediaPlayer(self)
                lecteur.setAudioOutput(sortie)
                lecteur.setSource(QUrl.fromLocalFile(str(mp3.resolve())))
                # La sortie audio doit survivre au lecteur : sans référence,
                # elle est ramassée et le son devient muet.
                self._outputs[nom] = sortie
                self._effects[nom] = lecteur
            elif wav.is_file():
                effet = QSoundEffect(self)
                effet.setSource(QUrl.fromLocalFile(str(wav.resolve())))
                effet.setVolume(self._volume)
                self._effects[nom] = effet

    # -- état -------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Vrai si au moins un échantillon a pu être chargé."""
        return bool(self._effects)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, actif: bool) -> None:
        self._enabled = actif

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))
        for effet in self._effects.values():
            if hasattr(effet, "setVolume"):
                effet.setVolume(self._volume)
        for sortie in self._outputs.values():
            sortie.setVolume(self._volume)

    # -- lecture ----------------------------------------------------------

    def play(self, nom: str) -> None:
        if not self._enabled:
            return
        effet = self._effects.get(nom)
        if effet is None:
            return
        try:
            # Un QMediaPlayer relancé sans rembobinage ne rejoue rien : il est
            # déjà à la fin du morceau.
            if hasattr(effet, "setPosition"):
                effet.setPosition(0)
            effet.play()
        except Exception:
            # Un backend audio capricieux ne doit pas interrompre la partie.
            pass

    def play_move(
        self,
        board_before: chess.Board,
        move: chess.Move,
        board_after: chess.Board,
        classification: MoveClass | None = None,
    ) -> None:
        self.play(sound_for_move(board_before, move, board_after, classification))