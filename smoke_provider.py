"""Smoke test manual por proveedor: pide UNA tool y verifica que se ejecutó.
Correr al cargar la key de un proveedor nuevo:  python smoke_provider.py groq
"""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


async def main():
    from kloom import load_config
    from cerebro import crear_cerebro
    import tools.media as media
    from registry import kloom_tool

    provider = sys.argv[1] if len(sys.argv) > 1 else "ollama"
    llamadas = []

    @kloom_tool("get_time", "Hora y fecha actuales.", {})
    async def get_time(args):
        llamadas.append(args)
        return await media.get_time.handler(args)

    c = crear_cerebro(load_config(), [get_time], brain=provider)
    await c.connect()
    reply = await c.ask("qué hora es? usá la herramienta")
    print(f"{provider} respondió: {reply}")
    assert llamadas, f"{provider} no llamó la tool"
    await c.close()
    print(f"smoke {provider} OK ✓")


asyncio.run(main())
