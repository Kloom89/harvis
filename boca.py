"""Edge TTS → mp3 en memoria → pygame. Beeps de feedback con winsound.
Habla por oraciones en pipeline: suena la primera mientras se sintetiza la
siguiente — la latencia percibida es la de UNA oración, no todo el texto."""
import asyncio
import io
import logging
import re
import winsound

import edge_tts
import pygame

log = logging.getLogger("kloom.boca")

_FRASES = re.compile(r"(?<=[.!?…:]) +")


def beep_wake():
    winsound.Beep(880, 90)


def beep_ok():
    winsound.Beep(660, 70)


def beep_error():
    winsound.Beep(220, 250)


def beep_listening():
    """Post-respuesta: la ventana de follow-up está abierta, se puede
    repreguntar sin wake word."""
    winsound.Beep(1320, 60)


class Boca:
    def __init__(self, cfg: dict):
        tcfg = cfg.get("tts") or {}
        self.enabled = tcfg.get("enabled", True)
        self.voice = tcfg.get("voice", "es-AR-TomasNeural")
        self.abortar = False
        pygame.mixer.init()

    def stop(self):
        """Corta la voz YA (el 'cortala' del usuario)."""
        self.abortar = True
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

    async def _synth(self, text: str) -> io.BytesIO | None:
        buf = io.BytesIO()
        try:
            async for chunk in edge_tts.Communicate(text, self.voice).stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
        except Exception as e:
            log.warning("TTS falló: %s", e)
            return None
        buf.seek(0)
        return buf

    async def _play(self, buf: io.BytesIO):
        pygame.mixer.music.load(buf, "mp3")
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy() and not self.abortar:
            await asyncio.sleep(0.05)

    async def say(self, text: str):
        if not self.enabled or not text.strip():
            return
        self.abortar = False
        frases = [f for f in _FRASES.split(text.strip()) if f.strip()]
        siguiente = asyncio.create_task(self._synth(frases[0]))
        for i in range(len(frases)):
            buf = await siguiente
            if self.abortar:
                break
            if i + 1 < len(frases):
                siguiente = asyncio.create_task(self._synth(frases[i + 1]))
            if buf:
                await self._play(buf)

    async def say_stream(self, frases):
        """Pipeline continuo sobre un stream de oraciones (async gen):
        sintetiza por adelantado mientras suena la actual — sin el silencio
        de ~1 s entre oración y oración que hace creer que ya terminó."""
        if not self.enabled:
            async for _ in frases:
                pass
            return
        self.abortar = False
        cola: asyncio.Queue = asyncio.Queue(maxsize=3)

        async def sintetizador():
            try:
                async for fr in frases:
                    if fr.strip():
                        await cola.put(await self._synth(fr.strip()))
            finally:
                await cola.put(None)

        tarea = asyncio.create_task(sintetizador())
        try:
            while True:
                buf = await cola.get()
                if buf is None or self.abortar:
                    break
                await self._play(buf)
        finally:
            tarea.cancel()
