"""Unit: el parser de requirements.txt del doctor (markers, comentarios,
pines) y la deteccion de host/puerto de los base_url de config.yaml."""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path

from doctor import _puerto_abierto, parse_requirements

crudo = """
# comentario suelto
claude-agent-sdk
faster-whisper>=1.0
pycaw          # medidor de audio

nvidia-cublas-cu12; sys_platform == "win32"
PyYAML==6.0.1
"""
assert parse_requirements(crudo) == [
    "claude-agent-sdk", "faster-whisper", "pycaw",
    "nvidia-cublas-cu12", "PyYAML"], parse_requirements(crudo)

# el requirements real no puede tener lineas que el parser se coma
real = parse_requirements(
    (Path(__file__).parent / "requirements.txt").read_text(encoding="utf-8"))
assert "faster-whisper" in real and "PyYAML" in real
assert all(nombre and " " not in nombre for nombre in real), real

# base_url invalido o vacio no puede explotar: es "no hay nada escuchando"
assert _puerto_abierto("") is False
assert _puerto_abierto("no-es-una-url") is False
# puerto cerrado a proposito (49151 = ultimo registrado, nadie lo usa)
assert _puerto_abierto("http://127.0.0.1:49151") is False

# La rama que mas importa para alguien que recien clona: ningun cerebro
# con credencial tiene que ser FALLA, no un warning que se pasa por alto.
import doctor

doctor._fallas.clear()
doctor.check_cerebros({"llm": {"brain": "groq", "providers": {
    "groq": {"driver": "openai", "api_key_env": "_NO_EXISTE_ESTA_VAR_"},
    "ollama": {"driver": "openai", "base_url": "http://127.0.0.1:49151/v1"},
}}})
assert len(doctor._fallas) == 1, doctor._fallas

doctor._fallas.clear()
doctor.check_cerebros({"llm": {"brain": "groq", "providers": {
    "ollama": {"driver": "openai", "base_url": "http://127.0.0.1:49151/v1"},
}, "fallback": []}})
assert doctor._fallas, "sin providers usables tiene que fallar"

print("test_doctor OK ✓")
