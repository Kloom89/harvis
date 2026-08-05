"""Huella acústica del wake word: compara el ARRANQUE de cada frase contra
grabaciones REALES del usuario diciendo "Harvis" (dataset/enroll/). Vía de
rescate cuando Whisper mangla el nombre ("Cabrón", "Neha"...): el texto
falla pero el sonido es el sonido. MFCC + DTW a mano — cero dependencias.

Enrolar: python grabar_harvis.py (guarda takes + calibra el umbral).
"""
import glob
import json
import logging
import os
import wave

import numpy as np

log = logging.getLogger("kloom.huella")

SR = 16000
_WIN, _HOP, _NFFT = 400, 160, 512      # 25 ms cada 10 ms
_N_MEL, _N_MFCC = 26, 13
_VENTANA = 2.5      # segundos del arranque de la frase donde buscar
_PASO = 0.15        # corrimiento entre ventanas candidatas
_UMBRAL_DEFAULT = 12.0   # medido: mismo hablante ~7-12, habla ajena ~16+


def _mel_fb() -> np.ndarray:
    def hz2mel(f):
        return 2595 * np.log10(1 + f / 700)
    def mel2hz(m):
        return 700 * (10 ** (m / 2595) - 1)
    pts = mel2hz(np.linspace(hz2mel(80), hz2mel(SR / 2), _N_MEL + 2))
    bins = np.floor((_NFFT + 1) * pts / SR).astype(int)
    fb = np.zeros((_N_MEL, _NFFT // 2 + 1))
    for i in range(_N_MEL):
        a, b, c = bins[i], bins[i + 1], bins[i + 2]
        if b > a:
            fb[i, a:b] = (np.arange(a, b) - a) / (b - a)
        if c > b:
            fb[i, b:c] = (c - np.arange(b, c)) / (c - b)
    return fb


def _dct_mat() -> np.ndarray:
    n = np.arange(_N_MEL)
    return np.cos(np.pi * np.outer(np.arange(_N_MFCC + 1), (2 * n + 1))
                  / (2 * _N_MEL))


_FB = _mel_fb()
_DCT = _dct_mat()


def mfcc(audio: np.ndarray) -> np.ndarray:
    """(frames, 13) con normalización de ganancia y de canal (CMVN)."""
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    if 0.002 < peak:
        audio = audio * (0.5 / peak)
    if audio.size < _WIN:
        return np.zeros((1, _N_MFCC), np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(audio, _WIN)[::_HOP]
    frames = frames * np.hanning(_WIN)
    spec = np.abs(np.fft.rfft(frames, _NFFT)) ** 2
    mel = np.log(spec @ _FB.T + 1e-10)
    coef = (mel @ _DCT.T)[:, 1:]           # sin c0 (energía absoluta)
    return (coef - coef.mean(axis=0)).astype(np.float32)


def dtw(a: np.ndarray, b: np.ndarray, banda: int = 25) -> float:
    """Distancia DTW normalizada por largo de camino (banda Sakoe-Chiba).
    Matriz de costos vectorizada; el DP va sobre escalares."""
    n, m = len(a), len(b)
    banda = max(banda, abs(n - m) + 5)   # siempre existe camino válido
    costos = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)
    D = np.full((n + 1, m + 1), np.inf, np.float32)
    D[0, 0] = 0
    for i in range(1, n + 1):
        j0, j1 = max(1, i - banda), min(m, i + banda)
        fila, prev = D[i], D[i - 1]
        ci = costos[i - 1]
        for j in range(j0, j1 + 1):
            fila[j] = ci[j - 1] + min(prev[j], fila[j - 1], prev[j - 1])
    return float(D[n, m]) / (n + m)


def cargar_wav(ruta: str) -> np.ndarray:
    with wave.open(ruta, "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def recortar_silencio(audio: np.ndarray, margen: float = 0.1) -> np.ndarray:
    """Deja solo la palabra: recorta colas por energía."""
    if not audio.size:
        return audio
    e = np.abs(audio)
    umbral = max(float(e.max()) * 0.08, 0.004)
    idx = np.where(e > umbral)[0]
    if not idx.size:
        return audio
    m = int(SR * margen)
    return audio[max(0, idx[0] - m):min(audio.size, idx[-1] + m)]


class Huella:
    def __init__(self, templates: list[np.ndarray], umbral: float):
        self.templates = templates
        self.umbral = umbral

    @classmethod
    def cargar(cls, carpeta: str):
        """None si no hay takes enrolados — el llamador sigue sin huella."""
        rutas = sorted(glob.glob(os.path.join(carpeta, "*.wav")))
        if not rutas:
            return None
        try:
            templates = [mfcc(recortar_silencio(cargar_wav(r)))
                         for r in rutas]
            umbral = _UMBRAL_DEFAULT
            meta = os.path.join(carpeta, "umbral.json")
            if os.path.exists(meta):
                umbral = float(json.load(open(meta))["umbral"])
            log.info("huella de voz: %d takes, umbral %.1f",
                     len(templates), umbral)
            return cls(templates, umbral)
        except Exception:
            log.exception("huella no cargó — sigo sin ella")
            return None

    def distancia(self, audio: np.ndarray) -> float:
        """Mínima distancia entre las ventanas del arranque y los takes."""
        arranque = audio[:int(SR * _VENTANA)]
        mejores = np.inf
        for t in self.templates:
            dur = int((len(t) * _HOP + _WIN) * 1.3)   # ventana ~ largo take
            paso = int(SR * _PASO)
            for i in range(0, max(1, arranque.size - dur // 2), paso):
                tramo = arranque[i:i + dur]
                if tramo.size < _WIN * 4:
                    break
                d = dtw(mfcc(tramo), t)
                mejores = min(mejores, d)
        return mejores

    def match(self, audio: np.ndarray, margen: float = 0.0) -> bool:
        """margen: tolerancia extra (p.ej. con música de fondo la voz
        mezclada da distancias más altas; las letras dan 18+ igual)."""
        d = self.distancia(audio)
        log.debug("huella: distancia %.1f (umbral %.1f%+.1f)", d,
                  self.umbral, margen)
        return d < self.umbral + margen
