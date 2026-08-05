"""Checks mínimos: match_wake + STT sintético + tool de hora."""
import asyncio, subprocess, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import numpy as np

def test_match_wake():
    from kloom import load_config, match_wake
    cfg = load_config()
    cases = [
        ("Jarvis, abrí el navegador.", "abrí el navegador."),
        ("charbis, ¿qué hora es?", "qué hora es?"),
        ("Sharvis abrí spotify", "abrí spotify"),
        ("Jarvis.", ""),
        ("Hola, ¿cómo andás?", None),
        ("El servicio anda mal hoy.", None),
        ("Me servís un mate?", None),
        ("Chervis, pausá la música", "pausá la música"),
        ("Me tomé un jarabe.", None),
    ]
    for text, want in cases:
        got = match_wake(text, cfg)
        assert got == want, f"match_wake({text!r}) = {got!r}, esperaba {want!r}"
    print("match_wake OK")

def test_stt():
    import edge_tts
    from kloom import load_config
    from stt import Stt
    async def synth(t, p):
        await edge_tts.Communicate(t, "es-AR-TomasNeural").save(p)
    frase = "Jarvis, abrí la calculadora y decime qué hora es"
    asyncio.run(synth(frase, "t.mp3"))
    pcm = subprocess.run(["ffmpeg","-y","-loglevel","error","-i","t.mp3",
                          "-ar","16000","-ac","1","-f","f32le","-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, dtype=np.float32)
    stt = Stt(load_config()); stt.warm_up()
    import time; t0=time.time()
    text = stt.transcribe(audio)
    dt = time.time()-t0
    print(f"STT ({dt:.2f}s): {text!r}")
    assert dt < 2.0, "muy lento, no está en GPU?"
    from kloom import match_wake, load_config as lc
    cmd = match_wake(text, lc())
    assert cmd and "calculadora" in cmd.lower(), f"wake no matcheó: {text!r}"
    print("STT + wake OK")

def test_tools():
    from tools.media import get_time
    r = asyncio.run(get_time.handler({}))
    print("get_time:", r)
    from tools.windows import _index_apps, _find_app
    apps = _index_apps()
    assert len(apps) > 10, f"solo {len(apps)} apps indexadas"
    print(f"apps indexadas: {len(apps)}; 'calculadora' → {_find_app('calculadora') or _find_app('calculator')}")

if __name__ == "__main__":
    test_match_wake()
    test_tools()
    test_stt()
    print("\nTODO OK")
