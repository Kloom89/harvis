"""Preflight: dice exactamente que le falta a esta PC para correr HARVIS.
Su razon de ser es diagnosticar cuando las dependencias NO estan, asi que
todo lo que no sea stdlib se importa adentro de un try. Salida en ingles:
es lo primero que ve alguien que llego por el README."""
import importlib.metadata as md
import os
import platform
import re
import shutil
import socket
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent
_fallas: list[str] = []

# Las wheels de CUDA pesan ~1.5 GB y sin GPU no sirven: faltar no es un
# error, faster-whisper cae solo a CPU/medium.
OPCIONALES = ("nvidia-",)


def ok(msg: str) -> None:
    print(f"[ ok ] {msg}")


def falla(msg: str, arreglo: str) -> None:
    print(f"[FAIL] {msg}")
    print(f"       -> {arreglo}")
    _fallas.append(msg)


def aviso(msg: str, nota: str = "") -> None:
    print(f"[warn] {msg}")
    if nota:
        print(f"       {nota}")


_NOMBRE = re.compile(r"^[A-Za-z0-9._-]+")


def parse_requirements(texto: str) -> list[str]:
    """Nombres de distribucion de un requirements.txt, sin markers ni
    versiones ni comentarios."""
    nombres = []
    for linea in texto.splitlines():
        linea = linea.split("#")[0].strip()
        if not linea:
            continue
        m = _NOMBRE.match(linea)
        if m:
            nombres.append(m.group(0))
    return nombres


def _hay_gpu() -> bool:
    return bool(shutil.which("nvidia-smi"))


def _puerto_abierto(url: str) -> bool:
    m = re.match(r"https?://([^:/]+)(?::(\d+))?", url or "")
    if not m:
        return False
    host = m.group(1)
    port = int(m.group(2) or (443 if url.startswith("https") else 80))
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def check_sistema() -> None:
    if platform.system() == "Windows":
        ok(f"Windows {platform.release()}")
    else:
        falla(f"{platform.system()} is not supported",
              "HARVIS uses win32 APIs, WASAPI audio and UIA. Windows only.")
    v = sys.version_info
    if v >= (3, 12):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        falla(f"Python {v.major}.{v.minor} is too old",
              "Install Python 3.12+ from python.org and recreate the venv.")


def check_venv() -> None:
    if sys.prefix == sys.base_prefix:
        aviso("not running inside a virtualenv",
              "Expected: .venv\\Scripts\\python.exe doctor.py")
    else:
        ok(f"virtualenv: {sys.prefix}")


def check_dependencias() -> None:
    req = RAIZ / "requirements.txt"
    if not req.exists():
        falla("requirements.txt not found",
              f"Run doctor from the repo root ({RAIZ}).")
        return
    faltan, faltan_opt = [], []
    for nombre in parse_requirements(req.read_text(encoding="utf-8")):
        try:
            md.distribution(nombre)
        except md.PackageNotFoundError:
            if nombre.startswith(OPCIONALES):
                faltan_opt.append(nombre)
            else:
                faltan.append(nombre)
    if faltan:
        falla(f"{len(faltan)} missing package(s): {', '.join(faltan)}",
              ".venv\\Scripts\\pip install -r requirements.txt")
    else:
        ok("all required packages installed")
    if faltan_opt and _hay_gpu():
        aviso("CUDA wheels missing - your NVIDIA GPU will sit idle",
              ".venv\\Scripts\\pip install " + " ".join(faltan_opt))
    elif faltan_opt:
        ok("CUDA wheels skipped (no NVIDIA GPU) - Whisper runs on CPU")


def check_config() -> dict | None:
    cfg_path = RAIZ / "config.yaml"
    if not cfg_path.exists():
        falla("config.yaml not found", f"Restore it from the repo ({RAIZ}).")
        return None
    try:
        import yaml
    except ImportError:
        aviso("skipping config checks (PyYAML not installed yet)")
        return None
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        falla(f"config.yaml does not parse: {e}",
              "Fix the YAML syntax or restore the file from the repo.")
        return None
    ok("config.yaml parses")
    return cfg


def check_cerebros(cfg: dict) -> None:
    llm = cfg.get("llm") or {}
    providers = llm.get("providers") or {}
    if not providers:
        falla("no brains configured in config.yaml",
              "Restore the llm.providers block from the repo.")
        return
    listos, pendientes = [], []
    for nombre, p in providers.items():
        env = p.get("api_key_env")
        if p.get("driver") == "sdk":
            # El SDK de Claude usa el login de la CLI o una API key.
            if shutil.which("claude") or os.environ.get("ANTHROPIC_API_KEY"):
                listos.append(nombre)
            else:
                pendientes.append(f"{nombre}: no Claude CLI login "
                                  f"(https://claude.com/claude-code)")
        elif env:
            if os.environ.get(env):
                listos.append(nombre)
            else:
                pendientes.append(f"{nombre}: {env} is not set")
        elif _puerto_abierto(p.get("base_url", "")):
            listos.append(nombre)
        else:
            pendientes.append(f"{nombre}: nothing listening on "
                              f"{p.get('base_url')}")
    if listos:
        ok(f"{len(listos)} brain(s) ready: {', '.join(listos)}")
        for p in pendientes:
            print(f"       (idle) {p}")
        activo = llm.get("brain")
        if activo and activo not in listos:
            aviso(f"the active brain '{activo}' is NOT one of them",
                  f"HARVIS will fall back to: {llm.get('fallback')}")
    else:
        falla("no usable brain - HARVIS cannot think",
              "Cheapest path: a free Groq key (console.groq.com/keys) then "
              "setx GROQ_API_KEY gsk_...  - or install Ollama for offline.")
        for p in pendientes:
            print(f"       {p}")


def check_microfono() -> None:
    try:
        import sounddevice as sd
    except Exception:
        aviso("skipping mic check (sounddevice not installed yet)")
        return
    try:
        entradas = [d for d in sd.query_devices()
                    if d.get("max_input_channels", 0) > 0]
    except Exception as e:
        falla(f"cannot query audio devices: {e}",
              "Check that Windows audio services are running.")
        return
    if entradas:
        ok(f"{len(entradas)} input device(s), default: "
           f"{sd.query_devices(kind='input')['name']}")
    else:
        falla("no microphone found",
              "Plug one in and allow mic access in Windows privacy settings.")


def check_gpu() -> None:
    if _hay_gpu():
        ok("NVIDIA GPU detected - Whisper large-v3 on CUDA")
    else:
        aviso("no NVIDIA GPU - Whisper falls back to CPU/medium",
              "It works, just slower. Set stt.device: cpu in config.yaml "
              "to skip the CUDA attempt at boot.")


def main() -> int:
    print("HARVIS doctor\n")
    check_sistema()
    check_venv()
    check_dependencias()
    cfg = check_config()
    if cfg:
        check_cerebros(cfg)
    check_microfono()
    check_gpu()
    print()
    if _fallas:
        print(f"{len(_fallas)} problem(s) to fix before HARVIS runs.")
        return 1
    print("All good. Run kloom.cmd and say the wake word.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
