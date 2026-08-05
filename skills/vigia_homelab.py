"""Skill Vigía del Homelab: watcher proactivo. Cada 15 minutos mira el
homelab (SSH solo-lectura) y AVISA solo si algo cambió para mal: un
contenedor que corría se cayó, o el disco de media pasó el 90%.
De noche (00-08) no habla — deja el aviso en el log y la traza.

Ejemplo de la API de watchers: exportar `WATCHER = async (avisar, cfg)`.
"""
import asyncio
import datetime
import logging
import re

log = logging.getLogger("kloom.skills.vigia")

INTERVALO = 15 * 60
DISCO_UMBRAL = 90            # % del disco vigilado (tools.homelab.disk_path)
HORA_SILENCIO = range(0, 8)  # no hablar de madrugada

PROMPT = (
    "Tenés un vigía del homelab corriendo de fondo: si un contenedor se cae "
    "o el disco pasa el 90%, avisás solo. Si el usuario pregunta por qué "
    "avisaste, los detalles están en el propio aviso.")


async def WATCHER(avisar, cfg):
    import tools.homelab as hl
    from trazas import ev
    if not hl.HOST:
        log.info("vigía: sin homelab configurado, no arranco")
        return
    disco_path = (cfg.get("tools", {}).get("homelab", {})
                  .get("disk_path", "/"))
    previos: set[str] | None = None
    while True:
        await asyncio.sleep(INTERVALO)
        try:
            out = await hl._ssh(
                "docker ps --format '{{.Names}}'; echo ---; "
                f"df --output=pcent {disco_path} | tail -1")
        except Exception as e:
            log.warning("vigía: homelab inalcanzable: %s", e)
            continue
        try:
            parte_docker, parte_disco = out.split("---")
            actuales = {l.strip() for l in parte_docker.splitlines()
                        if l.strip()}
            disco = int(re.search(r"(\d+)%", parte_disco).group(1))
        except Exception:
            log.warning("vigía: salida rara del homelab: %r", out[:200])
            continue

        avisos = []
        if previos is not None:
            caidos = previos - actuales
            if caidos:
                avisos.append("Señor, se cayeron contenedores del homelab: "
                              + ", ".join(sorted(caidos)) + ".")
        if disco >= DISCO_UMBRAL:
            avisos.append(f"El disco de media del homelab está al {disco} "
                          "por ciento, señor.")
        previos = actuales

        for a in avisos:
            ev("watcher", skill="vigia_homelab", aviso=a[:150])
            log.warning("vigía: %s", a)
            if datetime.datetime.now().hour not in HORA_SILENCIO:
                await avisar(a)
