"""Micrófono siempre abierto. Dos fuentes de frases:

- VAD: detecta habla, corta al silencio → evento ("utterance", audio).
- PTT: tecla mantenida → evento ("ptt", audio) al soltar, sin VAD.

Corre en threads (callback de sounddevice + poller); empuja eventos a una
asyncio.Queue del loop principal. `mute()` descarta el mic mientras KLOOM
piensa o habla, para no escucharse a sí mismo."""
import asyncio
import logging
import threading
import time

import numpy as np
import sounddevice as sd
from pynput import keyboard as pk
from faster_whisper.vad import VadOptions, get_speech_timestamps

log = logging.getLogger("kloom.oido")

SAMPLE_RATE = 16000
_BLOCK = int(SAMPLE_RATE * 0.05)          # 50 ms
_POLL = 0.25                              # cada cuánto corre el VAD
_VAD_WINDOW = 0.6                         # segundos que mira el VAD
_PRE_ROLL = 0.5                           # audio previo al arranque de habla


def _has_speech(window: np.ndarray) -> bool:
    opts = VadOptions(threshold=0.5, min_speech_duration_ms=150)
    return bool(get_speech_timestamps(window, opts, sampling_rate=SAMPLE_RATE))


class Oido:
    def __init__(self, cfg: dict, loop: asyncio.AbstractEventLoop):
        vcfg = cfg.get("vad") or {}
        self.silence_end = float(vcfg.get("silence_end", 1.2))
        self.max_utterance = float(vcfg.get("max_utterance", 30))
        # AEC: restar del mic lo que suena por los parlantes (música/TTS).
        self.eco = None
        acfg = cfg.get("aec") or {}
        if acfg.get("enabled", True):
            try:
                from eco import CancelEco
                self.eco = CancelEco(
                    delay_ms=int(acfg.get("delay_ms", 120)),
                    ns_level=int(acfg.get("ns_level", 2)))
                log.info("AEC activo (delay %s ms)",
                         acfg.get("delay_ms", 120))
            except Exception:
                log.exception("AEC no disponible — sigo sin cancelación")
        self.ptt_key = (cfg.get("ptt") or {}).get("key", "f8")
        self.abort_key = (cfg.get("ptt") or {}).get("abort_key", "f9")
        self.on_abort = lambda: None   # lo setea kloom: corta el turno
        self.loop = loop
        self.queue: asyncio.Queue = asyncio.Queue()
        self._buf = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()
        self._muted = False
        self._ptt_down = False
        self._ptt_start = 0

    def mute(self):
        self._muted = True
        with self._lock:
            self._buf = np.zeros(0, dtype=np.float32)

    def unmute(self):
        self._muted = False

    def _emit(self, kind: str, audio: np.ndarray):
        self.loop.call_soon_threadsafe(self.queue.put_nowait, (kind, audio))

    _cb_error_ts = 0.0

    def _cb(self, indata, _frames, _time, _status):
        self._last_cb = time.monotonic()   # latido: el stream sigue vivo
        if self._muted:
            return
        try:
            frame = indata[:, 0].copy()
            if self.eco is not None:
                frame = self.eco.procesar(frame)
            with self._lock:
                self._buf = np.concatenate([self._buf, frame])
        except MemoryError:
            # apretón de RAM del sistema: soltar ESTE frame y seguir vivo
            # (sin esto, la excepción en el callback CFFI abre un popup y
            # el buffer queda en cualquier estado).
            if time.monotonic() - self._cb_error_ts > 60:
                self._cb_error_ts = time.monotonic()
                log.warning("sin memoria para el buffer del mic; "
                            "descarto frames hasta que afloje")
            with self._lock:
                self._buf = np.zeros(0, dtype=np.float32)
            return
            # cap: pre-roll + frase máxima
            cap = int(SAMPLE_RATE * (self.max_utterance + _PRE_ROLL + 1))
            if self._buf.size > cap and not self._ptt_down:
                self._buf = self._buf[-cap:].copy()  # soltar el array viejo

    def _on_ptt_press(self):
        if self._ptt_down or self._muted:
            return
        self._ptt_down = True
        with self._lock:
            self._ptt_start = self._buf.size
        self._emit("ptt_start", np.zeros(0, np.float32))

    def _on_ptt_release(self):
        if not self._ptt_down:
            return
        self._ptt_down = False
        time.sleep(0.15)  # colita: lo último dicho al soltar
        with self._lock:
            audio = self._buf[self._ptt_start:].copy()
            self._buf = np.zeros(0, dtype=np.float32)
        self._emit("ptt", audio)

    def _abrir_stream(self):
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            callback=self._cb, blocksize=_BLOCK,
        )
        self._stream.start()
        self._last_cb = time.monotonic()

    def _reabrir_stream(self):
        """PortAudio puede morir mudo (cambio de dispositivo, glitch USB):
        el mic queda 'abierto' pero congelado. Se cierra y se reabre."""
        try:
            self._stream.abort()
            self._stream.close()
        except Exception:
            pass
        try:
            self._abrir_stream()
            with self._lock:
                self._buf = np.zeros(0, dtype=np.float32)
            log.warning("stream de audio relanzado")
        except Exception:
            log.exception("no pude relanzar el stream; reintento en 5 s")
            time.sleep(5)
            self._last_cb = time.monotonic()  # espaciar reintentos

    def start(self):
        self._abrir_stream()
        ptt = getattr(pk.Key, self.ptt_key, None) or pk.KeyCode.from_char(self.ptt_key)
        ab = getattr(pk.Key, self.abort_key, None) \
            or pk.KeyCode.from_char(self.abort_key)

        def _press(k):
            if k == ptt:
                self._on_ptt_press()
            elif k == ab:
                self.on_abort()

        self._kb_listener = pk.Listener(
            on_press=_press,
            on_release=lambda k: k == ptt and self._on_ptt_release(),
        )
        self._kb_listener.start()
        threading.Thread(target=self._segmenter_guard, daemon=True).start()
        log.info("mic abierto, PTT=%s", self.ptt_key)

    def _segmenter_guard(self):
        """Si el segmenter muere (p.ej. el VAD no pudo cargar), el mic queda
        'abierto' pero sordo para siempre — se loguea y se relanza."""
        while True:
            try:
                self._segmenter()
            except Exception:
                log.exception("segmenter murió; relanzo en 3 s")
                time.sleep(3)

    def _segmenter(self):
        """Corte de frases por VAD (solo cuando no hay PTT activo)."""
        in_speech = False
        speech_start = 0          # índice en el buffer donde arrancó
        last_speech = 0.0         # timestamp del último bloque con voz
        ultimo_nivel = 0.0        # para diagnosticar mic muerto vs mudo
        while True:
            time.sleep(_POLL)
            muerto = time.monotonic() - self._last_cb
            if muerto > 5:
                log.warning("stream de audio muerto (%.0f s sin frames) — "
                            "relanzo", muerto)
                self._reabrir_stream()
                in_speech = False
                continue
            if time.monotonic() - ultimo_nivel > 10:
                ultimo_nivel = time.monotonic()
                with self._lock:
                    w = self._buf[-int(SAMPLE_RATE * _VAD_WINDOW):]
                log.debug("nivel mic: peak=%.4f buf=%.1fs muted=%s",
                          float(abs(w).max()) if w.size else -1,
                          self._buf.size / SAMPLE_RATE, self._muted)
            if self._muted or self._ptt_down:
                in_speech = False
                continue
            with self._lock:
                snap = self._buf
                size = snap.size
            if size < int(SAMPLE_RATE * _VAD_WINDOW):
                continue
            window = snap[-int(SAMPLE_RATE * _VAD_WINDOW):]
            speech = _has_speech(window)
            now = time.monotonic()
            if speech:
                last_speech = now
                if not in_speech:
                    in_speech = True
                    speech_start = max(0, size - int(SAMPLE_RATE * (_VAD_WINDOW + _PRE_ROLL)))
            elif in_speech and now - last_speech >= self.silence_end:
                in_speech = False
                with self._lock:
                    audio = self._buf[speech_start:].copy()
                    self._buf = np.zeros(0, dtype=np.float32)
                if audio.size >= SAMPLE_RATE // 2:
                    self._emit("utterance", audio)
            if in_speech and size - speech_start > SAMPLE_RATE * self.max_utterance:
                # frase demasiado larga: cortar igual
                in_speech = False
                with self._lock:
                    audio = self._buf[speech_start:].copy()
                    self._buf = np.zeros(0, dtype=np.float32)
                self._emit("utterance", audio)
