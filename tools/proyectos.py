"""Status de los proyectos del usuario: lee la memoria persistente de Claude
(archivos project_*.md). Solo lectura."""
import asyncio
import glob
import logging
import os

from registry import kloom_tool

log = logging.getLogger("kloom.tools.proyectos")

MEMORY_DIR = ""   # kloom.py lo setea desde config tools.proyectos.memory_dir
MAX_CHARS = 2500  # el LLM resume para voz; no hace falta el archivo entero


def _buscar(nombre: str) -> str:
    if not MEMORY_DIR:
        return ("No hay carpeta de memoria configurada (config.yaml → "
                "tools.proyectos.memory_dir).")
    patron = nombre.lower().replace(" ", "*")
    hits = glob.glob(os.path.join(MEMORY_DIR, f"*{patron}*.md"))
    if not hits:
        # fallback: matchear por contenido del índice
        hits = [p for p in glob.glob(os.path.join(MEMORY_DIR, "project_*.md"))
                if nombre.lower() in os.path.basename(p).lower()]
    if not hits:
        return f"No tengo ningún proyecto que suene a '{nombre}'."
    cuerpos = []
    for p in hits[:2]:
        with open(p, encoding="utf-8", errors="replace") as f:
            cuerpos.append(f.read()[:MAX_CHARS])
    return "\n---\n".join(cuerpos)


@kloom_tool("project_status", "Estado de un proyecto del usuario: lee su memoria persistente (archivos project_*.md) y devuelve el texto para resumir en voz.", {"nombre": str})
async def project_status(args):
    return await asyncio.to_thread(_buscar, args["nombre"])


@kloom_tool("list_projects", "Lista los proyectos con memoria guardada, para saber de cuáles se puede pedir estado.", {})
async def list_projects(args):
    def _list():
        if not MEMORY_DIR:
            return ("No hay carpeta de memoria configurada (config.yaml → "
                    "tools.proyectos.memory_dir).")
        files = glob.glob(os.path.join(MEMORY_DIR, "project_*.md"))
        nombres = sorted(os.path.basename(p)[8:-3].replace("_", " ")
                         for p in files)
        return ", ".join(nombres) or "No hay proyectos guardados."
    return await asyncio.to_thread(_list)


TOOLS = [project_status, list_projects]
