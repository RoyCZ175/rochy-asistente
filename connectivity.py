"""Detección de conexión a internet, para elegir entre los servicios en la
nube (mejor calidad: Groq, Edge TTS) o las alternativas locales (funcionan
sin internet: Vosk, pyttsx3, Ollama) sin tener que esperar un timeout largo
en cada interacción."""

import socket
import time

_HOST = "8.8.8.8"
_PORT = 53
_TIMEOUT = 1.0
_CACHE_SECONDS = 15

_cached_result = None
_cached_at = 0.0


def is_online() -> bool:
    global _cached_result, _cached_at
    now = time.time()
    if _cached_result is not None and (now - _cached_at) < _CACHE_SECONDS:
        return _cached_result

    try:
        socket.create_connection((_HOST, _PORT), timeout=_TIMEOUT).close()
        _cached_result = True
    except OSError:
        _cached_result = False
    _cached_at = now
    return _cached_result
