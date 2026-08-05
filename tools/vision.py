"""Ojos de HARVIS: captura la pantalla a PNG. El cerebro Claude después la
LEE con su tool Read (entiende imágenes); los otros cerebros al menos saben
qué ventanas hay por list_windows."""
import asyncio
import datetime
import glob
import logging
import os

from registry import kloom_tool

log = logging.getLogger("kloom.tools.vision")

_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "screenshots")
MAX_GUARDADAS = 10
# JPEG q80 a 1600px ≈ 150-250 KB: entra holgado en el buffer del SDK y
# alcanza de sobra para leer texto de pantalla.
ANCHO_MAX = 1600


@kloom_tool("take_screenshot", "Captura la pantalla completa y devuelve la ruta del PNG. Después LEELA con Read para ver qué hay (solo funciona con el cerebro Claude). Usar cuando piden 'qué ves', 'leé este error', o para VERIFICAR el resultado de una acción.", {})
async def take_screenshot(args):
    def _cap():
        from PIL import ImageGrab
        os.makedirs(_DIR, exist_ok=True)
        img = ImageGrab.grab(all_screens=False).convert("RGB")
        if img.width > ANCHO_MAX:
            img = img.resize((ANCHO_MAX, int(img.height * ANCHO_MAX / img.width)))
        path = os.path.join(
            _DIR, f"pantalla-{datetime.datetime.now():%H%M%S}.jpg")
        img.save(path, quality=80)
        viejas = sorted(glob.glob(os.path.join(_DIR, "*.*")))
        for v in viejas[:-MAX_GUARDADAS]:
            os.remove(v)
        return path
    try:
        return await asyncio.to_thread(_cap)
    except Exception as e:
        log.exception("screenshot falló")
        return f"No pude capturar la pantalla: {e}"


TOOLS = [take_screenshot]
