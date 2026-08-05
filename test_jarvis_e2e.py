"""E2E real del driver OpenAI-compat contra Ollama local: abre y cierra
notepad DE VERDAD, y el switch por voz con y sin key."""
import asyncio
import logging
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s",
                    stream=sys.stdout)


def notepad_windows():
    import win32gui
    hits = []

    def cb(h, _):
        t = win32gui.GetWindowText(h)
        if win32gui.IsWindowVisible(h) and t and (
                "bloc de notas" in t.lower() or "notepad" in t.lower()):
            hits.append(t)

    win32gui.EnumWindows(cb, None)
    return hits


async def main():
    from kloom import load_config, parse_switch
    from cerebro import crear_cerebro
    from cerebro_jarvis import CerebroJarvis
    from tools import browser, claude_code, media, windows
    cfg = load_config()
    tools = windows.TOOLS + claude_code.TOOLS + browser.TOOLS + media.TOOLS

    # --- agent loop contra Ollama, efectos reales
    c = crear_cerebro(cfg, tools, brain="ollama")
    assert isinstance(c, CerebroJarvis)
    await c.connect()

    print(">>> abrí el bloc de notas")
    print("<<<", await c.ask("abrí el bloc de notas"))
    await asyncio.sleep(1.5)
    assert notepad_windows(), "notepad no abrió"
    print("notepad abierto ✓")

    print(">>> ahora cerralo")
    print("<<<", await c.ask("ahora cerralo"))
    await asyncio.sleep(1.5)
    assert not notepad_windows(), f"notepad sigue abierto: {notepad_windows()}"
    print("notepad cerrado ✓")
    await c.close()

    # --- parser del switch: positivos (incl. dictado sucio) y negativos
    for frase, esperado in [
        ("cambiá el cerebro a groq", "groq"),
        ("usá el cerebro claude", "claude"),
        ("poné el cerebro a ollama", "ollama"),
        ("que cambies tu cerebro a Grok", "groq"),
        ("cambiá el cerebro a cloud", "claude"),
        ("pasá el cerebro a olama", "ollama"),
        ("cambiá el cerebro a gémini", "gemini"),
        ("poné a claude a trabajar en el bot", None),
        ("usá claude code para esto", None),
        ("decile a claude que revise", None),
        ("cambiá el cerebro a pepito", None),
    ]:
        got = parse_switch(frase)
        assert got == esperado, f"{frase!r}: esperaba {esperado}, dio {got}"
    print("switch parser ✓")

    # --- switch a proveedor sin key: el driver ni se crea
    os.environ.pop("GROQ_API_KEY", None)
    try:
        crear_cerebro(cfg, tools, brain="groq")
        raise AssertionError("groq sin key debía fallar")
    except RuntimeError as e:
        assert "GROQ_API_KEY" in str(e)
    print("switch sin key falla limpio ✓")

    print("\ntest_jarvis_e2e OK ✓")


asyncio.run(main())
