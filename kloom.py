"""KLOOM OS — JARVIS del usuario.

- "Jarvis, <comando>" → agente Claude con tools de la PC, responde hablando.
- F8 mantenido → dictado: lo dicho se pega en la ventana activa.
"""
import asyncio
import datetime
import logging
import os
import sys
import time

# Bajo pythonw (sin consola) stdout/stderr son None y cualquier print
# revienta; van a /dev/null. El log de verdad vive en kloom.log.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import yaml

import trazas
import stt as stt_mod  # importar primero: arregla el PATH de las DLL CUDA
from boca import Boca, beep_error, beep_listening, beep_ok, beep_wake
from cerebro import BRAINS, crear_cerebro
from oido import Oido

log = logging.getLogger("kloom")

import difflib
import re
import unicodedata


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


# "cambiá el cerebro a groq" — la palabra "cerebro" es obligatoria para no
# confundir con "poné a claude a trabajar" (que va a send_to_claude).
# Tolerante al dictado: "que cambies tu cerebro a Grok" también vale.
_SWITCH_RE = re.compile(
    r"(?:cambi|us|pon|pas)\w*\s+(?:el|tu|de|del|al)?\s*cerebro[,:]?\s*"
    r"(?:al?\s+)?(\w+)")

# Whisper escribe los proveedores como puede: Grok (xAI es más famoso que
# groq), cloud, olama...
_BRAIN_ALIAS = {"grok": "groq", "grock": "groq", "groc": "groq",
                "cloud": "claude", "claud": "claude", "clode": "claude",
                "olama": "ollama", "oyama": "ollama",
                "yemini": "gemini", "geminis": "gemini", "gimini": "gemini",
                "quimi": "kimi", "openia": "openai"}


def parse_switch(text: str) -> str | None:
    """Devuelve el proveedor pedido en un "cambiá el cerebro a X", o None.
    El nombre se resuelve exacto → alias → similitud (dictado sucio)."""
    m = _SWITCH_RE.search(sin_tildes(text))
    if not m:
        return None
    tok = m.group(1)
    if tok in BRAINS:
        return tok
    if tok in _BRAIN_ALIAS:
        return _BRAIN_ALIAS[tok]
    mejor = max(BRAINS,
                key=lambda b: difflib.SequenceMatcher(None, tok, b).ratio())
    if difflib.SequenceMatcher(None, tok, mejor).ratio() >= 0.6:
        return mejor
    return None

# --- Comandos de voz de los MODOS: editables desde el HUD (botón Skills).
# Los overrides viven en comandos.yaml (aparte, para no pisar config.yaml);
# aplicar_comandos() recompila los regex en caliente.
COMANDOS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "comandos.yaml")
DEFAULT_COMANDOS = {
    "charla": ["modo charla", "modo conversación", "modo chat", "hablemos",
               "charlemos", "conversemos"],
    "redactor": ["modo redactor", "modo dictado", "modo escritor",
                 "anotá todo"],
    "coach": ["modo coach", "modo entrenador", "necesito un coach"],
    "reiniciar": ["conversación nueva", "nueva conversación",
                  "empezá de cero", "empecemos de cero",
                  "borrá la conversación", "reiniciá la conversación"],
    "privacidad": ["privacidad", "dejá de escuchar", "dejá de escucharme",
                   "apagá el micrófono", "apagá el mic", "no escuches más"],
    "salir": ["listo", "basta", "chau", "cortala", "terminamos", "fin",
              "ya está", "modo normal", "gracias harvis", "gracias jarvis",
              "salí del modo", "cortá la charla"],
}

# Modo música: el mic queda vivo pero SOLO pasan órdenes de música — la
# letra de la canción no matchea nada y se ignora. Directas = tecla
# multimedia al toque, sin gastar cerebro.
# OJO con las letras de canciones: "para siempre", "otra vez", "play" son
# palabras de canción — las ambiguas van ANCLADAS (frase entera o con
# contexto de música); las inequívocas ("pausa", "siguiente") van sueltas.
MUSICA_DIRECTAS = [
    (re.compile(r"\bpausa\w*\b|\bdeten\w*\b|\bfrena\w*\b"
                r"|^para(la)?( la (musica|cancion))?$"), "pause"),
    (re.compile(r"^(dale )?play$|\breanuda\w*\b|^segui$"
                r"|\bcontinua la (musica|cancion)\b"), "play"),
    (re.compile(r"\bsiguiente\b|\bsaltea\w*\b|\bproxima\b"
                r"|^(pasala|salta(la)?|otra)( cancion| tema)?$"
                r"|^(pasa|cambia)( de)? ?(tema|cancion|musica)$"
                r"|^(el|la) que sigue$"), "next"),
    (re.compile(r"\banterior\b|\bprevia\b|^volve una$"), "previous"),
    (re.compile(r"sub\w+ (el )?volumen|volumen (mas )?arriba"
                r"|^(mas fuerte|subile|mas volumen|a todo volumen)$"),
     "volume_up"),
    (re.compile(r"baj\w+ (el )?volumen|volumen (mas )?abajo"
                r"|^(mas bajo|bajale|menos volumen|mas despacio)$"),
     "volume_down"),
]
# Estas van al cerebro (necesitan tools): "poné tal tema", "cambiá de
# playlist", "podés poner X". Ancladas al inicio: "se pone triste"/"todo
# cambia" son letra y no deben pasar.
MUSICA_CEREBRO_RE = re.compile(
    r"^(pone|poneme|cambia|cambiame|reproduci)"
    r"|^(podes|puedes|podrias|me podes|me puedes)\b.{0,12}"
    r"\b(poner|cambiar|reproducir)\b"
    r"|\bplaylist\b|\blista de\b")

ENTER_CHAT_RE = EXIT_CHAT_RE = PRIVACY_RE = None
ENTER_REDACTOR_RE = EXIT_REDACTOR_RE = ENTER_COACH_RE = RESET_RE = None


def _frases_a_regex(frases: list[str]) -> re.Pattern:
    partes = [r"\b" + re.escape(sin_tildes(f)).replace(r"\ ", r"\s+") + r"\b"
              for f in frases if f.strip()]
    return re.compile("|".join(partes) or r"(?!x)x")


def aplicar_comandos(cfg: dict):
    global ENTER_CHAT_RE, EXIT_CHAT_RE, PRIVACY_RE
    global ENTER_REDACTOR_RE, EXIT_REDACTOR_RE, ENTER_COACH_RE, RESET_RE
    c = {**DEFAULT_COMANDOS, **(cfg.get("comandos") or {})}
    ENTER_CHAT_RE = _frases_a_regex(c["charla"])
    ENTER_REDACTOR_RE = _frases_a_regex(c["redactor"])
    ENTER_COACH_RE = _frases_a_regex(c.get("coach") or
                                     DEFAULT_COMANDOS["coach"])
    RESET_RE = _frases_a_regex(c.get("reiniciar") or
                               DEFAULT_COMANDOS["reiniciar"])
    PRIVACY_RE = _frases_a_regex(c["privacidad"])
    EXIT_CHAT_RE = EXIT_REDACTOR_RE = _frases_a_regex(c["salir"])
    cfg["comandos"] = c


def load_config(path="config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    # overrides editables desde el HUD (comandos + wake word/aliases)
    try:
        if os.path.exists(COMANDOS_FILE):
            ov = yaml.safe_load(open(COMANDOS_FILE, encoding="utf-8")) or {}
            if ov.get("comandos"):
                cfg["comandos"] = {**DEFAULT_COMANDOS, **ov["comandos"]}
            if ov.get("wake"):
                cfg.setdefault("wake", {}).update(ov["wake"])
                # wake word distinto (p.ej. en inglés): el pattern fonético
                # de "harvis" ya no aplica — cae a escape(word) + fuzzy.
                w = str(ov["wake"].get("word", ""))
                if w and not w.lower().startswith("harv"):
                    cfg["wake"]["pattern"] = None
    except Exception:
        log.exception("comandos.yaml ilegible, sigo con defaults")
    aplicar_comandos(cfg)
    # Nombre visible = wake word capitalizado; renombrar el wake renombra
    # la app entera (prompt del cerebro y correcciones de texto incluidos).
    word = str((cfg.get("wake") or {}).get("word", "harvis")).strip()
    nombre = word.capitalize() if word else "Harvis"
    cfg["display_name"] = nombre
    if nombre != "Harvis":
        lcfg = cfg.setdefault("llm", {})
        lcfg["system_prompt"] = (lcfg.get("system_prompt", "")
                                 .replace("HARVIS", nombre.upper())
                                 .replace("Harvis", nombre))
        for c in (cfg.get("stt", {}).get("text_corrections") or []):
            if c.get("replace") == "Harvis":
                c["replace"] = nombre
    return cfg


def guardar_comandos(cfg: dict, payload: dict) -> str:
    """Persiste lo editado en el HUD (comandos.yaml) y lo aplica en vivo."""
    ov = {}
    if payload.get("comandos"):
        ov["comandos"] = {k: [f.strip() for f in v if f.strip()]
                          for k, v in payload["comandos"].items()}
        cfg["comandos"] = {**DEFAULT_COMANDOS, **ov["comandos"]}
    if payload.get("wake"):
        w = payload["wake"]
        ov["wake"] = {"word": str(w.get("word", "harvis")).strip().lower(),
                      "aliases": [a.strip().lower()
                                  for a in w.get("aliases", []) if a.strip()]}
        cfg.setdefault("wake", {}).update(ov["wake"])
        if not ov["wake"]["word"].startswith("harv"):
            cfg["wake"]["pattern"] = None
    with open(COMANDOS_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(ov, f, allow_unicode=True, sort_keys=False)
    aplicar_comandos(cfg)
    log.info("comandos actualizados desde el HUD: %s", list(ov))
    return "Guardado y aplicado."


aplicar_comandos({})  # defaults al importar; load_config re-aplica overrides

SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "skills")


def cargar_skills(cfg: dict):
    """Carga cada .py de skills/ (TOOLS + PROMPT opcional + setup(cfg)).
    Devuelve (tools, info, buffer_del_redactor). Una skill rota se saltea.
    Se re-llama al instalar una skill desde el HUD (recarga en vivo)."""
    import glob as _glob
    import importlib.util
    tools, info, redactor_buffer, cargadas = [], [], None, []
    watchers = []
    for ruta in sorted(_glob.glob(os.path.join(SKILLS_DIR, "*.py"))):
        nombre = os.path.splitext(os.path.basename(ruta))[0]
        if nombre.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"skill_{nombre}", ruta)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "setup"):
                mod.setup(cfg)
            herramientas = list(getattr(mod, "TOOLS", []))
            tools += herramientas
            if prompt_extra := getattr(mod, "PROMPT", ""):
                marca = f"\n[skill {nombre}] "
                base = cfg.setdefault("llm", {}).get("system_prompt", "")
                if marca not in base:   # recargas: no duplicar el prompt
                    cfg["llm"]["system_prompt"] = base + marca + prompt_extra
            if nombre == "redactor":
                redactor_buffer = mod.BUFFER
            if hasattr(mod, "WATCHER"):
                watchers.append((nombre, mod.WATCHER))
            cargadas.append(f"{nombre}({len(herramientas)})")
            info.append({
                "nombre": nombre,
                "desc": (mod.__doc__ or "").strip().split("\n")[0][:120],
                "tools": [t.name for t in herramientas],
            })
        except Exception:
            log.exception("skill %s no cargó — sigo sin ella", nombre)
    if cargadas:
        log.info("skills: %s", ", ".join(cargadas))
    return tools, info, redactor_buffer, watchers


def match_wake(text: str, cfg: dict) -> str | None:
    """Si la frase arranca con el wake word devuelve el comando (sin él);
    si no, None. '' = wake word solo, sin comando.

    Whisper inventa una grafía distinta cada vez que el usuario dice "Jarvis"
    (javi, harvey, harris, harvís, jervis, hergis, carguis...), así que al
    regex se le suma similitud por distancia. El umbral es adaptativo:
    llamarlo es una frase CORTA, mientras que lo que se le parece en una
    charla ajena viene en frases largas ("me tomé un jarabe"). Calibrado
    con wake_lab.py: 13/13 aciertos, 0 falsos sobre 66 frases reales.
    """
    wcfg = cfg.get("wake") or {}
    palabra = sin_tildes(wcfg.get("word", "jarvis"))
    pattern = wcfg.get("pattern") or re.escape(palabra)
    prefix_chars = int(wcfg.get("prefix_chars", 18))
    # NFD sin tildes garantiza mismo largo: los índices valen sobre el original.
    norm = sin_tildes(text)
    m = re.search(pattern, norm)
    if not m:
        # alias exactos de config (variantes que el fuzzy no alcanza)
        aliases = set(wcfg.get("aliases") or [])
        for cand in re.finditer(r"[a-z]{3,9}", norm):
            if cand.group() in aliases:
                m = cand
                break
    if not m:
        corto = len(text.split()) <= int(wcfg.get("fuzzy_max_palabras", 3))
        umbral = float(wcfg.get("fuzzy_corto" if corto else "fuzzy_largo",
                                0.50 if corto else 0.58))
        for cand in re.finditer(r"[a-z]{4,9}", norm):
            w = cand.group()
            if w.startswith("ser"):   # servicio, servís
                continue
            # -éis/-áis = vosotros (España): el usuario nunca lo usa — si suena,
            # es un video ("habéis" dio 0.67 vs harvis y despertó a HARVIS).
            if w.endswith(("eis", "ais")):
                continue
            if difflib.SequenceMatcher(None, cand.group(),
                                       palabra).ratio() >= umbral:
                m = cand
                break
    if m and m.start() < prefix_chars:
        return text[m.end():].lstrip(" ,.!?¡¿:;").strip()
    # Vocativo al final, como con una persona: "...mirá Teams, Harvis?".
    # Solo regex (sin fuzzy) sobre la cola: posición más propensa a ruido.
    cola = int(wcfg.get("suffix_chars", 16))
    if len(norm) > cola:
        m2 = re.search(pattern, norm[-cola:])
        if m2:
            corte = len(norm) - cola + m2.start()
            return text[:corte].rstrip(" ,.!?¡¿:;").strip()
    return None


from teclado import paste as paste_active


async def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(
        filename="kloom.log", filemode="w", level=logging.DEBUG,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("faster_whisper", "urllib3", "asyncio", "httpcore", "httpx",
                  "mcp.server", "openai", "claude_agent_sdk", "comtypes"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    cfg = load_config()
    ptt_enter = (cfg.get("ptt") or {}).get("press_enter", True)

    # las tools leen su config de módulo antes de que el cerebro las registre
    from tools import (browser, claude_code, codigo, homelab, media, memoria,
                       proyectos, teams, timers, vision, whatsapp, windows)
    claude_code.WINDOW_TITLE = (cfg.get("tools", {}).get("claude_code", {})
                                .get("window_title", "Claude"))
    browser.CDP_PORT = (cfg.get("tools", {}).get("browser", {})
                        .get("cdp_port", 9222))
    base_tools = (windows.TOOLS + claude_code.TOOLS + browser.TOOLS
                  + media.TOOLS + timers.TOOLS + proyectos.TOOLS
                  + memoria.TOOLS + homelab.TOOLS + codigo.TOOLS
                  + whatsapp.TOOLS + vision.TOOLS + teams.TOOLS)
    skills_tools, skills_info, redactor_buffer, skills_watchers = cargar_skills(cfg)
    all_tools = base_tools + skills_tools

    from huella import Huella
    huella = Huella.cargar(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "dataset", "enroll"))

    print("Cargando Whisper large-v3 en GPU...", flush=True)
    stt = stt_mod.Stt(cfg)
    await asyncio.to_thread(stt.warm_up)

    boca = Boca(cfg)
    brain_actual = (cfg.get("llm") or {}).get("brain", "claude")
    cerebro = crear_cerebro(cfg, all_tools)

    # Conectar en SEGUNDO PLANO: el CLI de Claude tarda ~50 s en frío y
    # bloqueaba todo el arranque (el HUD se rendía sin levantar ventana).
    # Para cuando termine de cargar el mic ya suele estar listo; si llega
    # un comando antes, connect() lo hace esperar (no abre otra sesión).
    async def _conectar_cerebro(c):
        try:
            await c.connect()
            log.info("cerebro %s conectado", brain_actual)
        except Exception:
            log.exception("%s no conectó; reintenta al primer comando",
                          brain_actual)
    asyncio.create_task(_conectar_cerebro(cerebro))

    loop = asyncio.get_running_loop()
    oido = Oido(cfg, loop)
    oido.start()

    class _NoHud:
        def __getattr__(self, _):
            return lambda *a: None

    hud = _NoHud()
    if (cfg.get("hud") or {}).get("enabled", True):
        from hud import Hud
        providers = list((cfg.get("llm", {}).get("providers") or {}))
        def _save_desde_hud(payload):
            word_antes = (cfg.get("wake") or {}).get("word", "harvis")
            r = guardar_comandos(cfg, payload)
            word_ahora = (cfg.get("wake") or {}).get("word", "harvis")
            if word_ahora != word_antes:
                nombre = word_ahora.capitalize()
                cfg["display_name"] = nombre
                hud.set_name(nombre)
                # el cerebro toma el nombre nuevo recreándose (mismo camino
                # que la instalación de skills). Corre en el thread del
                # webview → threadsafe.
                loop.call_soon_threadsafe(
                    oido.queue.put_nowait, ("reload_skills", None))
                r += f" Ahora me llamo {nombre}."
            return r

        def _skills_data():
            return {"wake": {"word": cfg.get("wake", {}).get("word", ""),
                             "aliases": cfg.get("wake", {}).get("aliases", [])},
                    "comandos": cfg.get("comandos", {}),
                    "skills": skills_info}

        hud = Hud(cfg, loop,
                  lambda t: oido.queue.put_nowait(("text", t)), providers,
                  mic_sink=lambda: oido.queue.put_nowait(("mic", None)),
                  skills_data=_skills_data,
                  save_fn=_save_desde_hud,
                  reload_sink=lambda: oido.queue.put_nowait(
                      ("reload_skills", None)),
                  reset_sink=lambda: oido.queue.put_nowait(("reset", None)),
                  abort_sink=lambda: (boca.stop(), abort_ev.set()),
                  skills_dir=SKILLS_DIR)
        hud.start()
        hud.set_brain(cfg.get("llm", {}).get("brain", "claude"))
        if cfg.get("display_name", "Harvis") != "Harvis":
            hud.set_name(cfg["display_name"])

    # Estados granulares en el HUD: "Leyendo Teams…" en vez de "pensando…"
    # a secas. registry avisa al ARRANCAR cada tool, con cualquier driver.
    _ACTIVIDAD = [
        ("teams", "Leyendo Teams…"), ("whatsapp", "Escribiendo WhatsApp…"),
        ("play_music", "Poniendo música…"), ("web_answer", "Buscando en internet…"),
        ("browser", "Usando el navegador…"), ("screenshot", "Mirando la pantalla…"),
        ("cerebro_", "Buscando en el vault…"), ("homelab", "Consultando el homelab…"),
        ("code_", "Leyendo código…"), ("project", "Revisando el proyecto…"),
        ("open_app", "Abriendo la aplicación…"), ("close_window", "Cerrando la ventana…"),
        ("timer", "Con los timers…"), ("alarm", "Programando la alarma…"),
        ("weather", "Consultando el clima…"), ("get_time", "Mirando la hora…"),
        ("remember", "Anotando…"), ("forget", "Borrando el dato…"),
        ("recall", "Haciendo memoria…"), ("redactor", "Con el dictado…"),
        ("send_to_claude", "Delegando a Claude Code…"),
        ("media_key", "Controlando la música…"),
        ("harvis_update", "Actualizándome…"),
    ]

    def _mostrar_actividad(nombre):
        for pref, texto in _ACTIVIDAD:
            if pref in nombre:
                hud.actividad(texto)
                return
        hud.actividad(f"Usando {nombre.replace('_', ' ')}…")

    import registry as _registry
    _registry.ON_TOOL = _mostrar_actividad

    # Música sonando → MODO MÚSICA al cerrar el turno: el mic sigue vivo
    # pero solo acepta órdenes de música; la letra de la canción se ignora.
    pedido_musica = {"on": False}
    browser.ON_MUSICA = lambda: pedido_musica.__setitem__("on", True)

    def duck(bajar: bool, restaurar_en: float = 0):
        """Baja la música mientras HARVIS espera el comando ("¿Señor?" /
        ventana de repregunta) — sin esto Whisper no entiende nada con la
        música de fondo. restaurar_en > 0 agenda la vuelta al 100%."""
        asyncio.get_running_loop().run_in_executor(
            None, browser._duck_navegador, bajar)
        if bajar and restaurar_en > 0:
            asyncio.get_running_loop().call_later(
                restaurar_en, lambda: asyncio.get_running_loop()
                .run_in_executor(None, browser._duck_navegador, False))

    from canal_telegram import Telegram
    tg = Telegram(cfg, lambda t: oido.queue.put_nowait(("tg", t)),
                  voice_sink=lambda r: loop.call_soon_threadsafe(
                      oido.queue.put_nowait, ("tg_voice", r)))
    if tg.enabled:
        asyncio.create_task(tg.poll())

    _FRASE_FIN = re.compile(r"(?<=[.!?…]) +")
    # Los cerebros a veces meten markdown igual: se pela antes de hablar y
    # de mostrar ("**Hola**" leído como "asterisco asterisco Hola" = ridículo).
    _MARKDOWN = re.compile(r"[*`#]+|^\s*[-•]\s+", re.MULTILINE)

    async def responder_en_vivo(gen) -> str:
        """Consume el stream del cerebro hablando cada oración apenas está
        completa — latencia percibida de UNA oración, y el habla fluye sin
        pausas: boca.say_stream sintetiza por adelantado."""
        acum = {"full": ""}

        async def frases():
            pendiente = ""
            async for chunk in gen:
                chunk = _MARKDOWN.sub("", chunk)
                # chunks = deltas de tokens (traen su propio espaciado) o
                # respuestas enteras (jarvis) — concatenar tal cual
                # separador SOLO en fronteras de bloque (fin de oración →
                # letra): un delta puede cortar en medio de una palabra y
                # meterle un espacio la rompe ("esper ada").
                full = acum["full"]
                sep = " " if full and full[-1] in ".!?…:" \
                    and chunk[:1].isalnum() else ""
                acum["full"] += sep + chunk
                pendiente += sep + chunk
                partes = _FRASE_FIN.split(pendiente)
                for fr in partes[:-1]:
                    if fr.strip():
                        hud.set_state("speaking")
                        hud.reply_chunk(fr.strip())  # texto a la par de la voz
                        yield fr.strip()
                pendiente = partes[-1]
            if pendiente.strip():
                hud.set_state("speaking")
                hud.reply_chunk(pendiente.strip())
                yield pendiente.strip()

        await boca.say_stream(frases())
        return acum["full"].strip()

    # --- dataset del wake word: audio real de "Harvis" para entrenar un
    # modelo propio (openWakeWord) el día de mañana.
    dataset_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "dataset", "wake")
    save_wake_audio = (cfg.get("privacy") or {}).get("save_wake_audio", True)

    def guardar_wake(audio):
        import wave
        try:
            os.makedirs(dataset_dir, exist_ok=True)
            existentes = os.listdir(dataset_dir)
            if len(existentes) >= 500:
                return
            path = os.path.join(dataset_dir,
                                f"wake-{time.strftime('%Y%m%d-%H%M%S')}.wav")
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(16000)
                w.writeframes((audio * 32767).astype("int16").tobytes())
        except Exception:
            log.exception("no pude guardar audio del wake")

    # --- reflexión nocturna: HARVIS relee el día y actualiza su memoria y
    # el perfil del usuario en Cerebro, con sus propias tools.
    async def reflexion_diaria():
        from tools.memoria import HISTFILE
        rcfg = cfg.get("reflexion") or {}
        if not rcfg.get("enabled", True):
            return
        hh, mm = map(int, str(rcfg.get("hora", "04:30")).split(":"))
        while True:
            ahora = datetime.datetime.now()
            proxima = ahora.replace(hour=hh, minute=mm, second=0,
                                    microsecond=0)
            if proxima <= ahora:
                proxima += datetime.timedelta(days=1)
            await asyncio.sleep((proxima - ahora).total_seconds())
            hoy = datetime.date.today().isoformat()
            try:
                lineas = [l for l in open(HISTFILE, encoding="utf-8")
                          if l.startswith('{"ts": "' + hoy) or hoy in l[:30]]
            except FileNotFoundError:
                lineas = []
            if len(lineas) < 3:
                log.info("reflexión: día tranquilo (%s turnos), salteo",
                         len(lineas))
                continue
            log.info("reflexión nocturna: %s turnos del día", len(lineas))
            prompt = (
                "REFLEXIÓN NOCTURNA (tarea interna, no hay nadie escuchando"
                " — no uses TTS mental, respondé corto). Este es el registro"
                " de hoy:\n" + "".join(lineas)[-6000:] +
                "\nDestilá lo que valga la pena: correcciones o preferencias"
                " nuevas → remember (y forget de lo que quedó viejo);"
                " patrones de cómo es el usuario → actualizá Perfil-Usuario.md"
                " con cerebro_note (append, con fecha). Si no hay nada"
                " sustancial, no guardes nada. Cerrá con una línea de"
                " resumen.")
            try:
                async with asyncio.timeout(300):
                    r = await cerebro.ask(prompt)
                log.info("reflexión: %s", r[:300])
                await tg.send(f"🌙 Reflexión nocturna: {r[:500]}")
            except Exception:
                log.exception("reflexión nocturna falló")

    def arrancar_watchers(lista):
        tareas = []
        for nombre, w in lista:
            async def _guard(nombre=nombre, w=w):
                try:
                    await w(announce, cfg)
                except asyncio.CancelledError:
                    pass
                except Exception:
                    log.exception("watcher %s murió", nombre)
            tareas.append(asyncio.create_task(_guard()))
        if lista:
            log.info("watchers: %s", ", ".join(n for n, _ in lista))
        return tareas

    watcher_tasks = arrancar_watchers(skills_watchers)

    asyncio.create_task(reflexion_diaria())

    async def announce(text: str):
        """Aviso espontáneo (timers/alarmas): beep + voz con el mic cerrado,
        y también al celu si Telegram está emparejado."""
        beep_wake()
        print(f"⏰ {text}", flush=True)
        hud.aviso(text)
        await tg.send(f"⏰ {text}")
        oido.mute()
        await boca.say(text)
        oido.unmute()

    timers.ANNOUNCE = announce
    followup = float((cfg.get("wake") or {}).get("followup", 8))
    log_all_speech = (cfg.get("privacy") or {}).get("log_all_speech", True)
    chat_timeout = float((cfg.get("wake") or {}).get("chat_timeout", 180))
    brain_timeout = float((cfg.get("llm") or {}).get("turn_timeout", 120))

    wake_word = (cfg.get("wake") or {}).get("word", "jarvis")
    ptt_key = (cfg.get("ptt") or {}).get("key", "f8").upper()
    print(f"\n🎤 KLOOM OS listo. Decí «{wake_word}, ...» para comandos, "
          f"mantené {ptt_key} para dictar. Ctrl+C para salir.\n", flush=True)

    awaiting_command_until = 0.0  # ventana post-"¿señor?" sin wake word
    chat_mode = False              # todo lo que se oiga va al cerebro
    chat_last = 0.0
    privacy = False                # mic apagado; se sale desde el HUD
    redactor_mode = False          # anota todo sin cerebro (skill redactor)
    coach_mode = False             # charla + prompt de coach (skill coach)
    music_mode = False             # solo órdenes de música; la letra se ignora

    async def vigia_musica():
        """Música/video sonando en el navegador o un reproductor → MODO
        MÚSICA automático (aunque la haya puesto el usuario a mano);
        ~15 s de silencio → modo normal solo."""
        nonlocal music_mode
        son = sil = 0
        while True:
            await asyncio.sleep(5)
            try:
                if privacy or chat_mode or coach_mode or redactor_mode:
                    son = sil = 0
                    continue
                pico = await asyncio.to_thread(browser._audio_navegador)
                if pico > 0.02:
                    son, sil = son + 1, 0
                    if not music_mode and son >= 2:
                        music_mode = True
                        hud.actividad("♪ modo música automático — pausa, "
                                      "siguiente… o «Harvis, …»")
                        log.info("modo música AUTO ON (pico %.2f)", pico)
                        print("♪ modo música AUTO", flush=True)
                elif pico >= 0:
                    sil, son = sil + 1, 0
                    if music_mode and sil >= 3:
                        music_mode = False
                        hud.set_state("idle")
                        log.info("modo música AUTO OFF (silencio)")
                        print("♪ modo música OFF (silencio)", flush=True)
            except Exception:
                log.debug("vigía música falló", exc_info=True)

    asyncio.create_task(vigia_musica())
    # El coach charla mejor en otro modelo (Groq/Llama 70B, probado por
    # el usuario): cerebro aparte SIN tools, creado recién al entrar al modo.
    # El principal ni se entera; el hilo del coach persiste entre sesiones.
    cerebro_coach = None
    coach_brain = (cfg.get("llm") or {}).get("coach_brain", "groq")

    # "Cortala": F9 o botón ⏹ — calla la voz al instante y aborta el turno.
    abort_ev = asyncio.Event()
    oido.on_abort = lambda: loop.call_soon_threadsafe(
        lambda: (boca.stop(), abort_ev.set()))

    class _Abortado(Exception):
        pass

    coach_turnos = 0

    async def guardar_sesion_coach(cc, turnos):
        """Cierra la sesión de coach en el diario del vault Cerebro."""
        try:
            r = await cc.ask(
                "[modo coach] La sesión terminó. Escribí un registro breve "
                "de 5 a 8 líneas para el diario: temas tocados, lo que se "
                "vio, compromisos o desafío pendiente. Sin preguntas ni "
                "cierre motivacional; solo el registro.")
            from tools.homelab import cerebro_note
            fecha = time.strftime("%Y-%m-%d %H:%M")
            out = await cerebro_note.handler({
                "nota": "Diario-Coach.md",
                "contenido": f"\n## Sesión {fecha} ({turnos} intervenciones)"
                             f"\n{r}\n",
                "modo": "append"})
            log.info("diario coach guardado: %s", str(out)[:80])
        except Exception:
            log.exception("no pude guardar la sesión de coach")

    silence_base = float((cfg.get("vad") or {}).get("silence_end", 0.9))
    silence_chat = float((cfg.get("vad") or {})
                         .get("silence_end_chat", 1.6))
    max_base = float((cfg.get("vad") or {}).get("max_utterance_normal", 25))
    max_chat = float((cfg.get("vad") or {}).get("max_utterance", 90))

    while True:
        # En charla/coach el VAD espera más antes de cortar: pausar para
        # pensar no es terminar de hablar, y los descargos son largos. En
        # modo normal, frases CORTAS: con tope alto el ruido de fondo arma
        # segmentos de 90 s donde el "Harvis" queda enterrado.
        oido.silence_end = silence_chat if chat_mode else silence_base
        oido.max_utterance = max_chat if chat_mode else max_base
        kind, audio = await oido.queue.get()

        # Botón del mic en el HUD: única salida del modo privacidad.
        if kind == "mic":
            privacy = not privacy
            if privacy:
                chat_mode = False
                oido.mute()
                hud.set_state("muted")
                print("🔇 privacidad ON", flush=True)
                log.info("privacidad ON (HUD)")
            else:
                oido.unmute()
                hud.set_state("idle")
                print("🎤 privacidad OFF", flush=True)
                log.info("privacidad OFF (HUD)")
            continue

        # Skill instalada desde el HUD: recargar skills y recrear el
        # cerebro con las tools nuevas — sin reiniciar HARVIS.
        if kind == "reload_skills":
            try:
                skills_tools, skills_info, redactor_buffer, \
                    skills_watchers = cargar_skills(cfg)
                nuevos = base_tools + skills_tools
                nuevo = crear_cerebro(cfg, nuevos, brain=brain_actual)
                await nuevo.connect()
                await cerebro.close()
                cerebro = nuevo
                all_tools = nuevos
                for t in watcher_tasks:
                    t.cancel()
                watcher_tasks = arrancar_watchers(skills_watchers)
                cerebro_coach = None  # prompt fresco en la próxima entrada
                hud.aviso(f"Skills recargadas ({len(skills_info)} "
                          "instaladas). Ya puede usarlas.")
                log.info("skills recargadas en vivo")
            except Exception:
                log.exception("recarga de skills falló; sigo como estaba")
                hud.aviso("La recarga falló, sigo con las skills de antes.")
            continue

        # Conversación de cero (botón 🔄 del HUD o "conversación nueva"):
        # recrea el cerebro actual — mismo camino que el switch. MUDO a
        # pedido del usuario: limpia el chat del HUD y listo, sin anuncio.
        if kind == "reset":
            def _drenar_resets():
                # clics repetidos mientras reconecta (~8 s): colapsar en UNO
                resto = []
                try:
                    while True:
                        item = oido.queue.get_nowait()
                        if item[0] != "reset":
                            resto.append(item)
                except asyncio.QueueEmpty:
                    pass
                for item in resto:
                    oido.queue.put_nowait(item)
            _drenar_resets()
            hud.clear_chat()
            beep_ok()
            oido.mute()
            if coach_mode and cerebro_coach is not None:
                # reset EN modo coach: borra también el hilo del coach
                await cerebro_coach.close()
                cerebro_coach = None
            try:
                nuevo = crear_cerebro(cfg, all_tools, brain=brain_actual)
                await nuevo.connect()
                await cerebro.close()
                cerebro = nuevo
                log.info("conversación reiniciada (%s)", brain_actual)
            except Exception:
                log.exception("reset de conversación falló")
                beep_error()
                hud.error_flash()
                hud.aviso("No pude reiniciar la conversación.")
            _drenar_resets()
            if not privacy:
                oido.unmute()
            continue

        if kind == "ptt_start":
            print("● dictando...", flush=True)
            continue

        if kind == "ptt":
            text = await asyncio.to_thread(stt.transcribe, audio)
            if not text:
                print("  (no entendí)", flush=True)
                beep_error()
                continue
            print(f"→ {text}", flush=True)
            await asyncio.to_thread(paste_active, text, ptt_enter)
            beep_ok()
            continue

        # comando tipeado (HUD) o por Telegram: mismo pipeline, sin STT ni
        # wake word. Lo de Telegram responde al chat, no al parlante.
        por_tg = kind in ("tg", "tg_voice")
        typed = kind in ("text", "tg", "tg_voice")
        if kind == "tg_voice":
            # audio de voz del celu: lo transcribe el Whisper local
            text = await asyncio.to_thread(stt.transcribe, str(audio))
            try:
                os.remove(str(audio))
            except OSError:
                pass
            log.info("tg voz: %r", text)
            if not text.strip():
                await tg.send("No entendí ese audio, señor.")
                continue
        elif typed:
            text = str(audio).strip()
            log.info("%s: %r", "tg" if por_tg else "hud", text)
        else:
            # utterance por VAD: solo interesa si trae el wake word
            text = await asyncio.to_thread(stt.transcribe, audio)
            if not text:
                # Whisper no entendió NADA (o lo descartó por confianza) —
                # justo el caso de la huella: si el SONIDO es tu "Harvis",
                # dispara igual. Sin esto, un "Harvis" masticado moría acá.
                if (huella is not None and not chat_mode
                        and not redactor_mode and not privacy
                        and audio.size <= 16000 * 6
                        and huella.match(audio,
                                         margen=3.5 if music_mode else 0.0)):
                    log.info("wake por huella (whisper no entendió)")
                    beep_wake()
                    oido.mute()
                    print("🔊 ¿Señor?", flush=True)
                    hud.set_state("armed")
                    duck(True, followup + 5)
                    await boca.say("¿Señor?")
                    oido.unmute()
                    awaiting_command_until = time.monotonic() + followup
                continue
            if log_all_speech:
                log.debug("oído: %r", text)

        # Privacidad SIN wake word: una frase corta con "privacidad" casi
        # seguro es para HARVIS aunque Whisper haya masticado el resto
        # ("ahora exponemos privacidad"). El gate de largo evita que una
        # charla ajena sobre privacidad apague el mic.
        if (not typed and len(text.split()) <= 5
                and PRIVACY_RE.search(sin_tildes(text))):
            privacy = True
            chat_mode = coach_mode = music_mode = False
            oido.mute()
            hud.set_state("muted")
            print("🔇 privacidad ON", flush=True)
            log.info("privacidad ON (voz, sin wake): %r", text)
            await boca.say("Micrófono apagado, señor. Reactívelo con el "
                           "botón del panel.")
            continue

        # Modo redactor: anotar todo, sin cerebro ni TTS — dictado largo
        # gratis. "listo" cierra y el texto queda para redactor_paste.
        if redactor_mode and not typed:
            if EXIT_REDACTOR_RE.search(sin_tildes(text)) \
                    and len(text.split()) <= 4:
                redactor_mode = False
                n = len(redactor_buffer)
                hud.set_state("idle")
                oido.mute()
                await boca.say(f"Anoté {n} frases, señor. Dígame dónde "
                               "las pego, o pídame que las corrija.")
                oido.unmute()
                awaiting_command_until = time.monotonic() + followup
                continue
            redactor_buffer.append(text.strip())
            hud.heard("📝 " + text.strip())
            beep_ok()
            continue

        # MODO MÚSICA: solo pasan órdenes de música. Directas → tecla
        # multimedia al toque; "poné/cambiá..." → cerebro; wake word →
        # flujo normal; TODO lo demás (la letra de la canción) se ignora.
        comando_musica = None
        if music_mode and not typed:
            st_m = sin_tildes(text.lower()).strip(".!?¿¡, ")
            if (time.monotonic() - len(audio) / 16000
                    < awaiting_command_until):
                pass  # ventana post-"¿Señor?": el comando pasa ENTERO,
                      # dictado con la música ya baja (ducking)
            elif match_wake(text, cfg) is not None:
                pass          # "Harvis..." explícito: sigue el flujo normal
            elif len(text.split()) > 8:
                continue      # frase larga = letra de canción
            elif EXIT_CHAT_RE.search(st_m):
                music_mode = False
                beep_ok()
                hud.set_state("idle")
                print("♪ modo música OFF", flush=True)
                continue
            else:
                accion = next((a for rx, a in MUSICA_DIRECTAS
                               if rx.search(st_m)), None)
                if accion:
                    from teclado import media as _media
                    veces = 4 if accion.startswith("volume") else 1
                    for _ in range(veces):
                        _media("play" if accion in ("pause", "play")
                               else accion)
                    beep_ok()
                    hud.actividad(f"♪ {accion}")
                    log.info("modo música: %s", accion)
                    continue
                if MUSICA_CEREBRO_RE.search(st_m):
                    comando_musica = text.strip()
                else:
                    continue  # ruido o letra: ni beep

        # Modo charla: todo lo que se oiga va al cerebro, sin wake word.
        if chat_mode and time.monotonic() - chat_last > chat_timeout:
            if coach_mode and cerebro_coach is not None and coach_turnos >= 2:
                asyncio.create_task(
                    guardar_sesion_coach(cerebro_coach, coach_turnos))
                coach_turnos = 0
            chat_mode = coach_mode = False
            log.info("modo charla: cerrado por inactividad")
            print("💬 modo charla cerrado (silencio)", flush=True)

        if comando_musica is not None:
            command = comando_musica
        elif chat_mode:
            command = text.strip()
            chat_last = time.monotonic()
            if EXIT_CHAT_RE.search(sin_tildes(command)):
                if coach_mode and cerebro_coach is not None \
                        and coach_turnos >= 2:
                    # sesión de coach al diario del Cerebro, en background
                    asyncio.create_task(
                        guardar_sesion_coach(cerebro_coach, coach_turnos))
                    coach_turnos = 0
                chat_mode = coach_mode = False
                beep_ok()
                print("💬 modo charla OFF", flush=True)
                hud.set_state("idle")
                oido.mute()
                await boca.say("Listo señor, vuelvo a esperar que me llame.")
                oido.unmute()
                continue
        elif not typed and (time.monotonic() - len(audio) / 16000
                            < awaiting_command_until):
            # La ventana se compara contra el INICIO de la frase (ahora
            # menos su duración): si empezaste a hablar adentro, vale,
            # aunque el VAD la cierre con la ventana ya vencida.
            command = text.strip()
            awaiting_command_until = 0.0
        elif typed:
            command = text
        else:
            command = match_wake(text, cfg)
            if command and len(command.split()) <= 4 and all(
                    match_wake(t, cfg) is not None for t in command.split()):
                # "Harvis Harvis Harvis" (o Javier×3, dictado sucio): no es
                # un comando, es la LLAMADA repetida → "¿Señor?" + ducking.
                command = ""
            if command is None:
                # Frase de MODO corta sin wake word ("activá el modo
                # coach"): casi seguro es para HARVIS — mismo criterio que
                # privacidad. Charla queda afuera a propósito: "hablemos"
                # es demasiado común en una conversación ajena.
                st = sin_tildes(text)
                if (len(text.split()) <= 6
                        and (ENTER_COACH_RE.search(st)
                             or ENTER_REDACTOR_RE.search(st)
                             or RESET_RE.search(st))):
                    command = text.strip()
                elif huella is not None and len(text.split()) <= 6 \
                        and huella.match(audio):
                    # El TEXTO no trajo el wake word pero el SONIDO del
                    # arranque es la voz del usuario diciendo "Harvis"
                    # (takes de dataset/enroll). Responde "¿Señor?" y abre
                    # ventana de comando.
                    log.info("wake por huella de voz (whisper oyó: %r)",
                             text)
                    command = ""
                else:
                    continue

        if not chat_mode:
            beep_wake()

        # Entrar al modo redactor: "harvis, modo redactor / anotá todo".
        if (command and redactor_buffer is not None
                and ENTER_REDACTOR_RE.search(sin_tildes(command))):
            redactor_mode = True
            redactor_buffer.clear()
            chat_mode = coach_mode = music_mode = False
            print("📝 modo redactor ON", flush=True)
            hud.set_state("chat")
            oido.mute()
            await boca.say("Anoto todo, señor. Dicte tranquilo; "
                           "diga «listo» al terminar.")
            oido.unmute()
            continue

        # Conversación nueva por voz: "harvis, conversación nueva".
        if command and RESET_RE.search(sin_tildes(command)):
            oido.queue.put_nowait(("reset", None))
            continue

        # Entrar al modo coach: "harvis, modo coach" — es modo charla con
        # el prompt de coach ontológico (skill coach) prefijando cada turno.
        if command and ENTER_COACH_RE.search(sin_tildes(command)):
            chat_mode = coach_mode = True
            music_mode = False
            coach_turnos = 0
            chat_last = time.monotonic()
            awaiting_command_until = 0.0
            print("🥊 modo coach ON", flush=True)
            hud.set_state("chat")
            oido.mute()
            if cerebro_coach is None and coach_brain:
                try:
                    cerebro_coach = crear_cerebro(cfg, [], brain=coach_brain)
                    await cerebro_coach.connect()
                    log.info("cerebro coach: %s", coach_brain)
                except Exception:
                    log.exception("cerebro coach (%s) no conectó — uso el "
                                  "principal", coach_brain)
                    cerebro_coach = None
            await boca.say("Modo coach. Contame qué te está pasando; "
                           "decí «modo normal» cuando quieras cortar.")
            oido.unmute()
            continue

        # Entrar al modo charla: "harvis, modo charla".
        if command and ENTER_CHAT_RE.search(sin_tildes(command)):
            chat_mode = True
            music_mode = False
            chat_last = time.monotonic()
            awaiting_command_until = 0.0
            print("💬 modo charla ON", flush=True)
            hud.set_state("chat")
            oido.mute()
            await boca.say("Modo charla, señor. Hablá tranquilo, "
                           "decime «listo» para cortar.")
            oido.unmute()
            continue
        if not command:
            oido.mute()
            print("🔊 ¿Señor?", flush=True)
            hud.set_state("armed")
            duck(True, followup + 5)   # música al 25% mientras escucho
            await boca.say("¿Señor?")
            oido.unmute()
            awaiting_command_until = time.monotonic() + followup
            continue

        hud.heard(("📱 " if por_tg else "") + command)
        if not typed and save_wake_audio:
            asyncio.get_running_loop().run_in_executor(
                None, guardar_wake, audio)

        # Telegram: directo al cerebro — los modos de mic (privacidad,
        # charla, señor?) no aplican a un chat remoto.
        if por_tg:
            trazas.nuevo_turno("telegram", command)
            print(f"📱 «{command}»", flush=True)
            hud.set_state("thinking")
            try:
                async with asyncio.timeout(brain_timeout):
                    reply = await cerebro.ask(command)
            except TimeoutError:
                reply = "Eso me llevó demasiado y lo corté, señor."
            except Exception:
                log.exception("cerebro reventó (tg)")
                reply = "Se me rompió algo procesando eso, señor."
            reply = _MARKDOWN.sub("", reply)
            hud.reply(reply)
            hud.set_state("idle")
            memoria.append_historial(command, reply)
            trazas.cerrar_turno(reply)
            await tg.send(reply)
            if pedido_musica["on"]:   # música pedida desde el celu
                pedido_musica["on"] = False
                music_mode = True
                chat_mode = coach_mode = False
                hud.actividad("♪ modo música")
                log.info("modo música ON (tg)")
            continue

        # Modo privacidad por voz: mic apagado hasta el botón del HUD.
        if PRIVACY_RE.search(sin_tildes(command)):
            privacy = True
            chat_mode = coach_mode = music_mode = False
            oido.mute()
            hud.set_state("muted")
            print("🔇 privacidad ON", flush=True)
            log.info("privacidad ON (voz)")
            await boca.say("Micrófono apagado, señor. Cuando quiera que "
                           "vuelva a escuchar, tóqueme el micrófono en el "
                           "panel.")
            continue  # sin unmute: queda sordo a propósito

        # Cambio de cerebro por voz — antes del LLM: funciona aunque el
        # cerebro actual esté roto. El viejo no se cierra hasta que el
        # nuevo conectó.
        target = parse_switch(command)
        if target:
            oido.mute()
            try:
                nuevo = crear_cerebro(cfg, all_tools, brain=target)
                await nuevo.connect()
                await cerebro.close()
                descartados = len(getattr(cerebro, "messages", [])) - 1
                cerebro = nuevo
                log.info("switch de cerebro a %s (historial descartado: %s)",
                         target, max(descartados, 0))
                reply = f"Listo señor, ahora piensa {target.capitalize()}."
                brain_actual = target
                hud.set_brain(target)
            except Exception as e:
                log.exception("switch a %s falló", target)
                reply = f"No pude cambiar a {target.capitalize()}, señor."
                beep_error()
                hud.error_flash()
            print(f"🔊 {reply}", flush=True)
            hud.reply(reply)
            await boca.say(reply)
            oido.unmute()
            continue

        print(f"🧠 «{command}»", flush=True)
        log.info("wake: %r", command)
        objetivo = cerebro_coach if (coach_mode and cerebro_coach) \
            else cerebro
        trazas.nuevo_turno("hud" if typed else "voz", command)
        trazas.ev("cerebro", brain=coach_brain if objetivo is cerebro_coach
                  else brain_actual)
        hud.set_state("thinking")
        # mute = política de "cerebro ocupado": mientras piensa, el mic está
        # cerrado — un comando dicho en el medio se descarta en el aire.
        oido.mute()
        abort_ev.clear()
        tarea = espera_abort = None
        try:
            # Timeout de TODO el turno, cualquier driver: sin esto un cuelgue
            # del SDK deja el mic muteado para siempre (= parece muerto).
            # El stream habla cada oración apenas el cerebro la produce.
            # F9/⏹ (abort_ev) corta voz y turno al instante.
            async with asyncio.timeout(brain_timeout):
                pedido = ("[modo coach] " + command) if coach_mode else command
                tarea = asyncio.create_task(
                    responder_en_vivo(objetivo.ask_stream(pedido)))
                espera_abort = asyncio.create_task(abort_ev.wait())
                await asyncio.wait({tarea, espera_abort},
                                   return_when=asyncio.FIRST_COMPLETED)
                if not tarea.done():
                    raise _Abortado
                reply = tarea.result()
            if not reply:
                reply = "Hecho, señor."
                hud.reply(reply)
                await boca.say(reply)
        except _Abortado:
            log.info("turno abortado por el usuario")
            reply = "[cortado]"
            beep_ok()
            hud.aviso("Cortado, señor.")
            if objetivo is cerebro and type(cerebro).__name__ == "CerebroClaude":
                # el stream del SDK quedó a medias: cliente fresco
                try:
                    nuevo = crear_cerebro(cfg, all_tools, brain=brain_actual)
                    await nuevo.connect()
                    await cerebro.close()
                    cerebro = nuevo
                except Exception:
                    log.exception("reconexión post-aborto falló")
        except TimeoutError:
            log.warning("turno cortado tras %ss", brain_timeout)
            reply = ("Eso me estaba llevando demasiado y lo corté, señor. "
                     "Puede que haya quedado a medio hacer.")
            beep_error()
            hud.error_flash()
            hud.reply(reply)
            await boca.say(reply)
        except Exception as e:
            log.exception("cerebro reventó")
            reply = "Se me rompió algo procesando eso, señor."
            beep_error()
            hud.error_flash()
            hud.reply(reply)
            await boca.say(reply)
        for t in (tarea, espera_abort):
            if t is not None and not t.done():
                t.cancel()
        # el texto ya se fue streameando al HUD oración por oración
        hud.reply_end()
        print(f"🔊 {reply}", flush=True)
        if objetivo is cerebro_coach:
            coach_turnos += 1
        memoria.append_historial(command, reply)
        trazas.cerrar_turno(reply)
        # ¿Arrancó música en este turno? → MODO MÚSICA: escucha solo
        # órdenes de música; la letra no matchea nada y se ignora.
        if pedido_musica["on"]:
            pedido_musica["on"] = False
            music_mode = True
            chat_mode = coach_mode = False
            oido.unmute()
            hud.actividad("♪ modo música: pausa, siguiente, poné tal "
                          "tema… «modo normal» para salir")
            log.info("modo música ON")
            print("♪ modo música ON", flush=True)
            continue   # sin ventana de followup
        oido.unmute()
        # Conversación seguida estilo Alexa: unos segundos para repreguntar
        # sin repetir el wake word. El beep avisa que la ventana está abierta.
        # En modo charla no hace falta: ya escucha todo.
        if chat_mode:
            chat_last = time.monotonic()
            hud.set_state("chat")
        elif music_mode:
            # seguimos en modo música: nada de ventana de repregunta ni
            # "te escucho" — el modo ya escucha órdenes de música siempre.
            hud.actividad("♪ modo música — pausa, siguiente, poné tal "
                          "tema… «modo normal» para salir")
        elif followup > 0:
            beep_listening()
            hud.set_state("armed")
            awaiting_command_until = time.monotonic() + followup
        else:
            hud.set_state("idle")


def _run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nKLOOM OS apagado.", file=sys.stderr)
    except Exception:
        # la consola está oculta: un crash sin log = HARVIS "muerto sin causa"
        logging.getLogger("kloom").exception("worker MURIÓ en el arranque")
        raise


if __name__ == "__main__":
    if (load_config().get("hud") or {}).get("enabled", True):
        # La única cara es el HUD: esconder la consola (correr bajo pythonw
        # no sirve — el SDK de Claude no spawnea sin handles de consola,
        # WinError 50).
        import ctypes
        _hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if _hwnd:
            ctypes.windll.user32.ShowWindow(_hwnd, 0)  # SW_HIDE
        # Identidad propia en la barra de tareas (si no, agrupa como Python
        # y hereda su ícono).
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Kloom.HARVIS")

        # pywebview exige el thread principal → asyncio va a un worker y
        # el main sirve la ventana. Si el worker muere, se baja la UI.
        import threading

        import hud as hud_mod

        def worker():
            try:
                _run()
            finally:
                hud_mod.shutdown()

        threading.Thread(target=worker, daemon=True, name="kloom").start()
        hud_mod.serve_main_thread()
    else:
        _run()
