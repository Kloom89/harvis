"""WhatsApp por voz, en DOS pasos: draft precarga el mensaje en el chat
correcto (protocolo whatsapp:// del WhatsApp Desktop) SIN enviarlo; el envío
es un paso aparte y explícito. Un dictado mal transcripto nunca sale solo.

Agenda propia en contactos_whatsapp.json — se cargan por voz.
"""
import asyncio
import json
import logging
import os
import re
import time
import urllib.parse

from registry import kloom_tool

log = logging.getLogger("kloom.tools.whatsapp")

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTACTOS_FILE = os.path.join(_DIR, "contactos_whatsapp.json")
_NUM = re.compile(r"^\+\d{8,15}$")


def _cargar() -> dict:
    if os.path.exists(CONTACTOS_FILE):
        try:
            return json.load(open(CONTACTOS_FILE, encoding="utf-8"))
        except Exception:
            log.exception("contactos ilegibles")
    return {}


def _norm(nombre: str) -> str:
    return nombre.strip().lower()


@kloom_tool("whatsapp_add_contact", "Guarda o actualiza un contacto de WhatsApp (número internacional, ej +5493511234567). Usar cuando el usuario dicta un número.", {"nombre": str, "numero": str})
async def whatsapp_add_contact(args):
    numero = re.sub(r"[ \-()]", "", args["numero"].strip())
    if not numero.startswith("+"):
        numero = "+" + numero
    if not _NUM.match(numero):
        return f"'{numero}' no parece un número internacional válido."
    contactos = _cargar()
    contactos[_norm(args["nombre"])] = numero
    json.dump(contactos, open(CONTACTOS_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return f"Guardado: {args['nombre']} → {numero}."


def _draft_por_nombre(nombre: str, mensaje: str) -> str:
    """Como lo haría un humano: buscador de WhatsApp → nombre → primer
    chat → escribir el mensaje. NUNCA Enter final."""
    from pynput.keyboard import Controller, Key

    from teclado import paste
    from tools.windows import _find_window, focus_hwnd

    hwnd = _find_window("WhatsApp")
    if not hwnd:
        os.startfile("whatsapp://")
        time.sleep(4)
        hwnd = _find_window("WhatsApp")
        if not hwnd:
            return "No pude abrir WhatsApp."
    focus_hwnd(hwnd)
    time.sleep(0.6)
    kb = Controller()
    with kb.pressed(Key.ctrl):        # buscador de chats
        kb.tap("f")
    time.sleep(0.5)
    with kb.pressed(Key.ctrl):        # limpiar búsqueda previa
        kb.tap("a")
    kb.tap(Key.delete)
    time.sleep(0.2)
    # Whisper mastica los nombres dictados ("Dani"→"Danny"): se busca por
    # la palabra MÁS LARGA del nombre (el apellido suele venir bien) para
    # maximizar el match. El chat queda a la vista antes de confirmar.
    busqueda = max(nombre.split(), key=len)
    paste(busqueda, press_enter=False)
    time.sleep(1.5)                   # que filtre resultados
    kb.tap(Key.enter)                 # abre el primer resultado
    time.sleep(0.9)
    paste(mensaje, press_enter=False)
    return (f"Busqué '{nombre}' y dejé el mensaje escrito SIN enviar. "
            "MIRÁ que el chat sea el correcto y decime «mandalo».")


@kloom_tool("whatsapp_draft", "PASO 1 de mandar un WhatsApp: busca el contacto POR NOMBRE (como figura en WhatsApp) y deja el mensaje escrito en su chat, SIN enviarlo. El usuario después confirma con 'mandalo'. No hace falta número de teléfono.", {"contacto": str, "mensaje": str})
async def whatsapp_draft(args):
    contactos = _cargar()
    nombre = _norm(args["contacto"])
    numero = contactos.get(nombre)
    if not numero:
        hits = [n for n in contactos if nombre in n or n in nombre]
        if len(hits) == 1:
            numero = contactos[hits[0]]
    if numero:
        # atajo exacto: con número no hay ambigüedad de búsqueda
        url = (f"whatsapp://send?phone={urllib.parse.quote(numero)}"
               f"&text={urllib.parse.quote(args['mensaje'])}")
        await asyncio.to_thread(os.startfile, url)
        return (f"Le dejé el mensaje listo a {args['contacto']}. "
                "Confirmá con «mandalo» o tocá Enter.")
    return await asyncio.to_thread(_draft_por_nombre, args["contacto"],
                                   args["mensaje"])


@kloom_tool("whatsapp_confirm", "PASO 2: envía el mensaje que quedó precargado en WhatsApp (Enter en su ventana). SOLO usar cuando el usuario dijo explícitamente 'mandalo' / 'enviálo' DESPUÉS de un whatsapp_draft.", {})
async def whatsapp_confirm(args):
    def _enter():
        from pynput.keyboard import Controller, Key
        from tools.windows import _find_window, focus_hwnd
        hwnd = _find_window("WhatsApp")
        if not hwnd:
            return "No encuentro la ventana de WhatsApp."
        focus_hwnd(hwnd)
        time.sleep(0.4)  # que el foco asiente
        kb = Controller()
        kb.press(Key.enter)
        kb.release(Key.enter)
        return "Enviado."
    return await asyncio.to_thread(_enter)


@kloom_tool("whatsapp_contacts", "Lista los contactos de WhatsApp guardados.", {})
async def whatsapp_contacts(args):
    contactos = _cargar()
    if not contactos:
        return "No hay contactos guardados todavía."
    return ", ".join(f"{n} ({num})" for n, num in sorted(contactos.items()))


TOOLS = [whatsapp_add_contact, whatsapp_draft, whatsapp_confirm,
         whatsapp_contacts]
