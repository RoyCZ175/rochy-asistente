"""Pitidos cortos (no voz) para marcar cuándo el micrófono realmente empieza
o deja de escuchar — útil si no estás mirando la pantalla para saber el
momento exacto en que puedes hablar, en vez de adivinarlo.

Usa winsound (viene incluido con Python en Windows, no requiere instalar
nada). Cada pitido dura menos de un décimo de segundo — la pausa que
introduce en el hilo que lo llama es imperceptible."""

import winsound

# Tono agudo y corto: "te escucho, puedes hablar ahora".
_START_FREQ, _START_MS = 880, 90

# Tono grave y corto: "ya capté algo, dejo de escuchar".
_STOP_FREQ, _STOP_MS = 520, 90


def listening_started() -> None:
    try:
        winsound.Beep(_START_FREQ, _START_MS)
    except Exception:
        pass  # nunca debe romper el flujo de voz por un pitido que falló


def listening_stopped() -> None:
    try:
        winsound.Beep(_STOP_FREQ, _STOP_MS)
    except Exception:
        pass
