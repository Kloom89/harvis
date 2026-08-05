"""Apps y ventanas de Windows: abrir por Start Menu, cerrar/foco/min/max."""
import glob
import logging
import os

import win32con
import win32gui

from registry import kloom_tool

log = logging.getLogger("kloom.tools.windows")

_START_DIRS = [
    os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
    os.path.expandvars(r"%AppData%\Microsoft\Windows\Start Menu\Programs"),
]


def _index_apps() -> dict[str, str]:
    apps = {}
    for base in _START_DIRS:
        for lnk in glob.glob(os.path.join(base, "**", "*.lnk"), recursive=True):
            apps[os.path.splitext(os.path.basename(lnk))[0].lower()] = lnk
    return apps


# Apps UWP/sistema sin .lnk en el Start Menu, por su nombre en castellano.
_ALIASES = {
    "calculadora": "calc", "calc": "calc",
    "bloc de notas": "notepad", "notepad": "notepad",
    "explorador": "explorer", "explorador de archivos": "explorer",
    "configuracion": "ms-settings:", "configuración": "ms-settings:",
    "administrador de tareas": "taskmgr", "paint": "mspaint",
    "camara": "microsoft.windows.camera:", "cámara": "microsoft.windows.camera:",
}


def _find_app(name: str) -> str | None:
    apps = _index_apps()
    name = name.lower().strip()
    if name in apps:
        return apps[name]
    for app, lnk in apps.items():
        if name in app:
            return lnk
    return None


def _find_window(title: str) -> int | None:
    title = title.lower()
    hits = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if t and title in t.lower():
                hits.append(hwnd)

    win32gui.EnumWindows(cb, None)
    return hits[0] if hits else None


def focus_hwnd(hwnd: int):
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        # Windows bloquea robar el foco desde un proceso de fondo (error
        # 258): el truco estándar es un toque de ALT antes de reintentar.
        from pynput.keyboard import Controller, Key
        kb = Controller()
        kb.press(Key.alt)
        kb.release(Key.alt)
        win32gui.SetForegroundWindow(hwnd)


@kloom_tool("open_app", "Abre una aplicación instalada, por nombre (ej: 'calculadora', 'spotify', 'notepad').", {"name": str})
async def open_app(args):
    name = args["name"].lower().strip()
    if name in _ALIASES:
        os.startfile(_ALIASES[name])
        return f"Abierta: {name}"
    lnk = _find_app(name)
    if lnk:
        os.startfile(lnk)
        return f"Abierta: {os.path.splitext(os.path.basename(lnk))[0]}"
    try:
        os.startfile(name)  # comandos de Windows: calc, notepad, winword...
        return f"Abierta: {name}"
    except OSError:
        return f"No encontré ninguna app que se llame '{name}'."


@kloom_tool("close_window", "Cierra la ventana ENTERA (la app completa) cuyo título contiene el texto dado. Para cerrar UNA pestaña o página del navegador usá close_tab, NO esto.", {"title": str})
async def close_window(args):
    import asyncio
    hwnd = _find_window(args["title"])
    if not hwnd:
        return f"No hay ninguna ventana con '{args['title']}' en el título."
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    # VERIFICAR el efecto (lección Automaton): el navegador puede mostrar
    # un diálogo de confirmación y la ventana sigue viva — no mentir.
    await asyncio.sleep(1.2)
    if win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd):
        return ("La ventana SIGUE abierta: la app pidió confirmación para "
                "cerrar (p.ej. el navegador con varias pestañas). Avisale "
                "al usuario que confirme él, o usá close_tab si solo había "
                "que cerrar una pestaña.")
    return "Cerrada, verificado."


@kloom_tool("close_tab", "Cierra la PESTAÑA activa del navegador (u otra app con pestañas) cuyo título contiene el texto dado: trae la ventana al frente y manda Ctrl+W. Para cerrar 'la página de noticias' o 'esa pestaña', usá esto y no close_window.", {"title": str})
async def close_tab(args):
    import asyncio
    hwnd = _find_window(args["title"])
    if not hwnd:
        return f"No hay ninguna ventana con '{args['title']}' en el título."
    titulo_antes = win32gui.GetWindowText(hwnd)
    focus_hwnd(hwnd)
    await asyncio.sleep(0.3)
    from teclado import combo
    combo("ctrl", "w")
    await asyncio.sleep(0.8)
    # verificación honesta: el título cambia al cerrar la pestaña activa
    if win32gui.IsWindow(hwnd):
        titulo_ahora = win32gui.GetWindowText(hwnd)
        if titulo_ahora == titulo_antes:
            return ("Mandé cerrar la pestaña pero el título no cambió — "
                    "puede que no se haya cerrado. Decíselo al usuario.")
        return f"Pestaña cerrada; ahora se ve: {titulo_ahora[:60]}"
    return "Pestaña cerrada (era la última: se cerró la ventana)."


@kloom_tool("focus_window", "Trae al frente la ventana cuyo título contiene el texto dado.", {"title": str})
async def focus_window(args):
    hwnd = _find_window(args["title"])
    if not hwnd:
        return f"No hay ninguna ventana con '{args['title']}' en el título."
    focus_hwnd(hwnd)
    return "Al frente."


@kloom_tool("minimize_window", "Minimiza la ventana cuyo título contiene el texto dado.", {"title": str})
async def minimize_window(args):
    hwnd = _find_window(args["title"])
    if not hwnd:
        return f"No hay ninguna ventana con '{args['title']}' en el título."
    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    return "Minimizada."


@kloom_tool("maximize_window", "Maximiza la ventana cuyo título contiene el texto dado.", {"title": str})
async def maximize_window(args):
    hwnd = _find_window(args["title"])
    if not hwnd:
        return f"No hay ninguna ventana con '{args['title']}' en el título."
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    return "Maximizada."


@kloom_tool("list_windows", "Lista los títulos de las ventanas abiertas.", {})
async def list_windows(args):
    titles = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if t:
                titles.append(t)

    win32gui.EnumWindows(cb, None)
    return "\n".join(titles) or "No hay ventanas visibles."


TOOLS = [open_app, close_window, close_tab, focus_window, minimize_window,
         maximize_window, list_windows]
