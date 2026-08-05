import asyncio, sys, logging
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s", stream=sys.stdout)

async def main():
    from kloom import load_config
    from cerebro import CerebroClaude, crear_cerebro
    from tools import browser, claude_code, media, windows
    cfg = load_config()
    tools = windows.TOOLS + claude_code.TOOLS + browser.TOOLS + media.TOOLS
    c = crear_cerebro(cfg, tools, brain="claude")
    assert isinstance(c, CerebroClaude)
    await c.connect()
    for cmd in ["abrí el bloc de notas", "ahora cerralo"]:
        print(f"\n>>> {cmd}")
        print("<<<", await c.ask(cmd))
    await c.close()
    # verificación real
    import win32gui
    hits = []
    def cb(h,_):
        t = win32gui.GetWindowText(h)
        if win32gui.IsWindowVisible(h) and t and "bloc de notas" in t.lower(): hits.append(t)
    win32gui.EnumWindows(cb, None)
    print("\nventanas notepad tras cerrar:", hits or "ninguna ✓")
    assert not hits, hits

asyncio.run(main())
