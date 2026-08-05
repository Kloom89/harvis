"""Modo charla: entrada, salidas y que no se dispare con la charla real
del corpus (kloom.log de la llamada telefónica)."""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from kloom import ENTER_CHAT_RE, EXIT_CHAT_RE, sin_tildes

ENTRAR = ["modo charla", "modo conversación", "entrá en modo charla",
          "modo chat", "hablemos", "charlemos un rato", "conversemos"]
NO_ENTRAR = ["qué hora es", "abrí spotify", "poné música",
             "contame de qué se trata la charla de mañana"]
SALIR = ["listo", "basta", "chau", "cortala", "terminamos", "gracias jarvis",
         "gracias harvis", "modo normal", "salí del modo charla",
         "cortá la charla", "bueno listo, gracias"]
# "dejá de escuchar" ya NO corta la charla: activa modo privacidad (más
# fuerte — apaga el mic del todo). Lo verifica el PRIVACY_RE:
from kloom import PRIVACY_RE
assert PRIVACY_RE.search(sin_tildes("dejá de escuchar"))
NO_SALIR = ["contame un chiste", "qué hora es", "cómo viene tucora",
            "poneme un timer de diez minutos", "abrí el bloc de notas"]

mal = 0
for t in ENTRAR:
    if not ENTER_CHAT_RE.search(sin_tildes(t)):
        print(f"  FALLA entrada: {t!r} no activa"); mal += 1
for t in NO_ENTRAR:
    if ENTER_CHAT_RE.search(sin_tildes(t)):
        print(f"  FALLA entrada: {t!r} activa de más"); mal += 1
for t in SALIR:
    if not EXIT_CHAT_RE.search(sin_tildes(t)):
        print(f"  FALLA salida: {t!r} no corta"); mal += 1
for t in NO_SALIR:
    if EXIT_CHAT_RE.search(sin_tildes(t)):
        print(f"  FALLA salida: {t!r} corta de más"); mal += 1

# El corpus real: nada de la llamada telefónica debe ENTRAR en modo charla.
corpus = [l.strip() for l in open("corpus_oido.txt", encoding="utf-8")
          if l.strip()]
entradas_espurias = [c for c in corpus if ENTER_CHAT_RE.search(sin_tildes(c))]
if entradas_espurias:
    print("  FALLA: el corpus real activa modo charla:", entradas_espurias)
    mal += len(entradas_espurias)

# Cuántas frases del corpus lo CORTARÍAN (bueno que sean muchas: en modo
# charla, la charla ajena lo saca solo en vez de seguir mandando todo al LLM).
cortes = [c for c in corpus if EXIT_CHAT_RE.search(sin_tildes(c))]
print(f"frases del corpus que cortarían el modo charla: "
      f"{len(cortes)}/{len(corpus)} (cuantas más, más rápido se autocorta)")

assert mal == 0, f"{mal} fallas"
print("test_chat_mode OK ✓")
