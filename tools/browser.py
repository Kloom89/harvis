"""Navegador: Chrome real vía CDP :9222 si está, si no el default del sistema."""
import json
import logging
import urllib.parse
import urllib.request
import webbrowser

from registry import kloom_tool

log = logging.getLogger("kloom.tools.browser")

CDP_PORT = 9222  # kloom.py lo pisa desde config.yaml


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


@kloom_tool("open_url", "Abre una URL en el navegador.", {"url": str})
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
        return _open(f"https://www.youtube.com/watch?v={m.group(1)}")
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


@kloom_tool("youtube_music", "Reproduce una playlist DEL USUARIO en YouTube Music: si está aprendida, EMPIEZA A SONAR sola. Para 'poné mi playlist X'. Si no la conozco, la respuesta te dice qué pedirle al usuario. NUNCA uses play_music para playlists.", {"nombre": str})
async def youtube_music(args):
    nombre = args["nombre"].strip().lower()
    lisas = _playlists()
    for guardado, pid in lisas.items():
        if nombre in guardado or guardado in nombre:
            r = _open(f"https://music.youtube.com/watch?list={pid}")
            return (f"{r} La playlist '{guardado}' arranca a sonar sola "
                    "(URL de reproducción directa). Confirmá al usuario "
                    "que ya está sonando.")
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
