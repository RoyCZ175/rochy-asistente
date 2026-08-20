"""Respuestas instantáneas para consultas básicas, sin llamar a la IA remota."""

import random
import re
from datetime import datetime

GREETINGS = {"hola", "buenas", "buenos días", "buenas tardes", "buenas noches", "qué tal", "hey"}

IDENTITY_TRIGGERS = ("quién eres", "cómo te llamas", "cual es tu nombre", "cuál es tu nombre")

JOKES = [
    "¿Por qué los programadores prefieren el frío? Porque odian los bugs.",
    "¿Sabes por qué las computadoras nunca se resfrían? Porque tienen Windows.",
    "Un byte le dice a otro: ¿te sientes mal? El otro responde: sí, tengo un bit torcido.",
]

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

_MATH_ALLOWED = re.compile(r"^[\d\s.+\-*/()]+$")


def try_local_answer(text: str, assistant_name: str):
    """Devuelve una respuesta instantánea o None si la consulta necesita a la IA."""
    t = text.lower().strip().strip("¿?")

    if t in GREETINGS or any(t.startswith(g + " ") for g in GREETINGS):
        return f"Hola, soy {assistant_name}. ¿En qué te ayudo?"

    if any(trigger in t for trigger in IDENTITY_TRIGGERS):
        return f"Soy {assistant_name}, tu asistente personal."

    if "qué día es" in t or "que dia es" in t:
        now = datetime.now()
        return f"Hoy es {DIAS[now.weekday()]}, {now.strftime('%d/%m/%Y')}."

    if "chiste" in t or "cuéntame algo gracioso" in t:
        return random.choice(JOKES)

    result = _try_math(t)
    if result is not None:
        return f"El resultado es {result}."

    return None


def _try_math(t: str):
    t = (
        t.replace("más", "+")
        .replace("menos", "-")
        .replace("por", "*")
        .replace("dividido entre", "/")
        .replace("dividido", "/")
    )
    t = re.sub(r"cu[aá]nto\s+es", "", t).strip()

    if not t or len(t) > 40 or "**" in t:
        return None
    if not _MATH_ALLOWED.match(t):
        return None
    if not any(op in t for op in "+-*/"):
        return None

    try:
        return eval(t, {"__builtins__": {}}, {})
    except Exception:
        return None
