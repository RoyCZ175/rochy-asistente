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
