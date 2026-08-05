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


@kloom_tool("close_window", "Cierra la ventana cuyo título contiene el texto dado (como clickear la X).", {"title": str})
async def close_window(args):
    hwnd = _find_window(args["title"])
    if not hwnd:
        return f"No hay ninguna ventana con '{args['title']}' en el título."
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    return "Cerrada."


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


TOOLS = [open_app, close_window, focus_window, minimize_window,
         maximize_window, list_windows]
