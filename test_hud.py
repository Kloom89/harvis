"""Smoke del HUD con la arquitectura real: UI en el thread principal,
asyncio en un worker. Corre ~10 s y se cierra solo."""
import asyncio
import sys
import threading

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RECIBIDOS = []
FALLAS = []


async def checks():
    import hud as hud_mod
    from hud import Hud
    loop = asyncio.get_running_loop()
    hud = Hud({}, loop, lambda t: RECIBIDOS.append(t),
              ["claude", "ollama", "groq"])
    hud.start()

    # eventos ANTES de que cargue: deben encolarse y aplicarse al cargar
    hud.set_brain("claude")
    hud.heard("harvis, qué hora es")
    hud.reply("Son las diez, señor.")
    hud.set_state("thinking")

    for _ in range(60):
        await asyncio.sleep(0.25)
        if hud._ready.is_set():
            break
    try:
        assert hud._ready.is_set(), "el HUD nunca terminó de cargar"
        msgs = hud.window.evaluate_js(
            "document.querySelectorAll('.msg').length")
        estado = hud.window.evaluate_js("document.body.className")
        brains = hud.window.evaluate_js(
            "document.querySelectorAll('#brains button').length")
        print(f"msgs={msgs} estado={estado!r} brains={brains}")
        assert msgs == 2, f"esperaba 2 mensajes, hay {msgs}"
        assert "thinking" in estado, estado
        assert brains == 3, brains

        hud.send_text("abrí el bloc de notas")
        await asyncio.sleep(0.3)
        assert RECIBIDOS == ["abrí el bloc de notas"], RECIBIDOS
        assert hud.get_timers() == []
    except Exception as e:
        FALLAS.append(e)
    finally:
        hud_mod.shutdown()


def worker():
    asyncio.run(checks())


t = threading.Thread(target=worker, daemon=True)
t.start()

import hud as hud_mod

hud_mod.serve_main_thread(timeout=20)
t.join(timeout=5)

if FALLAS:
    print("FALLA:", FALLAS[0])
    sys.exit(1)
print("test_hud OK ✓")
