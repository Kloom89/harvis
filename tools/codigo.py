"""CodeGraph vía CLI: índice de código pre-armado de la carpeta de proyectos
del usuario (config tools.codigo.projects_dir), para cualquier cerebro.
Requiere el CLI `codegraph` instalado; sin config, las tools lo dicen."""
import asyncio
import logging
import os
import re
import subprocess

from registry import kloom_tool

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

log = logging.getLogger("kloom.tools.codigo")

PROYECTOS = ""   # kloom.py lo setea desde config tools.codigo.projects_dir
MAX_OUT = 2500


def _cg_sync(args: tuple, timeout: int) -> str:
    if not PROYECTOS:
        return ("CodeGraph no está configurado (config.yaml → "
                "tools.codigo.projects_dir).")
    try:
        r = subprocess.run(["cmd", "/c", "codegraph", *args], cwd=PROYECTOS,
                           capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "CodeGraph no respondió a tiempo."
    texto = _ANSI.sub("", (r.stdout + r.stderr)
                      .decode("utf-8", errors="replace")).strip()
    return (texto[:MAX_OUT] + "\n[recortado]") if len(texto) > MAX_OUT \
        else (texto or "(sin resultados)")


async def _cg(*args: str, timeout: int = 30) -> str:
    # subprocess.run en thread: create_subprocess_exec en Windows tira
    # "I/O operation on closed pipe" según el estado del loop.
    return await asyncio.to_thread(_cg_sync, args, timeout)


@kloom_tool("code_search", "Busca símbolos (funciones, clases, archivos) por nombre en TODOS los proyectos del usuario usando el índice CodeGraph. Instantáneo — usar esto en vez de grep.", {"termino": str})
async def code_search(args):
    return await _cg("query", args["termino"])


@kloom_tool("code_files", "Sin argumento: lista TODOS los proyectos del usuario (carpetas de primer nivel). Con 'proyecto': lista los archivos de esa carpeta (2 niveles).", {"proyecto": (str, "")})
async def code_files(args):
    def _listar():
        proy = (args.get("proyecto") or "").strip()
        if not proy:
            dirs = sorted(d for d in os.listdir(PROYECTOS)
                          if os.path.isdir(os.path.join(PROYECTOS, d))
                          and not d.startswith((".", "_", "$")))
            return "Proyectos: " + ", ".join(dirs)
        base = os.path.join(PROYECTOS, proy)
        if not os.path.isdir(base):
            return f"No existe la carpeta '{proy}'."
        lineas = []
        for raiz, dirs, files in os.walk(base):
            nivel = os.path.relpath(raiz, base).count(os.sep)
            dirs[:] = [d for d in dirs if not d.startswith(
                (".", "node_modules", "__pycache__"))] if nivel < 1 else []
            for f in files[:40]:
                lineas.append(os.path.relpath(os.path.join(raiz, f), base))
            if len(lineas) > 120:
                break
        return "\n".join(lineas[:120]) or "(carpeta vacía)"
    return await asyncio.to_thread(_listar)


@kloom_tool("code_callers", "Qué funciones llaman a un símbolo dado (grafo de llamadas de CodeGraph).", {"simbolo": str})
async def code_callers(args):
    return await _cg("callers", args["simbolo"])


@kloom_tool("code_context", "Arma contexto de código para una tarea o pregunta sobre un proyecto (CodeGraph elige los símbolos relevantes y devuelve un resumen).", {"tarea": str})
async def code_context(args):
    return await _cg("context", args["tarea"], timeout=60)


TOOLS = [code_search, code_files, code_callers, code_context]
