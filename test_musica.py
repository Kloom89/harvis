"""Unit del MODO MÚSICA: comandos disparan, letras de canciones NO."""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from kloom import MUSICA_CEREBRO_RE, MUSICA_DIRECTAS, sin_tildes


def clasificar(frase: str):
    st = sin_tildes(frase.lower()).strip(".!?¿¡, ")
    d = next((a for rx, a in MUSICA_DIRECTAS if rx.search(st)), None)
    if d:
        return d
    if MUSICA_CEREBRO_RE.search(st):
        return "cerebro"
    return None


COMANDOS = [
    ("pausala", "pause"), ("pausá la música", "pause"), ("pausa", "pause"),
    ("pará", "pause"), ("para la música", "pause"), ("detené", "pause"),
    ("dale play", "play"), ("play", "play"), ("seguí", "play"),
    ("reanudá", "play"),
    ("siguiente", "next"), ("otra", "next"), ("otra canción", "next"),
    ("saltala", "next"), ("próxima", "next"), ("pasa de tema", "next"),
    ("pasá de tema", "next"), ("cambiá de tema", "next"),
    ("cambia de canción", "next"), ("el que sigue", "next"),
    ("anterior", "previous"),
    ("subí el volumen", "volume_up"), ("más fuerte", "volume_up"),
    ("subile", "volume_up"), ("más volumen", "volume_up"),
    ("bajá el volumen", "volume_down"), ("más bajo", "volume_down"),
    ("bajale", "volume_down"), ("menos volumen", "volume_down"),
    ("poné mi playlist cumbia", "cerebro"),
    ("puedes poner Versuit", "cerebro"),
    ("podés poner bersuit vergarabat", "cerebro"),
    ("me podés cambiar la música", "cerebro"),
    ("cambiá a la playlist goodvibes", "cerebro"),
    ("poneme el tema de soda stereo", "cerebro"),
    ("reproducí play it", "cerebro"),
]

LETRAS = [
    "Bienvenidos a El Tico de la Vida",
    "para siempre te voy a amar",
    "otra vez me dejaste sola",
    "y todo cambia en esta vida",
    "se pone triste cuando llueve",
    "play that funky music",
    "no me dejes así",
    "el amor para mí ya no existe",
    "sube y baja como el mar",
    "vamos a bailar toda la noche",
    "gracias por venir",
    "dame una señal",
    "me pone triste tu mirada",
    "puedes ver que ya no estoy",
    "pasa el tiempo y no te olvido",
]

fallas = 0
for frase, esperado in COMANDOS:
    got = clasificar(frase)
    if got != esperado:
        print(f"  MISS comando: {frase!r} → {got} (esperaba {esperado})")
        fallas += 1

for letra in LETRAS:
    got = clasificar(letra)
    if got is not None:
        print(f"  FALSO POSITIVO letra: {letra!r} → {got}")
        fallas += 1

assert fallas == 0, f"{fallas} fallas"
print("test_musica OK ✓")
