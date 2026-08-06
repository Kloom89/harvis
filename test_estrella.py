"""El pedido de estrella sale UNA vez, recién pasada la semana, y nunca más."""
import asyncio
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from skills import estrella

estrella.CHEQUEO = 0.01          # el reloj de la prueba, no el de producción
avisos = []


async def avisar(t):
    avisos.append(t)


async def correr(dias_de_uso, cfg=None):
    avisos.clear()
    estrella._guardar({"primer_uso": time.time() - dias_de_uso * 86400})
    try:
        await asyncio.wait_for(estrella.WATCHER(avisar, cfg or {}), timeout=2)
    except asyncio.TimeoutError:
        pass
    return list(avisos)


async def main():
    recien = await correr(2)
    assert not recien, f"a los 2 días no debería pedir nada: {recien}"

    semana = await correr(9)
    assert len(semana) == 1, f"esperaba 1 pedido, hubo {len(semana)}"
    assert "estrella" in semana[0].lower(), semana[0]

    # el estado quedó marcado: una segunda corrida no vuelve a pedir
    otra = []
    async def avisar2(t):
        otra.append(t)
    try:
        await asyncio.wait_for(estrella.WATCHER(avisar2, {}), timeout=1)
    except asyncio.TimeoutError:
        pass
    assert not otra, f"volvió a pedirla: {otra}"

    apagado = await correr(30, {"estrella": {"dias": 0}})
    assert not apagado, f"con dias=0 tiene que quedarse callado: {apagado}"

    print("test_estrella OK ✓")


asyncio.run(main())
