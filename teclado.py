"""Teclado sintético (pynput) + pegado por portapapeles.

Por portapapeles y no tecla-por-tecla: instantáneo y no rompe acentos/ñ.
Restaura lo que el usuario tenía copiado."""
import time

import pyperclip
from pynput.keyboard import Controller, Key

_kb = Controller()

MEDIA = {
    "play": Key.media_play_pause, "pause": Key.media_play_pause,
    "next": Key.media_next, "previous": Key.media_previous,
    "volume_up": Key.media_volume_up, "volume_down": Key.media_volume_down,
    "mute": Key.media_volume_mute,
}


def paste(text: str, press_enter: bool) -> None:
    prev = pyperclip.paste()
    pyperclip.copy(text)
    with _kb.pressed(Key.ctrl):
        _kb.tap("v")
    if press_enter:
        time.sleep(0.2)
        _kb.tap(Key.enter)
    time.sleep(0.2)
    pyperclip.copy(prev)


def media(action: str) -> None:
    _kb.tap(MEDIA[action])
