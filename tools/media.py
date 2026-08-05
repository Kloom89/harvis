"""Teclas multimedia y sistema: música, volumen, hora, clima."""
import datetime
import urllib.parse
import urllib.request

from registry import kloom_tool
from teclado import MEDIA, media


@kloom_tool("media_key", "Controla la reproducción de medios del sistema. Acciones: play, pause, next, previous, volume_up, volume_down, mute.", {"action": str})
async def media_key(args):
    action = args["action"]
    if action not in MEDIA:
        return f"Acción desconocida '{action}'. Válidas: {', '.join(MEDIA)}."
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


@kloom_tool("get_weather", "Clima actual de una ciudad (por defecto la local).", {"city": (str, "")})
async def get_weather(args):
    city = args.get("city") or ""
    try:
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=%C,+%t,+humedad+%h&lang=es"
        with urllib.request.urlopen(url, timeout=6) as r:
            return r.read().decode("utf-8")
    except Exception as e:
        return f"No pude consultar el clima: {e}"


TOOLS = [media_key, get_time, get_weather]
