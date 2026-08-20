"""Texto a voz: usa las voces neuronales de Microsoft Edge cuando hay
internet, y cae automáticamente a las voces locales de Windows (pyttsx3)
cuando no — más robóticas, pero funcionan sin conexión."""

import asyncio
import os
import tempfile

import edge_tts
import pygame
import pyttsx3

import connectivity
import ui_server


class VoiceOutput:
    def __init__(self, voice: str):
        self.voice = voice
        pygame.mixer.init()
        self._local_engine = None

    def speak(self, text: str) -> None:
        if not text:
            return
        ui_server.broadcast_state("speaking")
        try:
            if connectivity.is_online() and self._speak_cloud(text):
                return
            self._speak_local(text)
        finally:
            ui_server.broadcast_state("idle")

    def _speak_cloud(self, text: str) -> bool:
        path = None
        try:
            path = self._synthesize(text)
            self._play(path)
            return True
        except Exception:
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
        except Exception:
            pass  # sin ninguna voz de salida disponible, pero no debe romper la app

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
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)

    def _cleanup(self, path: str) -> None:
        try:
            pygame.mixer.music.unload()
        except Exception:
            pass
        try:
            os.remove(path)
        except OSError:
            pass  # Windows a veces retiene el archivo un instante tras reproducirlo
