"""Mandarle texto a la sesión de Claude Code: enfocar su ventana, pegar, Enter."""
import asyncio
import logging
import time

from registry import kloom_tool
from teclado import paste
from tools.windows import _find_window, focus_hwnd

log = logging.getLogger("kloom.tools.claude_code")

WINDOW_TITLE = "Claude"  # kloom.py lo pisa desde config.yaml


def paste_to_window(title: str, text: str, press_enter: bool = True) -> str:
    hwnd = _find_window(title)
    if not hwnd:
        return f"No encontré ninguna ventana con '{title}' en el título."
    focus_hwnd(hwnd)
    time.sleep(0.3)  # que el foco asiente antes de pegar
    paste(text, press_enter)
    return "Enviado."


@kloom_tool("send_to_claude", "Escribe un mensaje en la ventana de Claude Code y lo envía. Usar cuando piden 'decile a claude ...' o delegar una tarea de programación.", {"message": str})
async def send_to_claude(args):
    return await asyncio.to_thread(paste_to_window, WINDOW_TITLE,
                                   args["message"], True)


@kloom_tool("type_into_window", "Escribe texto en cualquier ventana abierta (Word, Excel, bloc de notas...) por su título, sin Enter al final. Usar cuando piden 'escribí X en Y' o dictar a un documento.", {"title": str, "text": str})
async def type_into_window(args):
    return await asyncio.to_thread(paste_to_window, args["title"],
                                   args["text"], False)


TOOLS = [send_to_claude, type_into_window]
