"""faster-whisper en CUDA. Las DLL de cuBLAS/cuDNN vienen de los wheels de
pip (nvidia-*-cu12); hay que meterlas en el PATH ANTES de importar
faster_whisper o ctranslate2 tira "cublas64_12.dll not found"."""
import glob
import logging
import os

_nvidia = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       ".venv", "Lib", "site-packages", "nvidia")
_dirs = glob.glob(os.path.join(_nvidia, "*", "bin"))
os.environ["PATH"] = os.pathsep.join(_dirs) + os.pathsep + os.environ["PATH"]
for _d in _dirs:
    os.add_dll_directory(_d)

import re
import time

import numpy as np
from faster_whisper import WhisperModel

log = logging.getLogger("kloom.stt")

SAMPLE_RATE = 16000


class Stt:
    def __init__(self, cfg: dict):
        scfg = cfg.get("stt") or {}
        self.language = scfg.get("language", "es")
        self.no_speech_max = float(scfg.get("no_speech_max", 0.6))
        self.logprob_min = float(scfg.get("logprob_min", -1.0))
        self.hotwords = scfg.get("hotwords", "Jarvis")
        # Alucinaciones determinísticas de Whisper es (su corpus de YouTube):
        # si el transcript ENTERO es una de estas, es ruido, no habla.
        self.alucinaciones = {
            a.lower().strip(".!¡¿? ") for a in scfg.get("alucinaciones", [
                "suscríbete al canal", "suscríbete", "gracias por ver",
                "gracias por ver el video", "gracias", "hasta la próxima",
                "nos vemos en el próximo video",
                "subtítulos realizados por la comunidad de amara.org",
            ])}
        # Muletillas que Whisper inventa ante un soplido; nunca son un
        # comando por sí solas ("sí"/"no" NO están: son respuestas válidas).
        self.muletillas = set(scfg.get("muletillas", [
            "y", "e", "o", "a", "eh", "ah", "mm", "mmm", "este",
            "jaja", "jajaja",
        ]))
        self.short_no_speech_max = float(scfg.get("short_no_speech_max", 0.3))
        self.short_logprob_min = float(scfg.get("short_logprob_min", -0.6))
        self.wake_word = str((cfg.get("wake") or {})
                             .get("word", "harvis")).strip().lower()
        # Correcciones post-transcripción (config stt.text_corrections):
        # p.ej. "Harviss" → "Harvis" antes del parser de comandos.
        self.correcciones = [
            (re.compile(c["pattern"]), c["replace"])
            for c in scfg.get("text_corrections", [])]
        model = scfg.get("model", "large-v3")
        if scfg.get("device", "cuda") == "cuda":
            try:
                self.model = WhisperModel(model, device="cuda",
                                          compute_type="int8_float16")
                log.info("whisper %s en CUDA", model)
            except Exception as e:
                log.warning("CUDA falló (%s) — cayendo a medium/CPU", e)
                self.model = WhisperModel("medium", device="cpu",
                                          compute_type="int8")
        else:
            self.model = WhisperModel(model, device="cpu", compute_type="int8")

    def warm_up(self) -> None:
        # El primer transcribe tras cargar compila kernels (puede tardar
        # ~1 min la primerísima vez); hacerlo acá y no cuando el usuario habla.
        segs, _ = self.model.transcribe(np.zeros(SAMPLE_RATE, np.float32),
                                        language=self.language, beam_size=1)
        list(segs)

    def transcribe(self, audio: np.ndarray) -> str:
        if audio.size == 0:
            return ""
        # Ganancia automática: un mic lejano o con perilla baja entrega
        # picos de 0.03-0.06 y Whisper pierde confianza → el filtro come
        # frases reales. Se normaliza a ~0.5 con tope de 15x para no
        # amplificar ruido puro.
        peak = float(np.abs(audio).max())
        if 0.002 < peak < 0.35:
            audio = audio * min(0.5 / peak, 15.0)
        # Un fallo de Whisper (CUDA OOM cuando la GPU está exigida) NO puede
        # matar a HARVIS: reintento corto y si no, se descarta la frase.
        def _correr():
            s, _ = self.model.transcribe(audio, language=self.language,
                                         beam_size=1, vad_filter=True,
                                         hotwords=self.hotwords)
            return list(s)   # materializa: los errores saltan ACÁ, no después
        try:
            segs = _correr()
        except Exception as e:
            log.warning("whisper falló (%s) — reintento en 2 s",
                        str(e)[:120])
            time.sleep(2)
            try:
                segs = _correr()
            except Exception:
                log.exception("whisper falló de nuevo; descarto la frase")
                return ""
        # Con música o ruido de fondo Whisper alucina frases de su corpus de
        # YouTube ("Gracias", "Suscríbete al canal"). Se descartan por
        # confianza baja del segmento, no por lista negra de frases.
        kept = []
        for s in segs:
            corr = s.text
            for rx, reemplazo in self.correcciones:
                corr = rx.sub(reemplazo, corr)
            # "Harvis" es palabra inventada: Whisper la transcribe SIEMPRE
            # con logprob bajo (-1.2 a -2.8 en muestras reales). Si el
            # segmento nombra el wake word, el filtro de confianza no
            # aplica — matarlo acá es el "le hablé 5 veces y ni pelota".
            es_wake = self.wake_word in corr.lower()
            if (s.no_speech_prob < self.no_speech_max
                    and (s.avg_logprob > self.logprob_min or es_wake)):
                kept.append(s)
            else:
                # sin este log, un "Harvis" filtrado desaparece sin rastro
                log.debug("descartado (ns=%.2f lp=%.2f): %r",
                          s.no_speech_prob, s.avg_logprob, s.text.strip())
        texto = " ".join(s.text.strip() for s in kept).strip()
        pelado = texto.lower().strip(".!¡¿? ")
        if pelado in self.alucinaciones or pelado in self.muletillas:
            return ""
        for rx, reemplazo in self.correcciones:
            texto = rx.sub(reemplazo, texto)
        # Transcripts de 1-2 palabras: un soplido alcanza para que Whisper
        # invente "y"/"Bien" — solo pasan con confianza ALTA. Excepción: el
        # wake word solo ("¡Harvis!") es el falso negativo que MÁS duele;
        # si lo nombró, alcanza la confianza base de arriba.
        if len(texto.split()) <= 2 and any(
                s.no_speech_prob > self.short_no_speech_max
                or s.avg_logprob < self.short_logprob_min for s in kept):
            if self.wake_word not in texto.lower():
                log.debug("descartado corto (confianza baja): %r", texto)
                return ""
        return texto
