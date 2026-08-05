"""Unit del agent loop de CerebroJarvis con cliente falso: tool_calls,
tope de iteraciones, timeout con historial intacto, truncado por turnos."""
import asyncio
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import cerebro_jarvis
from cerebro_jarvis import CerebroJarvis
from registry import kloom_tool

CALLS = []


@kloom_tool("suma", "Suma dos enteros.", {"a": int, "b": int})
async def suma(args):
    CALLS.append(args)
    return str(args["a"] + args["b"])


class _TC:
    def __init__(self, id, name, args):
        self.id = id
        self.function = type("F", (), {"name": name, "arguments": args})()
    def model_dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name,
                             "arguments": self.function.arguments}}


def _resp(content=None, tool_calls=None):
    msg = type("M", (), {"content": content, "tool_calls": tool_calls})()
    choice = type("C", (), {"message": msg})()
    return type("R", (), {"choices": [choice]})()


class FakeCompletions:
    def __init__(self, script):
        self.script = list(script)
    async def create(self, **kw):
        item = self.script.pop(0) if self.script else _resp("sin guion")
        if callable(item):
            return await item()
        return item


def make(script):
    cfg = {"llm": {"system_prompt": "test"}}
    pcfg = {"base_url": "http://x/v1", "model": "m"}
    c = CerebroJarvis(cfg, "ollama", pcfg, [suma])
    c.client = type("K", (), {})()
    c.client.chat = type("Ch", (), {})()
    c.client.chat.completions = FakeCompletions(script)
    return c


async def main():
    # 1. tool call → resultado → respuesta final
    c = make([_resp(tool_calls=[_TC("1", "suma", '{"a": 2, "b": 3}')]),
              _resp("Da cinco, señor.")])
    reply = await c.ask("cuánto es dos más tres")
    assert reply == "Da cinco, señor.", reply
    assert CALLS == [{"a": 2, "b": 3}], CALLS
    tool_msgs = [m for m in c.messages if m["role"] == "tool"]
    assert tool_msgs[0]["content"] == "5"

    # 2. tope de iteraciones: siempre pide tools → corta a las 12
    c = make([_resp(tool_calls=[_TC(str(i), "suma", '{"a": 1, "b": 1}')])
              for i in range(20)])
    reply = await c.ask("loop infinito")
    assert "sin turnos" in reply, reply

    # 3. timeout total → historial intacto
    async def lenta():
        await asyncio.sleep(5)
        return _resp("tarde")
    cerebro_jarvis.TOTAL_TIMEOUT = 0.2
    c = make([lenta])
    before = list(c.messages)
    reply = await c.ask("hola")
    assert "no responde" in reply, reply
    assert c.messages == before, "el historial debía quedar como estaba"
    cerebro_jarvis.TOTAL_TIMEOUT = 60

    # 4. truncado por turnos: nunca queda un role:tool huérfano
    c = make([])
    budget = cerebro_jarvis.HISTORY_BUDGET
    for i in range(budget * 2):
        c.messages += [
            {"role": "user", "content": f"u{i}"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": str(i)}]},
            {"role": "tool", "tool_call_id": str(i), "content": "r"},
            {"role": "assistant", "content": f"a{i}"},
        ]
    c._truncate()
    assert len(c.messages) - 1 <= budget
    assert c.messages[0]["role"] == "system"
    assert c.messages[1]["role"] == "user", c.messages[1]
    for i, m in enumerate(c.messages):
        if m["role"] == "tool":
            prev = c.messages[i - 1]
            assert prev.get("tool_calls"), "tool huérfano tras truncar"

    # 5. error del proveedor → mensaje corto hablado, historial intacto
    async def explota():
        raise ValueError("boom")
    c = make([explota])
    before = list(c.messages)
    reply = await c.ask("hola")
    assert "error" in reply.lower(), reply
    assert c.messages == before

    print("test_jarvis OK ✓")


asyncio.run(main())
