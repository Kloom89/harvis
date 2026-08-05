"""Teams desktop por UI Automation (accesibilidad de Windows): lee la lista
de chats como TEXTO real — nombres, previews, no leídos — sin capturas.
Muchas empresas bloquean la Graph API; esto lee lo que la app ya muestra."""
import asyncio
import logging
import re
import time

from registry import kloom_tool

log = logging.getLogger("kloom.tools.teams")

MAX_ITEMS = 25


def _leer_chats() -> str:
    from pywinauto import Desktop

    win = Desktop(backend="uia").window(title_re=".*Microsoft Teams.*")
    if not win.exists(timeout=2):
        return ("Teams no está abierto. Abrilo con open_app('Microsoft "
                "Teams') y volvé a intentar en unos segundos.")
    # Ir a la vista Chat si no estamos ahí (el título dice la vista actual)
    if not win.window_text().lower().startswith(("chat", "conversac")):
        for b in win.descendants(control_type="Button"):
            nombre = b.window_text().strip().lower()
            if re.match(r"^chat\b", nombre):
                try:
                    b.invoke()
                except Exception:
                    b.click_input()
                time.sleep(2.0)  # que cargue la lista
                break
    win2 = Desktop(backend="uia").window(title_re=".*Microsoft Teams.*")
    lineas = []
    for ct in ("ListItem", "TreeItem"):
        for it in win2.descendants(control_type=ct):
            t = " ".join(it.window_text().split())
            if len(t) > 15:  # descartar íconos y adornos
                lineas.append(t)
        if len(lineas) >= 3:
            break
    if not lineas:
        return ("No pude leer la lista de chats (la vista no cargó o la "
                "accesibilidad no expuso los items). Alternativa: "
                "take_screenshot y leela.")
    return "\n".join(lineas[:MAX_ITEMS])


@kloom_tool("teams_unread", "Lee la lista de chats de Microsoft Teams (nombres, último mensaje, no leídos) como texto. Usar cuando pregunten 'quién me habló' / 'qué hay en Teams'. Respondé con nombre + canal + mensaje: 'Ana dijo en Proyecto X: ...'. OJO: cambia la vista de Teams a Chat.", {})
async def teams_unread(args):
    try:
        return await asyncio.wait_for(asyncio.to_thread(_leer_chats),
                                      timeout=30)
    except asyncio.TimeoutError:
        return "Teams no respondió a tiempo."
    except Exception as e:
        log.exception("teams_unread")
        return f"No pude leer Teams: {e}"


TOOLS = [teams_unread]
