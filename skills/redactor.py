"""Skill Redactor: "harvis, modo redactor" → HARVIS anota TODO lo que digas
(sin mandarlo al cerebro, sin gastar tokens); "listo" cierra, y después
"pegalo" lo escribe donde quieras. El modo vive en kloom.py (toca el loop
de audio); estas tools operan sobre el texto juntado."""
import asyncio

from registry import kloom_tool

BUFFER: list[str] = []

PROMPT = (
    "Modo redactor: si el usuario dictó texto (modo redactor), con "
    "redactor_get lo leés, con redactor_paste lo pegás en la ventana "
    "activa o en la que te nombre (podés pasarle el texto MEJORADO si te "
    "pidió corregirlo), y redactor_clear lo descarta.")


@kloom_tool("redactor_get", "Devuelve el texto dictado en el último modo redactor, para leerlo, resumirlo o corregirlo.", {})
async def redactor_get(args):
    return "\n".join(BUFFER) if BUFFER else "No hay nada dictado."


@kloom_tool("redactor_paste", "Pega texto donde el usuario quiera: en la ventana cuyo título contenga 'titulo', o en la ventana activa si va vacío. Si 'texto' va vacío, pega el dictado tal cual; si no, pega ese texto (p.ej. el dictado corregido).", {"titulo": (str, ""), "texto": (str, "")})
async def redactor_paste(args):
    texto = (args.get("texto") or "").strip() or "\n".join(BUFFER)
    if not texto:
        return "No hay nada que pegar."
    titulo = (args.get("titulo") or "").strip()
    if titulo:
        from tools.claude_code import paste_to_window
        return await asyncio.to_thread(paste_to_window, titulo, texto, False)
    from teclado import paste
    await asyncio.to_thread(paste, texto, False)
    return "Pegado."


@kloom_tool("redactor_clear", "Descarta el texto dictado del modo redactor.", {})
async def redactor_clear(args):
    n = len(BUFFER)
    BUFFER.clear()
    return f"Descartadas {n} frases."


TOOLS = [redactor_get, redactor_paste, redactor_clear]
