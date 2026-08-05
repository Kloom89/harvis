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


@kloom_tool("play_music", "Reproduce música o un video: abre directo el primer resultado de YouTube (empieza a sonar solo). Usar cuando piden 'poné música de X' o 'poné X'.", {"query": str})
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


TOOLS = [open_url, web_search, youtube_search, play_music, web_answer]
