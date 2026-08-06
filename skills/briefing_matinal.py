"""Skill Briefing Matinal: apagado por default. Se prende desde el HUD
(botón SKILLS) o en config.yaml → briefing: activo/hora/dias/saltar_feriados.
Los días elegidos, a la hora configurada, HARVIS te da los buenos días con
sustancia: clima, timers pendientes y mensajes de Teams sin leer.
Lo que falle (Teams cerrado, sin internet) se saltea sin drama."""
import asyncio
import datetime
import logging

log = logging.getLogger("kloom.skills.briefing")

CHEQUEO = 20          # cada cuánto mira el reloj (y relee la config del HUD)
VENTANA = 60 * 60     # si arranca más tarde que esto, el briefing ya venció
DIAS_DEF = [0, 1, 2, 3, 4]   # lunes a viernes; 0=lunes … 6=domingo

PROMPT = (
    "Briefing matinal: si está activo, los días y la hora que el usuario "
    "configuró das un parte con clima, pendientes y Teams. Si el usuario "
    "pide 'el briefing' a mano, armalo igual con get_weather, list_timers "
    "y teams_unread.")

_FERIADOS: dict[int, set[str]] = {}


def _hora(b: dict) -> tuple[int, int]:
    try:
        hh, mm = (int(x) for x in str(b.get("hora", "09:00")).split(":")[:2])
        return (hh, mm) if 0 <= hh < 24 and 0 <= mm < 60 else (9, 0)
    except Exception:
        return 9, 0


def _dias(b: dict) -> set[int]:
    if "dias" not in b:
        return set(DIAS_DEF)
    try:   # lista vacía = ningún día (destildar todo en el HUD lo apaga)
        return {int(x) for x in (b["dias"] or []) if 0 <= int(x) <= 6}
    except Exception:
        return set(DIAS_DEF)


def _toca(b: dict, ahora: datetime.datetime, ultimo) -> bool:
    """¿Corresponde el briefing ahora? (el feriado se chequea aparte: pide red)."""
    if not b.get("activo") or ahora.date() == ultimo:
        return False
    if ahora.weekday() not in _dias(b):
        return False
    hh, mm = _hora(b)
    objetivo = ahora.replace(hour=hh, minute=mm, second=0, microsecond=0)
    # Si la PC arrancó mucho después, el "buen día" ya no va.
    return objetivo <= ahora < objetivo + datetime.timedelta(seconds=VENTANA)


def _bajar_feriados(ano: int) -> set[str]:
    import json
    import urllib.request
    url = f"https://api.argentinadatos.com/v1/feriados/{ano}"
    # sin User-Agent propio la API contesta 403 (Cloudflare bloquea urllib)
    req = urllib.request.Request(url, headers={"User-Agent": "harvis/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return {f["fecha"] for f in json.load(r)}


async def _es_feriado(dia: datetime.date) -> bool:
    """Feriados nacionales AR (api.argentinadatos.com, sin API key), cacheados
    por año. Sin internet devuelve False: mejor hablar de más que comerse el
    briefing por una falla de red."""
    if dia.year not in _FERIADOS:
        try:
            _FERIADOS[dia.year] = await asyncio.to_thread(
                _bajar_feriados, dia.year)
        except Exception:
            log.warning("briefing: no pude bajar feriados %s", dia.year)
            return False
    return dia.isoformat() in _FERIADOS[dia.year]


async def WATCHER(avisar, cfg):
    ultimo = None                      # día del último briefing dado
    while True:
        await asyncio.sleep(CHEQUEO)
        b = cfg.get("briefing") or {}   # releído: el HUD lo edita en vivo
        ahora = datetime.datetime.now()
        if not _toca(b, ahora, ultimo):
            continue
        ultimo = ahora.date()           # uno por día, pase lo que pase abajo
        if b.get("saltar_feriados") and await _es_feriado(ultimo):
            log.info("briefing: hoy es feriado, no hablo")
            continue

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
