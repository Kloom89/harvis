"""Memoria persistente: remember/forget/recall, tope, historial y que el
contexto entre al system prompt de un cerebro nuevo."""
import asyncio
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from tools import memoria

# archivos limpios para el test (se restauran al final)
BAK = {}
for f in (memoria.MEMFILE, memoria.HISTFILE):
    if os.path.exists(f):
        BAK[f] = open(f, encoding="utf-8").read()
        os.remove(f)


async def main():
    r = await memoria.remember.handler({"hecho": "el mate lo toma amargo"})
    assert "Anotado" in r
    r = await memoria.remember.handler({"hecho": "usa Spotify, no YouTube Music"})
    assert "Anotado" in r
    r = await memoria.recall.handler({})
    assert "amargo" in r and "Spotify" in r

    r = await memoria.forget.handler({"texto": "spotify"})
    assert "Olvidado (1)" in r, r
    r = await memoria.recall.handler({})
    assert "Spotify" not in r and "amargo" in r

    # historial + contexto para el system prompt
    memoria.append_historial("qué hora es", "Las diez, señor.")
    memoria.append_historial("abrí spotify", "Abierto.")
    ctx = memoria.contexto_sistema()
    assert "abrí spotify" in ctx and "amargo" in ctx

    # un cerebro nuevo (driver openai) nace con la memoria en el prompt
    from cerebro_jarvis import CerebroJarvis
    c = CerebroJarvis({"llm": {"system_prompt": "base"}}, "ollama",
                      {"base_url": "http://x/v1", "model": "m"}, [])
    assert "amargo" in c.messages[0]["content"]
    assert "abrí spotify" in c.messages[0]["content"]

    # tope: al pasar MAX_HECHOS quedan los últimos (al final: rompe el resto)
    for i in range(memoria.MAX_HECHOS + 10):
        await memoria.remember.handler({"hecho": f"hecho {i}"})
    hechos = memoria._leer_hechos()
    assert len(hechos) == memoria.MAX_HECHOS, len(hechos)
    assert f"hecho {memoria.MAX_HECHOS + 9}" in hechos[-1]

    print("test_memoria OK ✓")


try:
    asyncio.run(main())
finally:
    for f in (memoria.MEMFILE, memoria.HISTFILE):
        if os.path.exists(f):
            os.remove(f)
    for f, contenido in BAK.items():
        with open(f, "w", encoding="utf-8") as fh:
            fh.write(contenido)
