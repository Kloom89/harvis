"""Driver OpenAI-compatible: un solo agent loop para Ollama, Groq, Kimi,
OpenAI y Gemini. Mismas tools que el driver Claude, vía registry.to_openai."""
import asyncio
import json
import logging
import os
import re

from openai import APIConnectionError, APIStatusError, AsyncOpenAI

from registry import Tool, to_openai

log = logging.getLogger("kloom.jarvis")

MAX_TURNS = 12          # mismo tope que el driver Claude
REQUEST_TIMEOUT = 30    # por request
TOTAL_TIMEOUT = 60      # por comando completo
HISTORY_BUDGET = 40     # mensajes (sin contar el system)

# Diferencias por proveedor (lagunas de la capa compat de Gemini, tool_choice
# en Kimi/Groq, etc.). Vacío hasta que aparezcan; el loop consulta acá y no
# se llena de ifs.
QUIRKS: dict[str, dict] = {}


def _env_usuario(nombre: str) -> str:
    """setx no llega a procesos ya corriendo: fallback al registro de
    Windows, así una key nueva anda sin relogueo."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
        return winreg.QueryValueEx(k, nombre)[0]
    except OSError:
        return ""


class CerebroJarvis:
    def __init__(self, cfg: dict, name: str, pcfg: dict, tools: list[Tool]):
        key = "ollama"  # placeholder: Ollama no exige key
        env = pcfg.get("api_key_env")
        if env:
            key = os.environ.get(env, "") or _env_usuario(env)
            if not key:
                raise RuntimeError(f"Falta la variable de entorno {env}")
        self.name = name
        self.display = name.capitalize()
        self.model = pcfg["model"]
        self.client = AsyncOpenAI(base_url=pcfg["base_url"], api_key=key,
                                  timeout=REQUEST_TIMEOUT, max_retries=0)
        self.tools = {t.name: t for t in tools}
        # Descripciones recortadas a la primera oración: los free tiers
        # cobran por token del payload (Groq: 12k TPM) y 38 tools con
        # descripción completa son ~5k tokens por request.
        self.oai_tools = []
        for t in tools:
            o = to_openai(t)
            d = o["function"]["description"]
            corte = d.find(". ")
            if 0 < corte < len(d) - 10:
                o["function"]["description"] = d[:corte + 1]
            self.oai_tools.append(o)
        from tools.memoria import contexto_sistema
        system = ((cfg.get("llm") or {}).get("system_prompt", "")
                  + f"\nHoy tu motor es {self.display}."
                  + contexto_sistema())
        self.messages: list[dict] = [{"role": "system", "content": system}]

    async def connect(self):
        """Valida alcance y key con un GET barato; si no, el switch por voz
        no se entera hasta el primer comando."""
        await self.client.models.list()

    async def ask(self, text: str) -> str:
        snapshot = list(self.messages)
        self.messages.append({"role": "user", "content": text})
        try:
            async with asyncio.timeout(TOTAL_TIMEOUT):
                return await self._loop()
        except TimeoutError:
            self.messages = snapshot
            log.warning("%s: timeout total", self.name)
            return f"{self.display} no responde, señor."
        except Exception:
            self.messages = snapshot
            log.exception("%s: agent loop reventó", self.name)
            return f"{self.display} tiró un error, señor."

    async def _loop(self) -> str:
        for _ in range(MAX_TURNS):
            resp = await self._create()
            msg = resp.choices[0].message
            if msg.tool_calls:
                self.messages.append({
                    "role": "assistant", "content": msg.content or None,
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                })
                for tc in msg.tool_calls:
                    result = await self._run_tool(tc)
                    self.messages.append({"role": "tool",
                                          "tool_call_id": tc.id,
                                          "content": result})
                continue
            reply = (msg.content or "").strip()
            self.messages.append({"role": "assistant", "content": reply})
            self._truncate()
            return reply or "Hecho, señor."
        return "Me quedé sin turnos pensando eso, señor."

    async def _create(self):
        try:
            return await self._create_once()
        except (APIConnectionError, APIStatusError) as e:
            status = getattr(e, "status_code", None)
            if status is not None and status != 429 and status < 500:
                raise  # 4xx real (schema inválido, modelo inexistente): no reintentar
            # 429 con "try again in Xs": esperar lo que pide (tope 30 s),
            # no 2 s fijos que nunca alcanzan.
            m = re.search(r"try again in (\d+(?:\.\d+)?)", str(e))
            espera = min(float(m.group(1)) + 1, 30) if m else 2
            log.warning("%s: %s — reintento en %.0f s", self.name,
                        str(e)[:120], espera)
            await asyncio.sleep(espera)
            return await self._create_once()

    async def _create_once(self):
        kw = {"model": self.model, "messages": self.messages}
        if self.oai_tools:   # tools=[] da 400 en algunos proveedores
            kw["tools"] = self.oai_tools
        return await self.client.chat.completions.create(**kw)

    async def _run_tool(self, tc) -> str:
        name = tc.function.name
        tool = self.tools.get(name)
        if not tool:
            return f"No existe la herramienta '{name}'."
        import time as _time
        from trazas import ev
        _t0 = _time.monotonic()
        try:
            args = json.loads(tc.function.arguments or "{}")
            log.info("tool: %s %s", name, args)
            r = await tool.handler(args)
            ev("tool", nombre=name, ok=True,
               dur_ms=round((_time.monotonic() - _t0) * 1000))
            return r
        except Exception as e:
            log.exception("tool %s falló", name)
            ev("tool", nombre=name, ok=False, error=str(e)[:120],
               dur_ms=round((_time.monotonic() - _t0) * 1000))
            return f"La herramienta {name} falló: {e}"

    def _truncate(self):
        """Corta en fronteras de turno (role: user): nunca deja un mensaje
        tool huérfano de su tool_calls — la API devuelve 400 ante eso."""
        rest = self.messages[1:]
        if len(rest) <= HISTORY_BUDGET:
            return
        for i in range(len(rest) - HISTORY_BUDGET, len(rest)):
            if rest[i]["role"] == "user":
                self.messages = [self.messages[0]] + rest[i:]
                return
        self.messages = [self.messages[0]]  # sin frontera: contexto fresco

    async def ask_stream(self, text: str):
        """Los proveedores OpenAI-compat ya son rápidos (Groq ~300 tok/s);
        alcanza con soltar la respuesta entera de una."""
        yield await self.ask(text)

    async def close(self):
        await self.client.close()
