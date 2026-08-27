"""Texto a voz: usa las voces neuronales de Microsoft Edge cuando hay
internet, y cae automáticamente a las voces locales de Windows (pyttsx3)
cuando no — más robóticas, pero funcionan sin conexión."""

import asyncio
import os
import tempfile
import threading

import edge_tts
import numpy as np
import pygame
import pyttsx3

import connectivity
import processing_state as proc
import ui_server

# Cada cuánto tiempo se manda un valor de volumen a la interfaz mientras
# habla — bastante seguido para que se vea fluido, sin ser excesivo.
ENVELOPE_STEP_MS = 60


class VoiceOutput:
    def __init__(self, voice: str):
        self.voice = voice
        pygame.mixer.init()
        self._local_engine = None
        # Un acuse de recibo ("dame un momento") y la respuesta final podrían
        # querer hablar casi al mismo tiempo desde hilos distintos — este
        # lock los serializa (el segundo espera a que el primero termine) en
        # vez de arriesgarse a que se pisen entre sí en pygame.mixer.
        self._lock = threading.Lock()

    def speak(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            ui_server.broadcast_state("speaking")
            # Mientras esto suena por los parlantes, el bucle de voz debe dejar de
            # escuchar — si no, el micrófono puede captar la propia voz de Rochy
            # y procesarla como si fuera una orden nueva (retroalimentación).
            proc.speaking_event.set()
            try:
                if connectivity.is_online() and self._speak_cloud(text):
                    return
                self._speak_local(text)
            finally:
                proc.speaking_event.clear()
                ui_server.broadcast_state("idle")

    def _speak_cloud(self, text: str) -> bool:
        path = None
        try:
            path = self._synthesize(text)
            self._play(path)
            return True
        except Exception as exc:
            print(f"[tts] falló la voz en la nube (Edge TTS): {exc!r}")
            return False
        finally:
            if path:
                self._cleanup(path)

    def _speak_local(self, text: str) -> None:
        try:
            if self._local_engine is None:
                self._local_engine = pyttsx3.init()
                self._select_spanish_voice(self._local_engine)
            self._local_engine.say(text)
            self._local_engine.runAndWait()
        except Exception as exc:
            # no debe romper la app si no hay ninguna voz de salida disponible,
            # pero SÍ debe quedar registrado — antes esto fallaba en silencio total.
            print(f"[tts] falló la voz local (pyttsx3): {exc!r}")

    def _select_spanish_voice(self, engine) -> None:
        try:
            for v in engine.getProperty("voices"):
                name_id = f"{v.name} {v.id}".lower()
                if "spanish" in name_id or "es-" in name_id or "es_" in name_id:
                    engine.setProperty("voice", v.id)
                    return
        except Exception:
            pass

    def _synthesize(self, text: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        asyncio.run(edge_tts.Communicate(text, self.voice).save(path))
        return path

    def _play(self, path: str) -> None:
        envelope = self._compute_envelope(path)
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        # Manda el volumen real de la voz (calculado de antemano) al mismo
        # ritmo en que se reproduce, para que la interfaz pueda hacer que el
        # orbe crezca/encoja siguiendo los altos y bajos de verdad — no una
        # animación genérica de "hablando".
        if envelope:
            ui_server.broadcast_voice_envelope(envelope, ENVELOPE_STEP_MS)
        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)

    def _compute_envelope(self, path: str) -> list:
        """Volumen real del audio (RMS) en ventanitas de ENVELOPE_STEP_MS,
        normalizado de 0 a 1. Se calcula UNA vez antes de reproducir (no en
        vivo) porque es más simple y de sobra suficientemente rápido — un
        audio de varios segundos se analiza en milisegundos."""
        try:
            sound = pygame.mixer.Sound(path)
            raw = sound.get_raw()  # PCM ya decodificado por SDL_mixer
            init = pygame.mixer.get_init()
            if not init:
                return []
            freq, _fmt, channels = init
            samples = np.frombuffer(raw, dtype=np.int16)
            if channels > 1:
                samples = samples.reshape(-1, channels).mean(axis=1)
            step = max(1, int(freq * ENVELOPE_STEP_MS / 1000))
            usable = len(samples) - (len(samples) % step)
            if usable <= 0:
                return []
            windows = samples[:usable].reshape(-1, step).astype(np.float64)
            rms = np.sqrt(np.mean(windows * windows, axis=1))
            peak = float(rms.max()) or 1.0
            return [round(float(v) / peak, 3) for v in rms]
        except Exception as exc:
            print(f"[tts] no pude calcular el volumen del audio: {exc!r}")
            return []

    def _cleanup(self, path: str) -> None:
        try:
            pygame.mixer.music.unload()
        except Exception:
            pass
        try:
            os.remove(path)
        except OSError:
            pass  # Windows a veces retiene el archivo un instante tras reproducirlo
