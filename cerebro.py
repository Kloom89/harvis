"""Cerebros de KLOOM. Factory + driver Claude (Agent SDK, suscripción Max).
La sesión es persistente: los comandos sucesivos comparten contexto
("abrí spotify" ... "ahora cerrala")."""
import asyncio
import json
import logging
import os

# El handshake del SDK vence a los 60 s y con la máquina cargada (Whisper
# recién subido a la GPU) a veces no llega; estirarlo antes de crear el client.
os.environ.setdefault("CLAUDE_CODE_STREAM_CLOSE_TIMEOUT", "180000")

from claude_agent_sdk import (
    AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage,
    StreamEvent, TextBlock, ToolUseBlock, create_sdk_mcp_server,
)

from registry import Tool, to_sdk

log = logging.getLogger("kloom.cerebro")

BRAINS = ("claude", "ollama", "groq", "kimi", "openai", "gemini")


def cuenta_activa() -> str:
    """Email de la cuenta Claude logueada en la CLI ("" si no hay) — la que
    va a usar el SDK. Respeta CLAUDE_CONFIG_DIR (login propio opcional)."""
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~")
    try:
        with open(os.path.join(base, ".claude.json"), encoding="utf-8") as f:
            return (json.load(f).get("oauthAccount") or {}).get(
                "emailAddress", "")
    except Exception:
        return ""


class SuscripcionBloqueada(Exception):
    """La cuenta de Claude activa no permite uso headless de la suscripción
    (pasa al rotar cuentas). kloom.py la atrapa y cae al cerebro fallback."""


def _error_hablable(result) -> str:
    """Versión corta y en criollo del error del SDK, apta para TTS."""
    texto = str(result or "error desconocido")
    if "rate limit" in texto.lower() or "429" in texto:
        return "me limitaron por cuota, probá en un rato."
    return texto[:140].replace("\n", " ") + "."


def sufijo_idioma(cfg: dict) -> str:
    """Directiva de idioma según el AJUSTE (cfg["lang"]), no según el idioma
    del comando. Va al FINAL del system prompt: enterrada en el medio, un
    modelo chico la ignora y repite el español de las tools y la memoria."""
    if cfg.get("lang") == "en":
        return ("\nCRITICAL — LANGUAGE: the app is set to ENGLISH. Every "
                "single reply must be in English, no matter what language "
                "the command or the tool results come in. Tool results may "
                "arrive in Spanish (dates, weather, statuses): translate "
                "them before speaking.")
    return ("\nCRÍTICO — IDIOMA: la app está en ESPAÑOL. Todas tus "
            "respuestas van en español, sin importar en qué idioma llegue "
            "el comando o lo que devuelvan las tools.")


def crear_cerebro(cfg: dict, tools: list[Tool], brain: str | None = None):
    """Devuelve el driver según providers.<brain>.driver. Levanta ValueError
    si el proveedor no está en config y RuntimeError si le falta la API key."""
    lcfg = cfg.get("llm") or {}
    brain = brain or lcfg.get("brain", "claude")
    pcfg = (lcfg.get("providers") or {}).get(brain)
    if not pcfg:
        raise ValueError(f"Proveedor '{brain}' no está en llm.providers")
    if pcfg.get("driver") == "sdk":
        return CerebroClaude(cfg, pcfg, tools)
    from cerebro_jarvis import CerebroJarvis
    return CerebroJarvis(cfg, brain, pcfg, tools)


class CerebroClaude:
    def __init__(self, cfg: dict, pcfg: dict, tools: list[Tool]):
        lcfg = cfg.get("llm") or {}
        cdir = pcfg.get("config_dir")
        if cdir:
            cdir = os.path.abspath(cdir)
            # Login PROPIO de HARVIS: rotar la cuenta de la CLI no lo toca.
            # Sin credenciales en la carpeta todavía, se usa el login global
            # (así el feature queda armado sin romper nada hasta el login).
            if os.path.exists(os.path.join(cdir, ".credentials.json")):
                os.environ["CLAUDE_CONFIG_DIR"] = cdir
            else:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
        sdk_tools = [to_sdk(t) for t in tools]
        server = create_sdk_mcp_server(name="kloom", version="1.0.0",
                                       tools=sdk_tools)
        allowed = [f"mcp__kloom__{t.name}" for t in tools]
        modelo = pcfg.get("model", "sonnet")
        # Un LLM no sabe qué modelo es: si no se le dice, inventa ("soy Opus
        # 4.5"). Va el valor real de config.yaml.
        from tools.memoria import contexto_sistema
        self.options = ClaudeAgentOptions(
            model=modelo,
            system_prompt=lcfg.get("system_prompt", "")
                          + f"\nCorrés sobre Claude '{modelo}' (lo dice la "
                            "config de KLOOM). Si te preguntan qué modelo "
                            "sos, decí exactamente eso y aclará que se "
                            "cambia en config.yaml; nunca inventes otro."
                          + contexto_sistema()
                          + sufijo_idioma(cfg),
            # CodeGraph entra como tools comunes (tools/codigo.py, vía CLI):
            # así lo tienen TODOS los cerebros, no solo Claude.
            mcp_servers={"kloom": server},
            # Read/Glob/Grep nativas: HARVIS puede LEER los proyectos de la
            # PC. Bash/Write/Edit siguen afuera — nada destructivo por voz.
            allowed_tools=allowed + ["Read", "Glob", "Grep"],
            disallowed_tools=["Bash", "Write", "Edit",
                              "WebSearch", "WebFetch", "Task", "TodoWrite"],
            permission_mode="bypassPermissions",
            # HARVIS no hereda la configuración de Claude Code: los plugins,
            # skills y hooks del usuario son de SU consola, y acá solo meten
            # ruido (un hook de arranque terminó anunciándose por voz).
            setting_sources=[],
            max_turns=12,
            # deltas de texto en vivo: la boca habla mientras genera
            include_partial_messages=True,
            # Read de una captura de pantalla = mensaje JSON gigante; el
            # default de 1 MB reventaba el reader ("mirá Teams" murió así).
            max_buffer_size=10 * 1024 * 1024,
        )
        # Con qué login se creó este cliente: si al fallar por suscripción
        # la cuenta activa ya es otra, kloom reintenta Claude antes de caer
        # a un fallback.
        self.cuenta = cuenta_activa()
        self.client: ClaudeSDKClient | None = None
        # El CLI tarda ~50 s en arranque frío: se conecta de fondo y quien
        # necesite el cerebro espera acá en vez de abrir una segunda sesión.
        self._listo = False
        self._lock = asyncio.Lock()

    async def connect(self):
        async with self._lock:
            if self._listo:
                return
            for attempt in (1, 2):
                self.client = ClaudeSDKClient(options=self.options)
                try:
                    await self.client.connect()
                    self._listo = True
                    return
                except Exception:
                    if attempt == 2:
                        raise
                    log.warning("connect falló, reintento...")
                    await asyncio.sleep(2)

    async def ask(self, text: str) -> str:
        # El subproceso del SDK puede morir solo (exit 129 visto corriendo
        # sin consola): ante cualquier fallo se reconecta UNA vez y se
        # reintenta. Se pierde el contexto de la sesión SDK, no el servicio.
        try:
            return await self._ask(text)
        except SuscripcionBloqueada:
            raise
        except Exception:
            log.warning("SDK caído, reconecto y reintento", exc_info=True)
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client, self._listo = None, False
            return await self._ask(text)

    async def _ask(self, text: str) -> str:
        reply = []
        async for t in self._stream(text):
            reply.append(t)
        return " ".join(reply).strip() or "Hecho, señor."

    async def ask_stream(self, text: str):
        """Va soltando el texto a medida que el SDK lo produce — la boca
        habla la primera oración mientras se generan las siguientes.
        Reconexión: solo si murió ANTES de soltar algo."""
        solto_algo = False
        try:
            async for t in self._stream(text):
                solto_algo = True
                yield t
        except SuscripcionBloqueada:
            raise
        except Exception:
            if solto_algo:
                log.exception("stream cortado a mitad de respuesta")
                yield "Se me cortó la respuesta ahí, señor."
                return
            log.warning("SDK caído, reconecto y reintento", exc_info=True)
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client, self._listo = None, False
            async for t in self._stream(text):
                yield t

    async def _stream(self, text: str):
        if not self._listo:
            await self.connect()
        await self.client.query(text)
        # El texto sale de los deltas (StreamEvent); los TextBlock del
        # AssistantMessage final los duplican y se ignoran.
        hubo_texto = False
        async for msg in self.client.receive_response():
            if isinstance(msg, StreamEvent):
                ev = msg.event
                if (ev.get("type") == "content_block_delta"
                        and ev.get("delta", {}).get("type") == "text_delta"):
                    hubo_texto = True
                    yield ev["delta"]["text"]
            elif isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, ToolUseBlock):
                        log.info("tool: %s %s", block.name, block.input)
            elif isinstance(msg, ResultMessage) and msg.is_error:
                log.warning("cerebro error: %s", msg.result)
                texto = str(msg.result or "")
                if not hubo_texto and ("subscription access" in texto
                                       or "Anthropic API key" in texto):
                    raise SuscripcionBloqueada(texto)
                # Error sin respuesta ≠ silencio: sin esto el turno vacío
                # caía al fallback "Hecho, señor." y el fallo quedaba mudo.
                if not hubo_texto:
                    yield ("El cerebro Claude falló, señor: "
                           + _error_hablable(msg.result)
                           + " Podés cambiarme el cerebro con "
                             "«cambiá el cerebro a groq».")

    async def close(self):
        if self.client:
            await self.client.disconnect()
