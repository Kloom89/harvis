"""Observabilidad por turno: cada interacción es un Turn con id, y todos
los módulos (loop, drivers, tools) le cuelgan eventos vía contextvar —
sin pasarse el id a mano. Un bug "irreproducible" queda como una secuencia
concreta en turnos.jsonl.
"""
import contextvars
import json
import logging
import os
import time
import uuid

log = logging.getLogger("kloom.trazas")

_DIR = os.path.dirname(os.path.abspath(__file__))
TRACE_FILE = os.path.join(_DIR, "turnos.jsonl")
MAX_BYTES = 5 * 1024 * 1024   # rota: se conserva una generación anterior

_turno = contextvars.ContextVar("turno", default=None)


def nuevo_turno(origen: str, texto: str) -> str:
    """origen: voz | hud | telegram | reflexion | watcher."""
    tid = uuid.uuid4().hex[:8]
    _turno.set({"id": tid, "t0": time.monotonic()})
    ev("comando", origen=origen, texto=texto[:200])
    return tid


def ev(tipo: str, **datos):
    """Evento del turno actual (o global si no hay turno)."""
    ctx = _turno.get()
    reg = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "turno": ctx["id"] if ctx else "-",
        "ms": round((time.monotonic() - ctx["t0"]) * 1000) if ctx else 0,
        "ev": tipo,
        **datos,
    }
    try:
        if os.path.exists(TRACE_FILE) and \
                os.path.getsize(TRACE_FILE) > MAX_BYTES:
            os.replace(TRACE_FILE, TRACE_FILE + ".1")
        with open(TRACE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")
    except Exception:
        log.debug("traza perdida", exc_info=True)


def cerrar_turno(reply: str = "", error: str = ""):
    ev("fin", chars=len(reply), error=error or None)
    _turno.set(None)
