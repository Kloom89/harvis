"""Teclas multimedia y sistema: música, volumen, hora, clima."""
import datetime
import urllib.parse
import urllib.request

from registry import kloom_tool
from teclado import MEDIA, media


@kloom_tool("media_key", "Controla la reproducción de medios del sistema. Acciones: play, pause, next, previous, volume_up, volume_down, mute.", {"action": str})
async def media_key(args):
    import asyncio
    action = args["action"]
    if action not in MEDIA:
        return f"Acción desconocida '{action}'. Válidas: {', '.join(MEDIA)}."
    if action in ("play", "pause", "next", "previous"):
        # con varias pestañas de música, la tecla global va a la sesión
        # equivocada: atajo directo a la ventana de YouTube Music primero
        from tools.browser import control_musica
        if await asyncio.to_thread(control_musica, action):
            return "Hecho (en YouTube Music)."
    times = 5 if action in ("volume_up", "volume_down") else 1
    for _ in range(times):
        media(action)
    return "Hecho."


@kloom_tool("get_time", "Hora y fecha actuales.", {})
async def get_time(args):
    now = datetime.datetime.now()
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    return (f"{dias[now.weekday()]} {now.day}/{now.month}/{now.year}, "
            f"{now.hour:02d}:{now.minute:02d}")


@kloom_tool("get_weather", "Clima actual y pronóstico de 3 días de una ciudad (por defecto la local).", {"city": (str, "")})
async def get_weather(args):
    import json
    city = args.get("city") or ""
    try:
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1&lang=es"
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))

        def desc(bloque):
            return ((bloque.get("lang_es") or [{}])[0].get("value")
                    or bloque["weatherDesc"][0]["value"]).strip()

        cur = data["current_condition"][0]
        out = [f"Ahora: {desc(cur)}, {cur['temp_C']} grados "
               f"(sensación {cur['FeelsLikeC']}), humedad {cur['humidity']}%"]
        dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        for d in data["weather"][:3]:
            fecha = datetime.date.fromisoformat(d["date"])
            # bloque horario del mediodía como representativo del día
            hh = d["hourly"][4] if len(d["hourly"]) > 4 else d["hourly"][0]
            out.append(f"{dias[fecha.weekday()]} {fecha.day}: {desc(hh)}, "
                       f"{d['mintempC']} a {d['maxtempC']} grados, "
                       f"lluvia {hh['chanceofrain']}%")
        return ". ".join(out)
    except Exception as e:
        return f"No pude consultar el clima: {e}"


TOOLS = [media_key, get_time, get_weather]
