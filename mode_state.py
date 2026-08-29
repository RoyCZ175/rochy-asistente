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
