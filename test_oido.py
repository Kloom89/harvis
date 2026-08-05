"""Pipeline oido→stt→wake sin acústica: inyecta audio en el callback."""
import asyncio, subprocess, sys, threading, time
import numpy as np
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

async def main():
    from kloom import load_config, match_wake
    from oido import Oido, SAMPLE_RATE
    cfg = load_config()
    loop = asyncio.get_running_loop()
    o = Oido(cfg, loop)
    threading.Thread(target=o._segmenter, daemon=True).start()

    pcm = subprocess.run(["ffmpeg","-y","-loglevel","error","-i","wake_test.mp3",
                          "-ar","16000","-ac","1","-f","f32le","-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, dtype=np.float32)
    audio = np.concatenate([audio, np.zeros(SAMPLE_RATE*3, np.float32)])

    def feed():  # bloques de 50 ms a ritmo real, como el mic
        blk = int(SAMPLE_RATE*0.05)
        for i in range(0, len(audio), blk):
            o._cb(audio[i:i+blk].reshape(-1,1), None, None, None)
            time.sleep(0.05)
    threading.Thread(target=feed, daemon=True).start()

    kind, seg = await asyncio.wait_for(o.queue.get(), timeout=20)
    print(f"evento: {kind}, {seg.size/SAMPLE_RATE:.1f}s de audio")
    from stt import Stt
    stt = Stt(cfg); stt.warm_up()
    text = stt.transcribe(seg)
    print(f"transcripto: {text!r}")
    cmd = match_wake(text, cfg)
    print(f"comando: {cmd!r}")
    assert cmd and "hora" in cmd.lower(), "pipeline roto"
    print("PIPELINE OK")

asyncio.run(main())
