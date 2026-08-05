"""Navegador: Chrome real vía CDP :9222 si está, si no el default del sistema."""
import json
import logging
import urllib.parse
import urllib.request
import webbrowser

from registry import kloom_tool

log = logging.getLogger("kloom.tools.browser")

CDP_PORT = 9222  # kloom.py lo pisa desde config.yaml
ON_MUSICA = None  # lo setea kloom: al arrancar música → privacidad AUTO
                  # (si no, el mic confunde la música con habla del usuario)


def _avisar_musica():
    if ON_MUSICA is not None:
        try:
            ON_MUSICA()
        except Exception:
            pass


def _open(url: str) -> str:
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{CDP_PORT}/json/new?{urllib.parse.quote(url, safe='')}",
            method="PUT")
        with urllib.request.urlopen(req, timeout=2) as r:
            json.load(r)
        return "Abierto en Chrome."
    except Exception:
        webbrowser.open(url)
        return "Abierto en el navegador."


@kloom_tool("open_url", "Abre una URL genérica en el navegador. PROHIBIDO para música o playlists (links de music.youtube.com incluidos): esto solo abre la página y NO reproduce nada — para que SUENE usá youtube_music.", {"url": str})
async def open_url(args):
    url = args["url"]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return _open(url)


@kloom_tool("web_search", "Busca en Google y abre los resultados.", {"query": str})
async def web_search(args):
    return _open("https://www.google.com/search?q="
                 + urllib.parse.quote_plus(args["query"]))


@kloom_tool("youtube_search", "Busca en YouTube y abre los resultados.", {"query": str})
async def youtube_search(args):
    return _open("https://www.youtube.com/results?search_query="
                 + urllib.parse.quote_plus(args["query"]))


def _fetch(url: str, timeout: int = 8) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


@kloom_tool("play_music", "Reproduce UNA canción o video puntual: abre directo el primer resultado de YouTube (empieza a sonar solo). SOLO para 'poné X' (una canción/artista). Para playlists del usuario o YouTube Music usá youtube_music. UNA llamada; si no salió lo esperado, contalo, no insistas con variantes.", {"query": str})
async def play_music(args):
    import asyncio
    import re as _re
    q = args["query"]
    try:
        html = await asyncio.to_thread(
            _fetch, "https://www.youtube.com/results?search_query="
            + urllib.parse.quote_plus(q))
        m = _re.search(r'"videoId":"([\w-]{11})"', html)
        if not m:
            return _open("https://www.youtube.com/results?search_query="
                         + urllib.parse.quote_plus(q))
        r = _open(f"https://www.youtube.com/watch?v={m.group(1)}")
        _avisar_musica()
        return (f"{r} Avisale al usuario que apagaste tu micrófono para no "
                "confundir la música con su voz — que toque el mic del "
                "panel cuando quiera hablarte.")
    except Exception as e:
        log.warning("play_music: %s", e)
        return f"No pude buscar en YouTube: {e}"


# Playlists del usuario en YouTube Music: nombre → ID. Se aprende UNA vez
# (youtube_music_learn con el link) y de ahí en más watch?list=<ID>
# arranca a SONAR solo, sin clicks.
import os as _os

_PLAYLISTS_FILE = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
    "playlists_ytmusic.json")


def _playlists() -> dict:
    try:
        return json.load(open(_PLAYLISTS_FILE, encoding="utf-8"))
    except Exception:
        return {}


_NAVEGADORES = {"opera.exe", "opera_gx.exe", "chrome.exe", "msedge.exe",
                "firefox.exe", "brave.exe", "vivaldi.exe"}


def _audio_navegador() -> float:
    """Pico de audio real del navegador (pycaw): la prueba de que SUENA."""
    import time as _t
    try:
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
        pico = 0.0
        for s in AudioUtilities.GetAllSessions():
            try:
                if s.Process and s.Process.name().lower() in _NAVEGADORES:
                    m = s._ctl.QueryInterface(IAudioMeterInformation)
                    for _ in range(20):
                        pico = max(pico, m.GetPeakValue())
                        _t.sleep(0.05)
            except Exception:
                pass
        return pico
    except Exception:
        return -1.0   # sin pycaw: no se puede verificar


def _click_play():
    """Click en el ▶ del reproductor de YT Music (barra inferior izquierda,
    posición fija: ~133 px del borde izquierdo, ~45 px del inferior)."""
    import ctypes
    import time as _t
    import win32gui
    from tools.windows import _find_window, focus_hwnd
    h = _find_window("youtube music")
    if not h:
        return False
    focus_hwnd(h)
    _t.sleep(0.5)
    r = win32gui.GetWindowRect(h)
    u = ctypes.windll.user32
    u.SetCursorPos(r[0] + 133, r[3] - 45)
    _t.sleep(0.2)
    u.mouse_event(2, 0, 0, 0, 0)
    _t.sleep(0.06)
    u.mouse_event(4, 0, 0, 0, 0)
    return True


@kloom_tool("youtube_music", "Reproduce una playlist DEL USUARIO en YouTube Music y VERIFICA que suene (mide el audio del navegador). Para 'poné mi playlist X'. Si no la conozco, la respuesta te dice qué pedirle al usuario. NUNCA uses play_music ni open_url para playlists.", {"nombre": str})
async def youtube_music(args):
    import asyncio
    nombre = args["nombre"].strip().lower()
    lisas = _playlists()
    for guardado, pid in lisas.items():
        if nombre in guardado or guardado in nombre:
            _open(f"https://music.youtube.com/watch?list={pid}")
            await asyncio.sleep(7)   # que cargue el reproductor
            if await asyncio.to_thread(_audio_navegador) > 0.01:
                _avisar_musica()
                return (f"Playlist '{guardado}' sonando, verificado. "
                        "Avisale al usuario que apagaste tu micrófono para "
                        "no confundir la música con su voz — que toque el "
                        "mic del panel para hablarte.")
            if not await asyncio.to_thread(_click_play):
                return ("Abrí la playlist pero no encontré la ventana de "
                        "YouTube Music para darle play. Contale al usuario.")
            await asyncio.sleep(1.5)
            pico = await asyncio.to_thread(_audio_navegador)
            if pico > 0.01:
                _avisar_musica()
                return (f"Playlist '{guardado}' SONANDO, verificado con el "
                        "medidor de audio. Avisale al usuario que apagaste "
                        "tu micrófono para no confundir la música con su "
                        "voz — que toque el mic del panel para hablarte.")
            if pico < 0:
                return (f"Playlist '{guardado}' abierta y le di play, pero "
                        "no pude verificar el audio. Preguntale al usuario "
                        "si suena.")
            return (f"Abrí la playlist '{guardado}' y cliqueé play, pero el "
                    "medidor dice que NO está sonando. Decíselo al usuario "
                    "tal cual — no digas que suena.")
    conocidas = ", ".join(lisas) or "ninguna todavía"
    return (f"No tengo aprendida la playlist '{args['nombre']}' "
            f"(conozco: {conocidas}). Pedile al usuario que abra la "
            "playlist una vez en YouTube Music, copie el link y te lo "
            "pegue en el panel — con eso llamás youtube_music_learn y "
            "queda aprendida para siempre. NO abras búsquedas a ciegas.")


@kloom_tool("youtube_music_learn", "Aprende una playlist del usuario para siempre: recibe el nombre y el LINK que el usuario pegó (music.youtube.com/...list=XXXX). Después youtube_music la reproduce sola.", {"nombre": str, "url": str})
async def youtube_music_learn(args):
    import re as _re
    m = _re.search(r"[?&]list=([\w-]+)", args["url"])
    if not m:
        return "Ese link no tiene '?list=' — pedile el link de la playlist."
    lisas = _playlists()
    lisas[args["nombre"].strip().lower()] = m.group(1)
    json.dump(lisas, open(_PLAYLISTS_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return (f"Aprendida '{args['nombre']}'. Ya puedo reproducirla "
            "directo cuando la pida.")


@kloom_tool("web_answer", "Busca en la web y DEVUELVE los resultados como texto (títulos y resúmenes) para responder una pregunta, sin abrir el navegador. Usar para preguntas de datos: 'quién ganó X', 'cuánto sale Y'.", {"query": str})
async def web_answer(args):
    import asyncio
    import html as _html
    import re as _re
    try:
        # lite.duckduckgo: la variante html.duckduckgo devuelve challenge
        # anti-bot para urllib; la lite sirve HTML plano.
        page = await asyncio.to_thread(
            _fetch, "https://lite.duckduckgo.com/lite/?q="
            + urllib.parse.quote_plus(args["query"]))
        titulos = _re.findall(
            r"class=['\"]result-link['\"][^>]*>(.*?)</a>", page, _re.S)
        snippets = _re.findall(
            r"class=['\"]result-snippet['\"][^>]*>(.*?)</td>", page, _re.S)
        limpio = lambda s: _html.unescape(_re.sub(r"<[^>]+>", "", s)).strip()
        lineas = []
        for t, s in list(zip(titulos, snippets))[:3]:
            lineas.append(f"{limpio(t)}: {limpio(s)}")
        return "\n".join(lineas) or "La búsqueda no devolvió resultados."
    except Exception as e:
        log.warning("web_answer: %s", e)
        return f"No pude buscar: {e}"


TOOLS = [open_url, web_search, youtube_search, play_music, youtube_music,
         youtube_music_learn, web_answer]
