"""Reconocimiento de voz local con Vosk — funciona sin internet.

Usa un modelo más liviano que Whisper: bueno para comandos cortos y frases
claras, menos preciso que la versión en la nube para conversación larga o
con mucho ruido de fondo.
"""

import json
import os

from vosk import KaldiRecognizer, Model

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vosk_model_es")
SAMPLE_RATE = 16000

_model = None


def available() -> bool:
    return os.path.isdir(MODEL_PATH)


def _get_model() -> Model:
    global _model
    if _model is None:
        if not available():
            raise RuntimeError(
                "Falta el modelo de voz local (carpeta vosk_model_es/). Descárgalo de "
                "https://alphacephei.com/vosk/models"
            )
        _model = Model(MODEL_PATH)
    return _model


def transcribe(audio) -> str:
    """audio es un speech_recognition.AudioData ya capturado del micrófono."""
    raw = audio.get_raw_data(convert_rate=SAMPLE_RATE, convert_width=2)
    recognizer = KaldiRecognizer(_get_model(), SAMPLE_RATE)
    recognizer.AcceptWaveform(raw)
    result = json.loads(recognizer.FinalResult())
    return (result.get("text") or "").strip()
