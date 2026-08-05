"""Enrolamiento del wake word con TU voz: graba varios takes de "Harvis",
los recorta, calibra el umbral y listo — HARVIS los usa al reiniciar.

Uso:  .venv\\Scripts\\python.exe grabar_harvis.py
(HARVIS puede quedar corriendo: el mic en Windows es compartido.)
"""
import json
import os
import sys
import time
import wave

import numpy as np
import sounddevice as sd

sys.stdout.reconfigure(encoding="utf-8")

from huella import SR, dtw, mfcc, recortar_silencio

BASE = os.path.dirname(os.path.abspath(__file__))
CARPETA = os.path.join(BASE, "dataset", "enroll")
TAKES = 6
DUR = 2.0


def beep():
    t = np.arange(int(SR * 0.12)) / SR
    tono = (0.4 * np.sin(2 * np.pi * 990 * t)).astype(np.float32)
    sd.play(tono, SR)
    sd.wait()


def grabar() -> np.ndarray:
    audio = sd.rec(int(SR * DUR), samplerate=SR, channels=1,
                   dtype="float32")
    sd.wait()
    return audio[:, 0]


def main():
    os.makedirs(CARPETA, exist_ok=True)
    print(f"Vas a grabar {TAKES} takes diciendo SOLO «Harvis», como le "
          "hablás siempre.\nDespués del beep tenés 2 segundos. Variá el "
          "tono: normal, rápido, desde lejos, con la tele de fondo.\n")
    input("Enter para arrancar...")
    tomas = []
    i = 0
    while len(tomas) < TAKES:
        i += 1
        print(f"\nTake {len(tomas) + 1}/{TAKES} — decí «Harvis» tras el beep")
        time.sleep(0.6)
        beep()
        crudo = grabar()
        palabra = recortar_silencio(crudo)
        dur = palabra.size / SR
        if dur < 0.25 or float(np.abs(palabra).max()) < 0.01:
            print("  no te escuché — de nuevo")
            continue
        print(f"  ok ({dur:.2f} s, pico {float(np.abs(palabra).max()):.2f})")
        tomas.append(palabra)
    # guardar
    for n, a in enumerate(tomas, 1):
        with wave.open(os.path.join(CARPETA, f"harvis-{n:02d}.wav"),
                       "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((a * 32767).astype("int16").tobytes())
    # calibrar: leave-one-out entre tus propios takes
    feats = [mfcc(a) for a in tomas]
    dists = [dtw(feats[i], feats[j])
             for i in range(len(feats)) for j in range(len(feats)) if i < j]
    peor = max(dists)
    umbral = round(peor * 1.25, 1)
    json.dump({"umbral": umbral, "takes": len(tomas),
               "distancias": [round(d, 1) for d in dists]},
              open(os.path.join(CARPETA, "umbral.json"), "w"))
    print(f"\nListo: {len(tomas)} takes guardados en dataset/enroll/")
    print(f"Distancias entre tus takes: {[round(d, 1) for d in dists]}")
    print(f"Umbral calibrado: {umbral}")
    print("\nReiniciá HARVIS y ya te reconoce por el SONIDO, no solo "
          "por el texto.")


if __name__ == "__main__":
    main()
