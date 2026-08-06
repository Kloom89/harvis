"""Skill Estrella: a la semana de uso pide UNA vez una estrella en GitHub.

Una sola vez en la vida de la instalación, cuando el asistente ya demostró
que sirve — pedirla el primer día es pedirle un favor a un desconocido.
Se apaga con `estrella.dias: 0` en config.yaml.
"""
import asyncio
import json
import logging
import os
import time

log = logging.getLogger("kloom.skills.estrella")

ESTADO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "estrella.json")
REPO = "https://github.com/Kloom89/harvis"
DIAS = 7
CHEQUEO = 6 * 60 * 60          # cada 6 h alcanza para algo que pasa una vez

PROMPT = ("Si el usuario dice que quiere dejar la estrella, o pide ver el "
          "repositorio del proyecto, usá abrir_repo.")


def _estado() -> dict:
    try:
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _guardar(d: dict):
    try:
        with open(ESTADO, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        log.warning("no pude guardar %s", ESTADO)


from registry import kloom_tool


@kloom_tool("abrir_repo",
            "Abre en el navegador el repositorio de HARVIS en GitHub. Usar "
            "cuando el usuario quiera dejar la estrella, ver el código o "
            "compartir el proyecto.", {})
async def abrir_repo(args):
    from tools.browser import open_url
    await open_url.handler({"url": REPO})
    return "Abrí el repositorio en el navegador."


TOOLS = [abrir_repo]


async def WATCHER(avisar, cfg):
    dias = int((cfg.get("estrella") or {}).get("dias", DIAS))
    if dias <= 0:
        return
    est = _estado()
    if not est.get("primer_uso"):
        est["primer_uso"] = time.time()
        _guardar(est)
    while True:
        await asyncio.sleep(CHEQUEO)
        est = _estado()
        if est.get("pedida"):
            return                      # ya se pidió: el watcher se apaga
        pasados = (time.time() - est.get("primer_uso", time.time())) / 86400
        if pasados < dias:
            continue
        est["pedida"] = True
        _guardar(est)
        log.info("pedido de estrella (uso: %.1f días)", pasados)
        await avisar(
            f"Señor, hace {int(pasados)} días que me usa. Si le sirvo, "
            "déjeme una estrella en GitHub — es gratis y es lo único que "
            "pido. Dígame «abrí el repo» y se lo abro. No se lo vuelvo "
            "a mencionar.")
        return
