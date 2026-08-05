"""Regresión del wake word contra el corpus real. Si vuelve a fallar el
reconocimiento: sumar la frase nueva a POSITIVOS en wake_lab.py, recalibrar
con --barrido, y este test protege lo que ya andaba."""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from kloom import load_config, match_wake
from wake_lab import NEGATIVOS, POSITIVOS

cfg = load_config()

# Cada variante que Whisper escribió cuando el usuario dijo "Jarvis" debe
# reconocerse, y el comando debe salir limpio (sin el wake word).
ESPERADOS = {
    "Javi, ¿qué hora es?": "qué hora es?",
    "Harvey, ¿estás ahí?": "estás ahí?",
    "JARVIS": "",
    "harris": "",
    "Hola Harvís, ¿podés abrir la calculadora?": "podés abrir la calculadora?",
    "Jervis, ¿estás ahí?": "estás ahí?",
    "¿Estás ahí, Hergis?": "",
    "Carguis": "",
    "Jarvis, abrí el navegador.": "abrí el navegador.",
    "Chervis, pausá la música": "pausá la música",
}

mal = 0
for frase, comando in ESPERADOS.items():
    got = match_wake(frase, cfg)
    if got != comando:
        print(f"  FALLA {frase!r}: dio {got!r}, esperaba {comando!r}")
        mal += 1

perdidos = [p for p in POSITIVOS if match_wake(p, cfg) is None]
if perdidos:
    print("  NO reconoció:", perdidos)
    mal += len(perdidos)

espurios = [n for n in NEGATIVOS if n != "JARVIS!"
            and match_wake(n, cfg) is not None]
if espurios:
    print("  activó de más:", espurios)
    mal += len(espurios)

print(f"positivos {len(POSITIVOS)}  negativos {len(NEGATIVOS)}  fallas {mal}")
assert mal == 0
print("test_wake OK ✓")

# Un video de fondo que arranca con una palabra parecida ("Mari" mide 0.60
# contra "harvis") NO puede despertarlo: el parecido solo vale si la huella
# de voz confirma que habló él (el gate vive en el loop de kloom.py).
PARECIDOS = [
    "Mari, Mari, Mari, sentiste el terremoto ¿el terremoto no? y esta billeta",
    "hoy es mi cumple y la pasé bárbaro con toda la gente que quiero",
]
for frase in PARECIDOS:
    if match_wake(frase, cfg, fuzzy=False) is not None:
        print(f"  FALLA parecido {frase[:40]!r}: despierta sin huella")
        mal += 1
