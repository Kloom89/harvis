"""Memoria persistente de HARVIS — aprende de las interacciones.

Lección del observatorio Automaton: el agente NUNCA edita su misión (el
system prompt de config.yaml es intocable); lo aprendido vive en un archivo
APARTE, aditivo, con tope, que el usuario puede leer y corregir a mano.
"""
import asyncio
import datetime
import difflib
import json
import logging
import os
import re

from registry import kloom_tool

log = logging.getLogger("kloom.tools.memoria")

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEMFILE = os.path.join(_DIR, "memoria.md")
HISTFILE = os.path.join(_DIR, "historial.jsonl")
MAX_HECHOS = 150      # tope: los más viejos se caen al superarlo
CONTEXT_TURNS = 8     # últimos intercambios que entran al contexto

# "- [fecha]" o "- [fecha, origen]" al inicio de cada hecho
_PREFIJO = re.compile(r"^- \[[^\]]*\]\s*")
# Dos hechos así de parecidos son el mismo tema: el nuevo REEMPLAZA al
# viejo en vez de acumularse (versiones actualizadas o contradicciones
# con la misma redacción).
UMBRAL_MISMO_TEMA = 0.72


def _texto_hecho(linea: str) -> str:
    return _PREFIJO.sub("", linea).strip()


def _leer_hechos() -> list[str]:
    if not os.path.exists(MEMFILE):
        return []
    with open(MEMFILE, encoding="utf-8") as f:
        return [l.rstrip("\n") for l in f if l.strip()]


def _guardar_hechos(hechos: list[str]):
    with open(MEMFILE, "w", encoding="utf-8") as f:
        f.write("\n".join(hechos[-MAX_HECHOS:]) + "\n")


@kloom_tool("remember", "Guarda un hecho aprendido del usuario para siempre (preferencias, correcciones, datos personales, cómo le gusta que hagas las cosas). Usala apenas el usuario te corrija o revele algo que convenga recordar. origen: 'dicho' si el usuario lo dijo con sus palabras, 'inferido' si es una deducción tuya.", {"hecho": str, "origen": (str, "dicho")})
async def remember(args):
    hecho = args["hecho"].strip()
    if not hecho:
        return "No había nada que recordar."
    if len(hecho) > 300:
        hecho = hecho[:300]
    origen = ("inferido" if str(args.get("origen", "")).strip().lower()
              == "inferido" else "dicho")
    hechos = _leer_hechos()
    linea = f"- [{datetime.date.today().isoformat()}, {origen}] {hecho}"
    # ¿Ya hay un hecho del mismo tema? → reemplazar, no acumular.
    mejor_i, mejor_r = None, 0.0
    nuevo = hecho.lower()
    for i, h in enumerate(hechos):
        r = difflib.SequenceMatcher(None, nuevo,
                                    _texto_hecho(h).lower()).ratio()
        if r > mejor_r:
            mejor_i, mejor_r = i, r
    if mejor_i is not None and mejor_r >= UMBRAL_MISMO_TEMA:
        viejo = _texto_hecho(hechos[mejor_i])
        hechos[mejor_i] = linea
        await asyncio.to_thread(_guardar_hechos, hechos)
        log.info("memoria ~: %s (pisó: %s)", hecho, viejo)
        return f"Anotado, señor (reemplaza lo que tenía: '{viejo}')."
    hechos.append(linea)
    await asyncio.to_thread(_guardar_hechos, hechos)
    log.info("memoria + (%s): %s", origen, hecho)
    return "Anotado, señor."


@kloom_tool("forget", "Borra de la memoria los hechos que contengan el texto dado. Usar cuando el usuario pide olvidar algo o corrige un hecho viejo.", {"texto": str})
async def forget(args):
    texto = args["texto"].strip().lower()
    if not texto:
        return "Decime qué olvidar."
    hechos = _leer_hechos()
    quedan = [h for h in hechos if texto not in h.lower()]
    borrados = len(hechos) - len(quedan)
    if not borrados:
        return f"No tenía nada anotado sobre '{texto}'."
    await asyncio.to_thread(_guardar_hechos, quedan)
    log.info("memoria -: %s (%s hechos)", texto, borrados)
    return f"Olvidado ({borrados})."


@kloom_tool("recall", "Lee todo lo que tenés anotado en la memoria de largo plazo.", {})
async def recall(args):
    hechos = _leer_hechos()
    return "\n".join(hechos) if hechos else "La memoria está vacía todavía."


TOOLS = [remember, forget, recall]


# ---------- historial de conversación (persistente entre reinicios) ----------

def append_historial(command: str, reply: str):
    try:
        with open(HISTFILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "yo": command, "harvis": reply,
            }, ensure_ascii=False) + "\n")
    except Exception:
        log.exception("no pude escribir historial")


def _historial_tail(n: int = CONTEXT_TURNS) -> list[dict]:
    if not os.path.exists(HISTFILE):
        return []
    with open(HISTFILE, encoding="utf-8") as f:
        lineas = f.readlines()[-n:]
    out = []
    for l in lineas:
        try:
            out.append(json.loads(l))
        except Exception:
            pass
    return out


def contexto_sistema() -> str:
    """Bloque para SUMAR al system prompt: memoria de hechos + últimos
    intercambios. La misión de config.yaml nunca se toca."""
    partes = []
    if hechos := _leer_hechos():
        partes.append("Lo que aprendiste del usuario hasta ahora "
                      "(tu memoria, escribís con remember/forget). "
                      "'dicho' = lo dijo él, vale como hecho; 'inferido' = "
                      "deducción tuya, tratala como hipótesis. Si un hecho "
                      "nuevo contradice uno anotado, borrá el viejo con "
                      "forget (o preguntale al usuario cuál vale) — nunca "
                      "dejes los dos:\n"
                      + "\n".join(hechos[-60:]))
    if hist := _historial_tail():
        lineas = [f"El usuario: {h['yo']}\nVos: {h['harvis']}" for h in hist]
        partes.append("Últimos intercambios (para continuidad, incluso "
                      "tras reinicios o cambio de cerebro):\n"
                      + "\n".join(lineas))
    return ("\n\n" + "\n\n".join(partes)) if partes else ""
