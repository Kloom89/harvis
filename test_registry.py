"""Unit: conversión de las 12 tools reales a ambos formatos."""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from registry import Tool, to_openai, to_sdk
from tools import browser, claude_code, codigo, homelab, media, memoria, proyectos, teams, timers, vision, whatsapp, windows

ALL = (windows.TOOLS + claude_code.TOOLS + browser.TOOLS + media.TOOLS
       + timers.TOOLS + proyectos.TOOLS + memoria.TOOLS + homelab.TOOLS + codigo.TOOLS + whatsapp.TOOLS + vision.TOOLS + teams.TOOLS)

assert len(ALL) == 42, f"esperaba 42 tools, hay {len(ALL)}"
assert all(isinstance(t, Tool) for t in ALL)

for t in ALL:
    oai = to_openai(t)
    fn = oai["function"]
    assert oai["type"] == "function"
    assert fn["name"] == t.name
    schema = fn["parameters"]
    assert schema["type"] == "object"
    for pname, spec in t.params.items():
        assert pname in schema["properties"]
        if isinstance(spec, tuple):
            assert pname not in schema["required"], f"{t.name}.{pname} opcional"
        else:
            assert pname in schema["required"], f"{t.name}.{pname} requerido"

# get_weather: city opcional → fuera de required
gw = to_openai(media.get_weather)["function"]["parameters"]
assert gw["properties"]["city"] == {"type": "string"}
assert gw["required"] == []

# el adaptador SDK devuelve algo que create_sdk_mcp_server acepta
sdk = to_sdk(windows.open_app)
assert sdk.name == "open_app"

print("test_registry OK ✓")
