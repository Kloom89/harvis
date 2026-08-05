"""Skill Teams Asistente: leer la conversación de un chat puntual y
RESPONDER — en dos pasos como WhatsApp (draft visible, enviar solo con
"mandalo"). Complementa la tool core teams_unread (lista de chats)."""
import asyncio
import logging
import re
import time

from registry import kloom_tool

log = logging.getLogger("kloom.skills.teams")

PROMPT = (
    "Teams completo: teams_read_chat(nombre) abre un chat y te da los "
    "últimos mensajes; teams_draft_reply(nombre, mensaje) deja la "
    "respuesta ESCRITA SIN ENVIAR; teams_send_confirm SOLO cuando el usuario "
    "diga «mandalo» tras ver el borrador. Nunca envíes sin confirmación.")


def _ventana():
    from pywinauto import Desktop
    win = Desktop(backend="uia").window(title_re=".*Microsoft Teams.*")
    return win if win.exists(timeout=2) else None


def _abrir_chat(win, nombre: str):
    """Click en el item de la lista cuyo texto contenga el nombre."""
    objetivo = nombre.lower()
    for ct in ("ListItem", "TreeItem"):
        for it in win.descendants(control_type=ct):
            if objetivo in it.window_text().lower():
                try:
                    it.invoke()
                except Exception:
                    it.click_input()
                time.sleep(1.8)
                return True
    return False


def _leer(nombre: str) -> str:
    win = _ventana()
    if not win:
        return "Teams no está abierto."
    if not _abrir_chat(win, nombre):
        return (f"No encontré un chat que contenga '{nombre}'. "
                "Mirá teams_unread para los nombres exactos.")
    from pywinauto import Desktop
    win = Desktop(backend="uia").window(title_re=".*Microsoft Teams.*")
    textos = []
    for el in win.descendants(control_type="Text"):
        t = " ".join(el.window_text().split())
        if len(t) > 2:
            textos.append(t)
    cuerpo = "\n".join(textos[-60:])
    return cuerpo[-3500:] if cuerpo else "El chat se abrió pero no leí texto."


def _draft(nombre: str, mensaje: str) -> str:
    win = _ventana()
    if not win:
        return "Teams no está abierto."
    if nombre and not _abrir_chat(win, nombre):
        return f"No encontré el chat '{nombre}'."
    from pywinauto import Desktop
    from teclado import paste
    win = Desktop(backend="uia").window(title_re=".*Microsoft Teams.*")
    # el cuadro de mensaje es el Edit de más abajo en la ventana
    edits = win.descendants(control_type="Edit")
    if not edits:
        return "No encontré el cuadro de mensaje."
    caja = max(edits, key=lambda e: e.rectangle().top)
    caja.click_input()
    time.sleep(0.4)
    paste(mensaje, press_enter=False)
    return ("Respuesta escrita SIN enviar. Verificá el chat en pantalla "
            "y decime «mandalo».")


def _confirmar() -> str:
    win = _ventana()
    if not win:
        return "Teams no está abierto."
    from pynput.keyboard import Controller, Key
    win.set_focus()
    time.sleep(0.4)
    kb = Controller()
    kb.press(Key.enter)
    kb.release(Key.enter)
    return "Enviado."


@kloom_tool("teams_read_chat", "Abre un chat de Teams por nombre (persona o grupo) y devuelve los últimos mensajes como texto. OJO: abre el chat en pantalla (lo marca leído).", {"nombre": str})
async def teams_read_chat(args):
    return await asyncio.wait_for(
        asyncio.to_thread(_leer, args["nombre"].strip()), timeout=40)


@kloom_tool("teams_draft_reply", "PASO 1 de responder en Teams: escribe el mensaje en el chat SIN enviarlo (queda visible para que el usuario lo verifique). Con nombre vacío usa el chat ya abierto.", {"nombre": (str, ""), "mensaje": str})
async def teams_draft_reply(args):
    return await asyncio.wait_for(
        asyncio.to_thread(_draft, (args.get("nombre") or "").strip(),
                          args["mensaje"]), timeout=40)


@kloom_tool("teams_send_confirm", "PASO 2: envía el borrador escrito en Teams (Enter). SOLO cuando el usuario dijo «mandalo» explícitamente después de ver el borrador.", {})
async def teams_send_confirm(args):
    return await asyncio.wait_for(asyncio.to_thread(_confirmar), timeout=20)


TOOLS = [teams_read_chat, teams_draft_reply, teams_send_confirm]
