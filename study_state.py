"""Materia activa en 'modo estudio' — cuando hay una, cada pregunta busca
primero los fragmentos más relevantes de sus apuntes indexados (study_rag.py)
y se los pasa como contexto real a la IA antes de responder.

Vive solo mientras la app esté abierta, igual que el resto del estado de la
conversación (mode_state.py, control_signal.py)."""

_active_subject = None


def get_subject():
    return _active_subject


def set_subject(subject) -> None:
    global _active_subject
    _active_subject = subject
