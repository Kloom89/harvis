"""Formato canónico de tools de KLOOM. La dependencia apunta hacia acá:
los drivers (Claude SDK, OpenAI-compat) consumen Tool vía sus adaptadores,
las tools nunca importan un SDK de vendor.

params: {"nombre": tipo} obligatorio, {"nombre": (tipo, default)} opcional,
o un JSON Schema completo (dict con "type") que se pasa tal cual.
El handler es async, recibe el dict de args y devuelve str.
"""
from dataclasses import dataclass
from typing import Any, Callable

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    handler: Callable


def kloom_tool(name: str, description: str, params: dict, meta: dict | None = None):
    """meta (opcional, para skills de la comunidad): category, tags,
    destructive, requires_confirmation... Hoy solo se almacena; la API
    queda estable para cuando el ecosistema la explote."""
    def deco(fn):
        t = Tool(name, description, params, fn)
        t.meta = meta or {}
        return t
    return deco


def _json_schema(params: dict) -> dict:
    if params.get("type") == "object":  # ya es JSON Schema completo
        return params
    props, required = {}, []
    for pname, spec in params.items():
        if isinstance(spec, tuple):
            ptype, _default = spec
        else:
            ptype = spec
            required.append(pname)
        props[pname] = {"type": _JSON_TYPES[ptype]}
    return {"type": "object", "properties": props, "required": required}


def to_openai(t: Tool) -> dict:
    return {"type": "function", "function": {
        "name": t.name, "description": t.description,
        "parameters": _json_schema(t.params),
    }}


def to_sdk(t: Tool):
    """Envuelve la Tool en el decorador del claude-agent-sdk."""
    from claude_agent_sdk import tool as sdk_tool

    # El schema simple del SDK no distingue opcionales; se pasa solo el tipo.
    if t.params.get("type") == "object":
        schema = t.params
    else:
        schema = {k: (v[0] if isinstance(v, tuple) else v)
                  for k, v in t.params.items()}

    async def wrapper(args: dict[str, Any], _t=t):
        import time as _time
        from trazas import ev
        _t0 = _time.monotonic()
        try:
            r = await _t.handler(args)
            ev("tool", nombre=_t.name, ok=True,
               dur_ms=round((_time.monotonic() - _t0) * 1000))
            return {"content": [{"type": "text", "text": r}]}
        except Exception as e:
            ev("tool", nombre=_t.name, ok=False, error=str(e)[:120],
               dur_ms=round((_time.monotonic() - _t0) * 1000))
            raise

    return sdk_tool(t.name, t.description, schema)(wrapper)
