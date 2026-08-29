"""Servidor WebSocket local: transmite el estado del asistente (idle/listening/
thinking/speaking) y el transcript de la conversación a la interfaz, y recibe
de vuelta los comandos escritos desde el cuadro de texto de la interfaz (o de
audio grabado desde el celular usado como micrófono remoto, ver remote.html).

HOST está en 0.0.0.0 (todas las interfaces) a propósito, no "localhost" — para
que el celular, en la misma red WiFi, pueda conectarse también. Esto expone el
servidor a quien esté en esa red local (puede mandarle comandos a Rochy, que
controla el PC de verdad) — aceptable en una red doméstica de confianza, pero
vale saberlo: no hay autenticación."""

import asyncio
import base64
import http.server
import json
import os
import queue
import socket
import threading

import websockets

HOST = "0.0.0.0"
PORT = 8765
HTTP_PORT = 8766
INTERFACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "interface")

_loop = None
_clients = set()
_ready = threading.Event()
_text_queue: "queue.Queue[str]" = queue.Queue()
_audio_queue: "queue.Queue[tuple[bytes, str]]" = queue.Queue()


async def _handler(websocket):
    _clients.add(websocket)
    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if data.get("type") == "text_command" and data.get("text", "").strip():
                _text_queue.put(data["text"].strip())
            elif data.get("type") == "audio_command" and data.get("audio"):
                try:
                    audio_bytes = base64.b64decode(data["audio"])
                except (ValueError, TypeError):
                    continue
                mime = data.get("mime", "audio/webm")
                _audio_queue.put((audio_bytes, mime))
    finally:
        _clients.discard(websocket)


async def _main() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    async with websockets.serve(_handler, HOST, PORT):
        _ready.set()
        await asyncio.Future()  # corre para siempre


def start() -> None:
    """Arranca el servidor WebSocket en un hilo de fondo. No bloquea."""
    thread = threading.Thread(target=lambda: asyncio.run(_main()), daemon=True)
    thread.start()
    _ready.wait(timeout=5)


def start_http() -> None:
    """Sirve la carpeta interface/ por HTTP normal (no WebSocket) para que el
    celular pueda abrir remote.html desde su navegador — pywebview solo sirve
    la ventana de escritorio, no es alcanzable desde otro dispositivo."""
    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(
        *args, directory=INTERFACE_DIR, **kwargs
    )
    server = http.server.ThreadingHTTPServer((HOST, HTTP_PORT), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()


def get_lan_ip() -> str:
    """IP de este PC dentro de la red local (la que hay que escribir en el
    navegador del celular) — no manda datos de verdad, solo usa el truco de
    abrir un socket UDP para que el sistema operativo resuelva sola cuál es
    la interfaz de red real (no la de loopback)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def get_text_command(timeout: float = 1.0):
    """Devuelve el próximo comando escrito por el usuario, o None si no llegó ninguno."""
    try:
        return _text_queue.get(timeout=timeout)
    except queue.Empty:
        return None


def get_audio_command(timeout: float = 1.0):
    """Devuelve (audio_bytes, mime) del próximo audio grabado desde el
    micrófono remoto (celular), o None si no llegó ninguno."""
    try:
        return _audio_queue.get(timeout=timeout)
    except queue.Empty:
        return None


def broadcast_state(state: str) -> None:
    _broadcast({"type": "state", "state": state})


def broadcast_transcript(role: str, text: str) -> None:
    _broadcast({"type": "transcript", "role": role, "text": text})


def broadcast_mode(ai_mode: str, study_subject) -> None:
    """Le avisa a la interfaz qué modo de IA está activo (local/online) y qué
    materia de 'modo estudio' está activa (o None si ninguna), para que lo
    muestre en la barra de estado sin que el usuario tenga que preguntarlo."""
    _broadcast({"type": "mode_update", "ai_mode": ai_mode, "study_subject": study_subject})


def broadcast_voice_envelope(envelope: list, step_ms: int) -> None:
    """Manda el volumen real de la voz que está a punto de sonar (ver
    tts.py) para que el orbe pueda crecer/encoger siguiendo los altos y
    bajos de verdad, en vez de una animación genérica de 'hablando'."""
    _broadcast({"type": "voice_envelope", "envelope": envelope, "step_ms": step_ms})


def broadcast_open_file_picker(subject: str) -> None:
    """Le pide a la interfaz que abra el selector nativo de archivos para esa
    materia — la propia interfaz es quien debe llamar a la función expuesta
    (ui_bridge.py) para que pywebview maneje bien el diálogo nativo."""
    _broadcast({"type": "open_file_picker", "subject": subject})


def _broadcast(payload: dict) -> None:
    if _loop is None or not _clients:
        return
    message = json.dumps(payload)
    asyncio.run_coroutine_threadsafe(_send_all(message), _loop)


async def _send_all(message: str) -> None:
    dead = []
    for ws in list(_clients):
        try:
            await ws.send(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _clients.discard(ws)
