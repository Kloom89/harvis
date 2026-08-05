"""Timers y alarmas con aviso por voz. Viven en memoria del proceso;
kloom.py setea ANNOUNCE (async) para hablar cuando vencen."""
import asyncio
import datetime
import itertools
import logging

from registry import kloom_tool

log = logging.getLogger("kloom.tools.timers")

ANNOUNCE = None  # async (text) -> None; kloom.py lo setea al arrancar
_seq = itertools.count(1)
PENDIENTES: dict[int, dict] = {}


async def _fire(tid: int, delay: float, aviso: str):
    try:
        await asyncio.sleep(delay)
        PENDIENTES.pop(tid, None)
        if ANNOUNCE:
            await ANNOUNCE(aviso)
    except asyncio.CancelledError:
        pass


def _schedule(delay: float, etiqueta: str, kind: str, aviso: str) -> int:
    tid = next(_seq)
    due = datetime.datetime.now() + datetime.timedelta(seconds=delay)
    task = asyncio.get_running_loop().create_task(_fire(tid, delay, aviso))
    PENDIENTES[tid] = {"kind": kind, "etiqueta": etiqueta, "due": due,
                       "task": task}
    log.info("%s #%s a las %s (%s)", kind, tid, due.strftime("%H:%M:%S"),
             etiqueta or "sin etiqueta")
    return tid


@kloom_tool("set_timer", "Pone un timer que avisa por voz al vencer. Minutos admite decimales: 0.5 es medio minuto.", {"minutos": float, "etiqueta": (str, "")})
async def set_timer(args):
    minutos = float(args["minutos"])
    if minutos <= 0:
        return "El timer necesita minutos mayores a cero."
    etiqueta = (args.get("etiqueta") or "").strip()
    aviso = (f"Señor, terminó el timer de {etiqueta}." if etiqueta
             else "Señor, terminó el timer.")
    _schedule(minutos * 60, etiqueta, "timer", aviso)
    if minutos < 1:
        return f"Timer puesto: {round(minutos * 60)} segundos."
    return f"Timer puesto: {minutos:g} minutos."


@kloom_tool("set_alarm", "Programa un aviso por voz a una hora dada (formato 24 hs). Si la hora ya pasó hoy, queda para mañana.", {"hora": int, "minuto": int, "etiqueta": (str, "")})
async def set_alarm(args):
    hora, minuto = int(args["hora"]), int(args["minuto"])
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        return "Hora inválida."
    ahora = datetime.datetime.now()
    due = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    if due <= ahora:
        due += datetime.timedelta(days=1)
    etiqueta = (args.get("etiqueta") or "").strip()
    aviso = (f"Señor, son las {hora}:{minuto:02d}. {etiqueta}." if etiqueta
             else f"Señor, son las {hora}:{minuto:02d}, la alarma que pidió.")
    _schedule((due - ahora).total_seconds(), etiqueta, "alarma", aviso)
    dia = "mañana" if due.date() != ahora.date() else "hoy"
    return f"Alarma puesta para las {hora}:{minuto:02d} de {dia}."


@kloom_tool("list_timers", "Lista los timers y alarmas pendientes.", {})
async def list_timers(args):
    if not PENDIENTES:
        return "No hay timers ni alarmas pendientes."
    lineas = []
    for tid, p in PENDIENTES.items():
        et = f" ({p['etiqueta']})" if p["etiqueta"] else ""
        lineas.append(f"{p['kind']} para las {p['due'].strftime('%H:%M')}{et}")
    return ". ".join(lineas)


@kloom_tool("cancel_timers", "Cancela todos los timers y alarmas pendientes.", {})
async def cancel_timers(args):
    if not PENDIENTES:
        return "No había nada que cancelar."
    n = len(PENDIENTES)
    for p in PENDIENTES.values():
        p["task"].cancel()
    PENDIENTES.clear()
    return f"Cancelados: {n}."


TOOLS = [set_timer, set_alarm, list_timers, cancel_timers]
