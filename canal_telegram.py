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


class Telegram:
    def __init__(self, cfg, sink):
        """sink(texto): encola un comando (thread del loop asyncio)."""
        tcfg = cfg.get("telegram") or {}
        token = os.environ.get(tcfg.get("token_env", "TELEGRAM_BOT_TOKEN"), "")
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
    def _call(self, metodo: str, timeout: int = 15, **params) -> dict:
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(f"{self.api}/{metodo}", data=data)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

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
                    self._call, "getUpdates", timeout=60,
                    offset=offset, **{"timeout": 50})
            except Exception as e:
                log.warning("telegram poll: %s", e)
                await asyncio.sleep(10)
                continue
            for u in resp.get("result", []):
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                chat_id = (msg.get("chat") or {}).get("id")
                texto = (msg.get("text") or "").strip()
                if not chat_id or not texto:
                    continue
                if self.owner is None:
                    # primer contacto = emparejamiento
                    self.owner = chat_id
                    json.dump({"chat_id": chat_id}, open(OWNER_FILE, "w"))
                    log.info("telegram: dueño registrado %s", chat_id)
                    await self.send("Emparejado, señor. Este chat quedó "
                                    "como el único autorizado. Hábleme.")
                    continue
                if chat_id != self.owner:
                    log.warning("telegram: ignorado chat ajeno %s", chat_id)
                    continue
                if texto == "/start":
                    await self.send("Acá estoy, señor.")
                    continue
                self.sink(texto)
