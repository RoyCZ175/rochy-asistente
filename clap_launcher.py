"""Escucha el micrófono todo el tiempo buscando un patrón de DOS aplausos
seguidos para abrir Rochy solo, sin doble clic. Corre aparte de Rochy a
propósito — tiene que poder abrirlo, así que no puede depender de que ya
esté corriendo. Pensado para arrancar junto con Windows (ver
iniciar_clap_launcher.vbs) y quedarse escuchando todo el tiempo, incluso
con Rochy cerrado — no graba ni manda nada a ningún lado, solo mide picos
de volumen en memoria.

No usa reconocimiento de voz (sería carísimo para esto) — un aplauso es un
pico de volumen muy corto y fuerte comparado con ruido normal de fondo, así
que basta con medir el volumen (RMS) de cada bloque de audio."""

import os
import socket
import subprocess
import time

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
BLOCK_MS = 20
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_MS / 1000)

# Qué tan fuerte tiene que ser un pico para contar como aplauso (RMS del
# bloque, en escala 0..1). CALIBRADO EN VIVO con Roger: su ruido de fondo
# mide ~0.004-0.01, y sus aplausos reales dieron entre 0.08 y 0.21 — 0.2
# (el valor original, adivinado sin probar) se perdía casi todos. 0.06 deja
# margen de sobra arriba del ruido y por debajo del aplauso más flojo real.
CLAP_RMS_THRESHOLD = 0.06
# Tiempo mínimo entre picos para no contar un solo sonido sostenido (una
# puerta, un golpe) como dos aplausos.
REFRACTORY_SECONDS = 0.15
# Ventana máxima entre el primer y el segundo aplauso para contar como
# "doble aplauso". Subido de 0.8 a 1.0s tras ver en vivo que aplausos
# reales seguidos a veces caen justo por encima de 0.8s.
DOUBLE_CLAP_WINDOW_SECONDS = 1.0

# Prende esto para ver el volumen real de cada bloque mientras se prueba —
# útil para calibrar CLAP_RMS_THRESHOLD con aplausos de verdad antes de
# dejarlo corriendo en modo normal.
DEBUG_PRINT_RMS = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LAUNCHER_VBS = os.path.join(BASE_DIR, "run_rochy_silent.vbs")
ROCHY_PORT = 8765


class ClapDetector:
    """Estado puro del detector, separado de sounddevice a propósito para
    poder probarlo con números inventados (ver tests/test_clap_launcher.py)
    sin necesitar un micrófono ni aplaudir de verdad."""

    def __init__(self, threshold=CLAP_RMS_THRESHOLD, refractory=REFRACTORY_SECONDS, window=DOUBLE_CLAP_WINDOW_SECONDS):
        self.threshold = threshold
        self.refractory = refractory
        self.window = window
        self._last_clap_at = 0.0
        self._quiet_since_last = True

    def process(self, rms: float, now: float) -> bool:
        """Le pasa un bloque más (su volumen RMS y el timestamp). Devuelve
        True justo cuando ese bloque completa un doble aplauso."""
        if rms < self.threshold:
            self._quiet_since_last = True
            return False

        if not self._quiet_since_last or (now - self._last_clap_at) < self.refractory:
            return False
        self._quiet_since_last = False

        if self._last_clap_at and (now - self._last_clap_at) <= self.window:
            self._last_clap_at = 0.0
            return True

        self._last_clap_at = now
        return False


def _rochy_running() -> bool:
    """Mismo chequeo que ya usa voice_assistant._already_running(): si se
    puede tomar el puerto, Rochy no está corriendo."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("0.0.0.0", ROCHY_PORT))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def _launch_rochy() -> None:
    print("[clap] doble aplauso detectado, abriendo Rochy...")
    subprocess.Popen(["cscript", "//nologo", LAUNCHER_VBS], cwd=BASE_DIR)


def main():
    print("[clap] escuchando aplausos dobles (Ctrl+C para salir)...")
    detector = ClapDetector()

    def callback(indata, _frames, _time_info, _status):
        rms = float(np.sqrt(np.mean(indata.astype(np.float64) ** 2)))
        if DEBUG_PRINT_RMS and rms > 0.02:
            print(f"[clap] rms={rms:.3f}")
        if detector.process(rms, time.time()):
            if _rochy_running():
                print("[clap] doble aplauso detectado, pero Rochy ya está abierto.")
            else:
                _launch_rochy()

    with sd.InputStream(
        channels=1, samplerate=SAMPLE_RATE, blocksize=BLOCK_SIZE, dtype="float32", callback=callback
    ):
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
