"""Fase 3: web_answer (texto real de la web), play_music (videoId real),
project_status (memoria real), type_into_window (validación sin ventana)."""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main():
    from tools.browser import play_music, web_answer
    from tools.claude_code import type_into_window
    from tools.proyectos import list_projects, project_status

    r = await web_answer.handler({"query": "capital de Francia"})
    print("web_answer:", r[:120].replace("\n", " | "))
    assert "No pude" not in r and len(r) > 30, r
    assert "par" in r.lower(), f"esperaba París en: {r[:200]}"

    r = await project_status.handler({"nombre": "kloom os"})
    print("project_status:", r[:80])
    assert "JARVIS" in r, r[:200]
    r = await project_status.handler({"nombre": "proyectoinexistentexyz"})
    assert "No tengo" in r, r

    r = await list_projects.handler({})
    print("list_projects:", r[:100], "...")
    assert "kloom os" in r, r[:200]

    r = await type_into_window.handler(
        {"title": "ventana-que-no-existe-xyz", "text": "hola"})
    assert "No encontré" in r, r

    # play_music: solo resolver el videoId (no abrir el browser en el test)
    import re
    import urllib.parse
    from tools.browser import _fetch
    html = await asyncio.to_thread(
        _fetch, "https://www.youtube.com/results?search_query="
        + urllib.parse.quote_plus("soda stereo de musica ligera"))
    m = re.search(r'"videoId":"([\w-]{11})"', html)
    assert m, "YouTube no devolvió videoId (cambió el HTML?)"
    print("play_music videoId:", m.group(1))

    print("\ntest_fase3 OK ✓")


asyncio.run(main())
