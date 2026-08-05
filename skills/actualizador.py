"""Skill Actualizador: mantiene HARVIS al día. Un watcher chequea el repo
una vez por día y avisa si hay versión nueva; "harvis, actualizate" hace
git pull + pip install y se reinicia solo. Requiere instalación vía git
clone (un ZIP no tiene .git y la tool lo explica)."""
import asyncio
import logging
import os
import subprocess
import sys

from registry import kloom_tool

log = logging.getLogger("kloom.skills.actualizador")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROMPT = ("Actualizador: si el usuario pide 'actualizate' / 'buscá "
          "actualizaciones', usá harvis_update. Avisás solo cuando hay "
          "versión nueva (watcher diario).")


def _git(*args, timeout=120):
    r = subprocess.run(["git", *args], cwd=BASE, capture_output=True,
                       text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


@kloom_tool("harvis_update", "Actualiza HARVIS a la última versión del repo (git pull + dependencias) y se reinicia solo. Usar cuando pidan 'actualizate' o instalar la actualización.", {})
async def harvis_update(args):
    def _do():
        if not os.path.isdir(os.path.join(BASE, ".git")):
            return ("Esta instalación no vino por git clone, así que no "
                    "puedo actualizarme solo. Bajá la última versión del "
                    "repo a mano.")
        rc, out = _git("pull", "--ff-only")
        if rc != 0:
            return f"No pude actualizar: {out[:150]}"
        if "Already up to date" in out or "Ya está actualizado" in out:
            return "Ya estoy en la última versión, señor."
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r",
             os.path.join(BASE, "requirements.txt")],
            cwd=BASE, capture_output=True, timeout=600)
        return "__RESTART__"

    r = await asyncio.to_thread(_do)
    if r != "__RESTART__":
        return r
    # Nueva instancia a los 15 s; esta muere a los 12 (con la respuesta ya
    # hablada). Los hijos de cmd sobreviven a la muerte del padre.
    subprocess.Popen(
        ["cmd", "/c",
         f'timeout /t 15 /nobreak >nul & start "" /min "{os.path.join(BASE, "kloom.cmd")}"'],
        creationflags=subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NEW_PROCESS_GROUP)
    asyncio.get_running_loop().call_later(12, os._exit, 0)
    log.info("actualizado; reinicio programado")
    return "Listo señor, me actualicé. Me reinicio en unos segundos."


TOOLS = [harvis_update]


async def WATCHER(avisar, cfg):
    """Chequeo diario: fetch + cuántos commits estamos atrás de origin."""
    if not os.path.isdir(os.path.join(BASE, ".git")):
        log.info("actualizador: instalación sin git, no chequeo")
        return
    avisado = None
    await asyncio.sleep(180)   # no molestar durante el arranque
    while True:
        try:
            def _check():
                _git("fetch", "--quiet", "origin", timeout=90)
                _, n = _git("rev-list", "--count", "HEAD..origin/main")
                _, sha = _git("rev-parse", "origin/main")
                return int(n or 0), sha
            n, sha = await asyncio.to_thread(_check)
            if n > 0 and sha != avisado:
                avisado = sha
                await avisar(
                    "Señor, hay una actualización de HARVIS disponible. "
                    "Dígame «actualizate» cuando quiera instalarla.")
        except Exception:
            log.warning("actualizador: chequeo falló", exc_info=True)
        await asyncio.sleep(24 * 3600)
