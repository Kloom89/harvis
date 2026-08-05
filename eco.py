"""Cancelación de eco (AEC) con WebRTC APM: al mic se le RESTA lo que está
saliendo por los parlantes (música, el propio TTS), capturado por loopback
WASAPI. Resultado: HARVIS te escucha limpio aunque la música esté fuerte.

Medido en esta PC: ~22 dB de atenuación del eco. Si algo falla (sin
loopback, driver raro), cae a passthrough y lo dice UNA vez en el log.
"""
import logging
import queue
import threading

import numpy as np

log = logging.getLogger("kloom.eco")

SR = 16000
FRAME = 160          # 10 ms — el APM procesa de a este tamaño


class CancelEco:
    def __init__(self, delay_ms: int = 120, ns_level: int = 2):
        from aec_audio_processing import AudioProcessor
        self.apm = AudioProcessor(enable_aec=True, enable_ns=True,
                                  ns_level=ns_level, enable_agc=False,
                                  enable_vad=False)
        self.apm.set_stream_format(SR, 1)
        self.apm.set_reverse_stream_format(SR, 1)
        self.apm.set_stream_delay(delay_ms)
        self._rev_q: queue.Queue = queue.Queue(maxsize=200)
        self._rev_resto = np.zeros(0, np.int16)
        self._roto = False
        self._stop = threading.Event()
        threading.Thread(target=self._loopback, daemon=True,
                         name="eco-loopback").start()

    # ---------- captura de lo que SUENA (thread propio) ----------
    def _loopback(self):
        try:
            import pyaudiowpatch as pa
            p = pa.PyAudio()
            wasapi = p.get_host_api_info_by_type(pa.paWASAPI)
            salida = p.get_device_info_by_index(wasapi["defaultOutputDevice"])
            lb = None
            for d in p.get_loopback_device_info_generator():
                if salida["name"] in d["name"]:
                    lb = d
                    break
            if lb is None:
                lb = next(p.get_loopback_device_info_generator())
            sr_lb, ch = int(lb["defaultSampleRate"]), int(lb["maxInputChannels"])
            log.info("AEC: loopback %s @%dHz x%d", lb["name"], sr_lb, ch)
            st = p.open(format=pa.paInt16, channels=ch, rate=sr_lb,
                        input=True, input_device_index=lb["index"],
                        frames_per_buffer=sr_lb // 100)
            paso = sr_lb / SR
            resto = np.zeros(0, np.float32)
            while not self._stop.is_set():
                raw = np.frombuffer(
                    st.read(sr_lb // 100, exception_on_overflow=False),
                    np.int16).astype(np.float32)
                mono = raw.reshape(-1, ch).mean(axis=1)
                resto = np.concatenate([resto, mono])
                n16 = int(len(resto) / paso)
                if n16 >= FRAME:
                    idx = (np.arange(n16) * paso).astype(int)
                    try:
                        self._rev_q.put_nowait(
                            np.clip(resto[idx], -32767, 32767)
                            .astype(np.int16))
                    except queue.Full:
                        pass   # el consumidor drena; perder un frame no duele
                    resto = resto[int(n16 * paso):]
            st.close()
            p.terminate()
        except Exception:
            self._roto = True
            log.exception("AEC: loopback murió — sigo SIN cancelación")

    # ---------- procesamiento del mic (en el thread del callback) ----------
    def procesar(self, frame_f32: np.ndarray) -> np.ndarray:
        """Recibe el bloque del mic (float32 [-1,1], múltiplo de 160) y
        devuelve la versión con el eco cancelado."""
        if self._roto:
            return frame_f32
        try:
            try:
                while True:
                    self._rev_resto = np.concatenate(
                        [self._rev_resto, self._rev_q.get_nowait()])
            except queue.Empty:
                pass
            while len(self._rev_resto) >= FRAME:
                self.apm.process_reverse_stream(
                    self._rev_resto[:FRAME].tobytes())
                self._rev_resto = self._rev_resto[FRAME:]
            entrada = np.clip(frame_f32 * 32767, -32767, 32767).astype(np.int16)
            salida = np.empty_like(entrada)
            for i in range(0, len(entrada), FRAME):
                out = self.apm.process_stream(entrada[i:i + FRAME].tobytes())
                salida[i:i + FRAME] = np.frombuffer(out, np.int16)
            return salida.astype(np.float32) / 32768.0
        except Exception:
            self._roto = True
            log.exception("AEC: procesamiento falló — sigo SIN cancelación")
            return frame_f32

    def cerrar(self):
        self._stop.set()
