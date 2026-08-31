"""Interruptor manual de 'modo local forzado' — para cuando el usuario quiere
que Rochy use la IA local a propósito (ahorrar tokens de Groq) aunque SÍ haya
internet, sin tener que desconectar el wifi de verdad para lograrlo.

Vive solo mientras la app esté abierta (no se guarda entre reinicios), igual
que el resto del estado de la conversación."""

_forced_local = False


def is_forced_local() -> bool:
    return _forced_local


def set_forced_local(value: bool) -> None:
    global _forced_local
    _forced_local = value


# Interruptor de "control remoto": cuando está activo, el micrófono de la PC
# deja de escuchar la palabra clave todo el rato (el celular, con su botón de
# mantener presionado, ya es la entrada principal — cada apretón YA es una
# acción explícita, no hace falta detectar nada solo). Se mantiene, eso sí,
# una escucha corta mientras Rochy está hablando, solo para poder cortarla
# (ver _voice_loop en voice_assistant.py) — eso nunca se apaga.
_remote_control = False


def is_remote_control() -> bool:
    return _remote_control


def set_remote_control(value: bool) -> None:
    global _remote_control
    _remote_control = value


# Nivel de "calidad" de las respuestas de la IA en la nube (Groq/Gemini):
# cuánto razona el modelo antes de responder y cuántos tokens se le permite
# usar. "bajo" ahorra costo/tiempo a cambio de respuestas más simples,
# "alto" razona más para tareas que de verdad lo necesitan (a cambio de
# tardar más y gastar más tokens). El modelo local no tiene un parámetro de
# "razonamiento" equivalente, así que solo ajusta cuánto puede escribir.
QUALITY_LEVELS = ("bajo", "medio", "alto")
_quality = "medio"


def get_quality() -> str:
    return _quality


def set_quality(value: str) -> None:
    global _quality
    if value in QUALITY_LEVELS:
        _quality = value
