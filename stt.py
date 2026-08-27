"""Captura de audio del micrófono y transcripción de voz a texto.

Usa Groq Whisper (nube, mejor calidad) cuando hay internet, y cae
automáticamente a Vosk (local, funciona sin internet) cuando no."""

import io

import speech_recognition as sr
import webrtcvad
from groq import Groq

import connectivity
import local_stt

# Frecuencia y duración de cuadro que exige WebRTC VAD (solo acepta 8000,
# 16000, 32000 o 48000 Hz, y cuadros de 10, 20 o 30ms exactos).
VAD_SAMPLE_RATE = 16000
VAD_FRAME_MS = 30
# Modo de "agresividad" de 0 (más permisivo) a 3 (más estricto) — 2 es un
# punto medio razonable: filtra ruido claro sin descartar voz de verdad.
VAD_AGGRESSIVENESS = 2
# Qué fracción de los cuadros de un audio ya capturado tiene que sonar a voz
# humana para no descartarlo como ruido.
VAD_MIN_SPEECH_RATIO = 0.3


def _contains_speech(audio: sr.AudioData, vad: webrtcvad.Vad) -> bool:
    """Segunda opinión sobre lo que el micrófono ya capturó: speech_recognition
    decide "hay una frase aquí" solo por volumen (energía) — esto reconoce el
    patrón de la voz humana de verdad (formantes/espectro), así que rechaza
    mejor un ruido fuerte (golpe, estática) que cruzó el umbral de volumen
    pero no es voz de nadie. No distingue DE QUIÉN es la voz (eso lo sigue
    haciendo la palabra clave) — solo si lo grabado suena a voz humana o no."""
    raw = audio.get_raw_data(convert_rate=VAD_SAMPLE_RATE, convert_width=2)
    frame_bytes = int(VAD_SAMPLE_RATE * VAD_FRAME_MS / 1000) * 2  # 16-bit = 2 bytes/muestra
    total = 0
    speech = 0
    for i in range(0, len(raw) - frame_bytes + 1, frame_bytes):
        frame = raw[i : i + frame_bytes]
        total += 1
        if vad.is_speech(frame, VAD_SAMPLE_RATE):
            speech += 1
    if total == 0:
        return True  # muy corto para evaluar — no se descarta por las dudas
    return (speech / total) >= VAD_MIN_SPEECH_RATIO


class SpeechListener:
    def __init__(self, config):
        self.recognizer = sr.Recognizer()
        self.recognizer.pause_threshold = 1.2
        self.microphone = sr.Microphone()
        self.client = Groq(api_key=config.groq_api_key)
        self.model = config.whisper_model
        self.language = config.voice_language.split("-")[0]

        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)
        # Por defecto, el umbral de sensibilidad se sigue reajustando solo
        # con cada escucha (dynamic_energy_threshold) — si en algún momento
        # capta un ruido fuerte de fondo (TV, golpe, incluso su propia voz),
        # ese umbral puede dispararse hacia arriba y quedarse ahí, cada vez
        # pidiendo más volumen para activarse hasta terminar ignorando todo,
        # ni a gritos. Se fija el umbral calibrado arriba y no se vuelve a
        # tocar solo: mucho más predecible que dejarlo "flotando".
        self.recognizer.dynamic_energy_threshold = False
        self.vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)

    def listen(self, timeout: float = 5, phrase_time_limit: float = 6) -> str:
        with self.microphone as source:
            try:
                audio = self.recognizer.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_time_limit
                )
            except sr.WaitTimeoutError:
                return ""
        if not _contains_speech(audio, self.vad):
            # Cruzó el umbral de volumen (por eso speech_recognition lo
            # capturó), pero no suena a voz humana — un golpe, estática, un
            # ruido fuerte cualquiera. Se descarta sin ni siquiera gastar una
            # llamada de transcripción (nube o local) en algo que ya sabemos
            # que no es una frase real. Se deja registrado (no en silencio
            # total) para poder notar si este filtro resulta demasiado
            # estricto y empieza a descartar voz real por error.
            print("[info] Audio descartado por el VAD (no parece voz humana)")
            return ""
        return self._transcribe(audio)

    def _transcribe(self, audio: sr.AudioData) -> str:
        if connectivity.is_online():
            text = self._transcribe_cloud(audio)
            if text:
                return text
        if local_stt.available():
            try:
                return local_stt.transcribe(audio)
            except Exception:
                return ""
        return ""

    def _transcribe_cloud(self, audio: sr.AudioData) -> str:
        buffer = io.BytesIO(audio.get_wav_data())
        buffer.name = "audio.wav"
        try:
            result = self.client.audio.transcriptions.create(
                file=buffer,
                model=self.model,
                language=self.language,
            )
        except Exception:
            return ""
        return (result.text or "").strip()
