"""Canal Telegram de HARVIS: long-polling con la Bot API pelada (urllib,
sin dependencias). Los mensajes entran por la MISMA cola que la voz y el
panel; las respuestas vuelven al chat.

Seguridad: el bot es de UN dueño. El primer /start registra ese chat como
dueño (queda en telegram_owner.json); todo lo demás se ignora. Token en la
variable de entorno TELEGRAM_BOT_TOKEN — nunca en config ni en el repo.
"""
import asyncio
import json
import logging
import os
import urllib.parse
import urllib.request

log = logging.getLogger("kloom.telegram")

_DIR = os.path.dirname(os.path.abspath(__file__))
OWNER_FILE = os.path.join(_DIR, "telegram_owner.json")


def _env_usuario(nombre: str) -> str:
    """setx no llega a procesos ya corriendo: fallback al registro de
    Windows, así el token anda sin relogueo (mismo truco que las API keys)."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
        return winreg.QueryValueEx(k, nombre)[0]
    except OSError:
        return ""


class Telegram:
    def __init__(self, cfg, sink, voice_sink=None):
        """sink(texto): encola un comando; voice_sink(ruta): encola un
        audio de voz ya bajado (lo transcribe el Whisper local)."""
        tcfg = cfg.get("telegram") or {}
        env = tcfg.get("token_env", "TELEGRAM_BOT_TOKEN")
        token = os.environ.get(env, "") or _env_usuario(env)
        self.voice_sink = voice_sink
        self.enabled = bool(token)
        self.api = f"https://api.telegram.org/bot{token}"
        self.sink = sink
        self.owner: int | None = None
        if os.path.exists(OWNER_FILE):
            try:
                self.owner = json.load(open(OWNER_FILE))["chat_id"]
            except Exception:
                pass

    # ---------- HTTP crudo (en thread: urllib bloquea) ----------
    def _call(self, metodo: str, _http_timeout: int = 15, **params) -> dict:
        # OJO: 'timeout' puede venir en params (el long-poll de Telegram usa
        # un parámetro con ese nombre) — el de urllib va aparte.
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(f"{self.api}/{metodo}", data=data)
        with urllib.request.urlopen(req, timeout=_http_timeout) as r:
            return json.load(r)

    def _bajar_voz(self, file_id: str) -> str:
        """Baja el audio de voz a un archivo temporal y devuelve la ruta."""
        import tempfile
        info = self._call("getFile", file_id=file_id)
        rel = info["result"]["file_path"]
        token = self.api.rsplit("/bot", 1)[1]
        url = f"https://api.telegram.org/file/bot{token}/{rel}"
        fd, ruta = tempfile.mkstemp(suffix=".oga")
        os.close(fd)
        urllib.request.urlretrieve(url, ruta)
        return ruta

    async def send(self, texto: str):
        if not (self.enabled and self.owner):
            return
        try:
            await asyncio.to_thread(self._call, "sendMessage",
                                    chat_id=self.owner, text=texto[:4000])
        except Exception as e:
            log.warning("telegram send falló: %s", e)

    # ---------- polling ----------
    async def poll(self):
        log.info("telegram: polling arrancado (dueño: %s)", self.owner)
        offset = 0
        while True:
            try:
                resp = await asyncio.to_thread(
                    self._call, "getUpdates", _http_timeout=60,
                    offset=offset, timeout=50)
            except Exception as e:
                log.warning("telegram poll: %s", e)
                await asyncio.sleep(10)
                continue
            for u in resp.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                chat_id = (msg.get("chat") or {}).get("id")
                texto = (msg.get("text") or "").strip()
                voz = msg.get("voice") or msg.get("audio")
                if not chat_id:
                    continue
                if self.owner is None:
                    # primer contacto (texto O audio) = emparejamiento
                    self.owner = chat_id
                    json.dump({"chat_id": chat_id}, open(OWNER_FILE, "w"))
                    log.info("telegram: dueño registrado %s", chat_id)
                    await self.send("Emparejado, señor. Este chat quedó "
                                    "como el único autorizado. Hábleme por "
                                    "texto o audio.")
                    continue
                if chat_id != self.owner:
                    log.warning("telegram: ignorado chat ajeno %s", chat_id)
                    continue
                if voz and self.voice_sink is not None:
                    try:
                        ruta = await asyncio.to_thread(self._bajar_voz,
                                                       voz["file_id"])
                        self.voice_sink(ruta)
                    except Exception as e:
                        log.warning("telegram voz: %s", e)
                        await self.send("No pude bajar ese audio, señor.")
                    continue
                if not texto:
                    log.info("telegram: mensaje sin texto ni voz, ignorado")
                    continue
                if texto == "/start":
                    await self.send("Acá estoy, señor.")
                    continue
                self.sink(texto)
