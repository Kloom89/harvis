"""Skill Briefing Matinal: todos los días a la hora configurada
(config.yaml → briefing.hora, default 09:00) HARVIS te da los buenos días
con sustancia: clima, timers pendientes y mensajes de Teams sin leer.
Lo que falle (Teams cerrado, sin internet) se saltea sin drama."""
import asyncio
import datetime
import logging

log = logging.getLogger("kloom.skills.briefing")

PROMPT = (
    "Briefing matinal: todos los días a la hora configurada das un parte "
    "con clima, pendientes y Teams. Si el usuario pide 'el briefing' a mano, "
    "armalo igual con get_weather, list_timers y teams_unread.")


async def WATCHER(avisar, cfg):
    hora = str((cfg.get("briefing") or {}).get("hora", "09:00"))
    hh, mm = (int(x) for x in hora.split(":"))
    while True:
        ahora = datetime.datetime.now()
        objetivo = ahora.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if objetivo <= ahora:
            objetivo += datetime.timedelta(days=1)
        await asyncio.sleep((objetivo - ahora).total_seconds())

        partes = []
        try:
            from tools.media import get_weather
            partes.append(str(await get_weather.handler({})))
        except Exception:
            log.warning("briefing: clima falló", exc_info=True)
        try:
            from tools.timers import PENDIENTES
            if PENDIENTES:
                ets = [p["etiqueta"] or p["kind"]
                       for p in PENDIENTES.values()]
                partes.append("Pendientes: " + ", ".join(ets) + ".")
        except Exception:
            pass
        try:
            from tools.teams import teams_unread
            r = str(await teams_unread.handler({}))
            if r and "no hay" not in r.lower() and "no pude" not in r.lower():
                partes.append("En Teams: " + r[:300])
        except Exception:
            pass  # Teams cerrado a la mañana: sin novedades

        if not partes:
            partes = ["Sin novedades por ahora."]
        await avisar("Buen día, señor. " + " ".join(partes))
