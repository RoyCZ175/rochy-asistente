"""Señal compartida para que la IA pueda pedir pausar/apagar el asistente
por su propio criterio semántico — respaldo para cuando el reconocimiento
rápido de frases (voice_assistant._classify_control_intent) no detecta nada.

Solo un comando se procesa a la vez (protegido por el lock en
voice_assistant.py), así que una variable simple a nivel de módulo alcanza,
sin necesitar nada más elaborado."""

_signal = None


def request(mode: str) -> None:
    global _signal
    _signal = mode


def pop() -> str:
    global _signal
    value = _signal
    _signal = None
    return value
