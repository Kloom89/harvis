"""Laboratorio del wake word: mide recall/falsos+ de cada candidato contra el
corpus REAL de kloom.log (charla telefónica ajena + música = negativos; los
intentos del usuario = positivos). Correr tras cada sesión fallida:

  python wake_lab.py          # compara candidatos
  python wake_lab.py --barrido  # busca el umbral óptimo del fuzzy
"""
import difflib
import os
import re
import sys
import unicodedata

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Lo que Whisper escribió CADA vez que el usuario dijo "Jarvis" (logs 2026-08-03).
POSITIVOS = [
    "Javi, ¿qué hora es?",
    "Harvey, ¿estás ahí?",
    "JARVIS",
    "harris",
    "Hola Harvís, ¿podés abrir la calculadora?",
    "Jervis, ¿estás ahí?",
    "¿Estás ahí, Hergis?",
    "Carguis",
    "Harley, ¿estás ahí?",
    "Javier, ¿estás ahí?",
    "te digo Harviss",
    # voz sintética (test_kloom):
    "Jarvis, abrí el navegador.",
    "charbis, ¿qué hora es?",
    "Sharvis abrí spotify",
    "Chervis, pausá la música",
    "Jarvis.",
]

_PALABRAS_POS = {"javi", "harvey", "jarvis", "harris", "harvis", "jervis",
                 "hergis", "carguis", "charbis", "sharvis", "chervis"}

# corpus_oido.txt = frases reales oídas por TU mic (se extrae de kloom.log,
# líneas "oído:"); es personal y no viene en el repo — sin él, el lab corre
# solo con los negativos de ejemplo.
NEGATIVOS = []
if os.path.exists("corpus_oido.txt"):
    NEGATIVOS = [l.rstrip("\n") for l in
                 open("corpus_oido.txt", encoding="utf-8") if l.strip()]
NEGATIVOS = [n for n in NEGATIVOS if n not in POSITIVOS]
NEGATIVOS += ["¿Habéis comprado un quistadillo en un estante de supermercado?",
              "¿Sabéis lo que pasó ayer?", "vosotros tenéis razón"]
NEGATIVOS += ["El servicio anda mal hoy.", "Me servís un mate?",
              "Me tomé un jarabe.", "Hola, ¿cómo andás?",
              "Dale, gracias por todo.", "Che, vení un segundo."]


def sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn")


RE_ACTUAL = re.compile(
    r"\b(?!ser)(?:[jhgyx]|ch|sh|ll)[aeo](?:r{1,2}|l)?[vbpfwl]?(?:i[sz]{0,2}|ey|ier)\b")


def por_regex(text):
    return RE_ACTUAL.search(sin_tildes(text))


class Fuzzy:
    """Compara cada palabra candidata contra 'jarvis' por similitud. Whisper
    inventa una grafía distinta cada vez (javi/hergis/carguis); un regex
    artesanal es un juego de whack-a-mole, la distancia no."""

    def __init__(self, umbral):
        self.umbral = umbral

    def __call__(self, text):
        for m in re.finditer(r"[a-z]{4,9}", sin_tildes(text)):
            w = m.group()
            if w.startswith("ser") or w.endswith(("eis", "ais")):
                continue
            r = difflib.SequenceMatcher(None, w, "harvis").ratio()
            if r >= self.umbral:
                return m
        return None


def mixto(umbral):
    fz = Fuzzy(umbral)
    return lambda t: por_regex(t) or fz(t)


class Adaptativo:
    """Umbral según largo: llamarlo es una frase corta ("Carguis",
    "Harley, ¿estás ahí?",
    "Javier, ¿estás ahí?",
    "te digo Harviss", "¿estás
    ahí, Hergis?"); la charla ajena que se le parece es larga ("me tomé un
    jarabe", "en cajas de cristal"). Permisivo con lo corto, estricto con
    lo largo."""

    def __init__(self, corto=0.50, largo=0.58, max_palabras=3):
        self.corto, self.largo, self.max_palabras = corto, largo, max_palabras

    def __call__(self, text):
        if m := por_regex(text):
            return m
        u = self.corto if len(text.split()) <= self.max_palabras else self.largo
        return Fuzzy(u)(text)


def evaluar(nombre, fn, prefix_chars=18, verboso=True):
    tp = [p for p in POSITIVOS if (m := fn(p)) and m.start() < prefix_chars]
    fp = [n for n in NEGATIVOS if (m := fn(n)) and m.start() < prefix_chars]
    if verboso:
        print(f"\n=== {nombre} ===")
        print(f"recall  {len(tp)}/{len(POSITIVOS)} = {len(tp)/len(POSITIVOS):.0%}"
              f"   falsos+ {len(fp)}/{len(NEGATIVOS)}")
        if perdidos := [p for p in POSITIVOS if p not in tp]:
            print("  NO detectó:", perdidos)
        if fp:
            print("  activó de más:", [f[:55] for f in fp])
    return len(tp), len(fp)


if __name__ != "__main__":
    pass          # importado por test_wake: solo se usan los corpus
elif "--barrido" in sys.argv:
    print("umbral  recall  falsos+   (fuzzy solo / mixto con regex)")
    for u in [x / 100 for x in range(45, 86, 5)]:
        tf, ff = evaluar(f"f{u}", Fuzzy(u), verboso=False)
        tm, fm = evaluar(f"m{u}", mixto(u), verboso=False)
        print(f"{u:.2f}    {tf:2}/{len(POSITIVOS)}    {ff:2}"
              f"        {tm:2}/{len(POSITIVOS)}    {fm:2}")
else:
    evaluar("regex actual", por_regex)
    evaluar("fuzzy 0.60", Fuzzy(0.60))
    evaluar("mixto 0.60", mixto(0.60))
