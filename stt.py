"""Captura de audio del micrófono y transcripción de voz a texto.

Usa Groq Whisper (nube, mejor calidad) cuando hay internet, y cae
automáticamente a Vosk (local, funciona sin internet) cuando no."""

import io

import speech_recognition as sr
from groq import Groq

import connectivity
import local_stt


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

    def listen(self, timeout: float = 5, phrase_time_limit: float = 6) -> str:
        with self.microphone as source:
            try:
                audio = self.recognizer.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_time_limit
                )
            except sr.WaitTimeoutError:
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
