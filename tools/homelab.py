"""Homelab/servidor del usuario por SSH — SOLO LECTURA por voz. Un comando
mal transcripto por Whisper no puede romper nada: lo destructivo se rechaza
acá. Configurar en config.yaml → tools.homelab (host, vault); sin host las
tools responden "no configurado"."""
import asyncio
import logging
import re

from registry import kloom_tool

log = logging.getLogger("kloom.tools.homelab")

HOST = ""            # kloom.py lo setea desde config tools.homelab.host
TIMEOUT = 30
MAX_OUT = 2500

# Denylist de destrucción: si aparece, el comando NO se ejecuta por voz.
_PELIGRO = re.compile(
    r"\b(rm|mv|dd|mkfs|shutdown|reboot|poweroff|halt|kill|pkill|killall|"
    r"chmod|chown|truncate|fdisk|parted|umount|passwd|useradd|userdel|"
    r"iptables|ufw)\b|"
    r"\bdocker\s+(rm|stop|restart|kill|prune|compose\s+down)\b|"
    r"\bsystemctl\s+(stop|restart|disable|mask)\b|"
    r">{1,2}\s*[\w/.\"']")  # redirección a archivo; pipes de lectura OK


@kloom_tool("homelab_run", "Ejecuta un comando DE LECTURA en el homelab por SSH (docker ps, df -h, uptime, ls, cat, docker logs, tailscale status...). Lo destructivo está bloqueado: para eso delegá a Claude Code con send_to_claude.", {"comando": str})
async def homelab_run(args):
    if not HOST:
        return ("No hay homelab configurado (config.yaml → "
                "tools.homelab.host).")
    cmd = args["comando"].strip()
    if _PELIGRO.search(cmd):
        return ("Ese comando puede romper algo y por voz no lo ejecuto. "
                "Se lo podés delegar a Claude Code.")
    try:
        proc = await asyncio.create_subprocess_exec(
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
            HOST, cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
        texto = out.decode("utf-8", errors="replace").strip()
        if len(texto) > MAX_OUT:
            texto = texto[:MAX_OUT] + "\n[recortado]"
        return texto or "(sin salida, terminó bien)"
    except asyncio.TimeoutError:
        return "El homelab no respondió a tiempo."
    except Exception as e:
        log.warning("homelab_run: %s", e)
        return f"No pude conectar al homelab: {e}"


# Rutas ABSOLUTAS: '~' entre comillas simples no expande y termina creando
# un directorio literal "~" (pasó en el primer test).
VAULT = ""           # kloom.py lo setea desde config tools.homelab.vault
VAULTS = []          # tools.homelab.vault acepta una ruta o una lista
HARVIS_DIR = ""      # <vault>/HARVIS — la única carpeta donde puede escribir
_NOTA_OK = re.compile(r"^[\w\-. áéíóúñÁÉÍÓÚÑ]{1,60}\.md$")


async def _ssh(cmd: str, stdin: bytes | None = None,
               timeout: int = TIMEOUT) -> str:
    proc = await asyncio.create_subprocess_exec(
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", HOST, cmd,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
    return out.decode("utf-8", errors="replace").strip()


@kloom_tool("cerebro_search", "Busca en el vault de notas del usuario (Obsidian u otro, en su servidor: proyectos, personas, notas diarias). Devuelve archivos que matchean y un par de líneas de contexto.", {"termino": str})
async def cerebro_search(args):
    if not VAULT:
        return ("No hay vault configurado (config.yaml → "
                "tools.homelab.vault).")
    t = args["termino"].strip().replace("'", "")
    if not t:
        return "Decime qué buscar."
    roots = " ".join(VAULTS or [VAULT])
    try:
        cmd = (f"grep -rlim 20 '{t}' {roots} --include='*.md' | head -12; "
               f"echo ---; grep -rihm 12 '{t}' {roots} --include='*.md' "
               f"| head -12")
        out = await _ssh(cmd)
        return out[:MAX_OUT] if out.strip("-\n ") else f"Nada sobre '{t}' en Cerebro."
    except Exception as e:
        return f"No pude buscar en Cerebro: {e}"


@kloom_tool("cerebro_read", "Lee una nota del vault por su ruta (como la devuelve cerebro_search).", {"ruta": str})
async def cerebro_read(args):
    if not VAULT:
        return ("No hay vault configurado (config.yaml → "
                "tools.homelab.vault).")
    ruta = args["ruta"].strip().replace("'", "")
    if ".." in ruta or not ruta:
        return "Ruta inválida."
    if not any(ruta.startswith(v) for v in (VAULTS or [VAULT])):
        ruta = f"{VAULT}/{ruta.lstrip('~/')}"
    try:
        out = await _ssh(f"cat '{ruta}'")
        return out[:MAX_OUT] or "(nota vacía)"
    except Exception as e:
        return f"No pude leer la nota: {e}"


@kloom_tool("cerebro_note", "Escribe en TU carpeta del vault (<vault>/HARVIS/): tu perfil del usuario y observaciones. modo 'append' agrega al final, 'replace' reescribe. NUNCA podés tocar otras notas del vault.", {"nota": str, "contenido": str, "modo": (str, "append")})
async def cerebro_note(args):
    if not HARVIS_DIR:
        return ("No hay vault configurado (config.yaml → "
                "tools.homelab.vault).")
    nota = args["nota"].strip()
    contenido = args["contenido"].strip()
    modo = (args.get("modo") or "append").strip()
    if not _NOTA_OK.match(nota):
        return "Nombre de nota inválido (algo.md, sin rutas)."
    if not contenido:
        return "No había nada que escribir."
    if len(contenido) > 4000:
        contenido = contenido[:4000]
    op = ">>" if modo != "replace" else ">"
    try:
        # el contenido viaja por stdin (sin inyección de shell) y el OK se
        # VERIFICA: lección Automaton, un stub jamás fabrica éxito.
        out = await _ssh(
            f"mkdir -p '{HARVIS_DIR}' && cat {op} '{HARVIS_DIR}/{nota}' "
            f"&& echo __OK__",
            stdin=(contenido + "\n").encode("utf-8"))
        if "__OK__" not in out:
            return f"La escritura falló: {out[:200]}"
        return f"Escrito en {nota}."
    except Exception as e:
        return f"No pude escribir en Cerebro: {e}"


TOOLS = [homelab_run, cerebro_search, cerebro_read, cerebro_note]
