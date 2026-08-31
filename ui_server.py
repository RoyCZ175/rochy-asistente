"""Servidor WebSocket local: transmite el estado del asistente (idle/listening/
thinking/speaking) y el transcript de la conversación a la interfaz, y recibe
de vuelta los comandos escritos desde el cuadro de texto de la interfaz (o de
audio grabado desde el celular usado como micrófono remoto, ver remote.html).

Todo — la página del celular, sus assets, y la conexión en sí — vive en el
MISMO puerto. Se sirve por HTTPS con un certificado autofirmado (obligatorio:
sin un "contexto seguro" el navegador del celular ni siquiera deja pedir
permiso de micrófono, se comprobó de verdad). Usar un solo puerto para todo
importa por eso mismo: con un certificado autofirmado, el navegador solo dejar
pasar una vez que aceptás su advertencia de seguridad para ESE origen exacto
(host+puerto) — si la página y el WebSocket estuvieran en puertos distintos,
habría que aceptar la advertencia dos veces por separado.

HOST está en 0.0.0.0 (todas las interfaces) a propósito, no "localhost" — para
que el celular, en la misma red WiFi, pueda conectarse también. Esto expone el
servidor a quien esté en esa red local (puede mandarle comandos a Rochy, que
controla el PC de verdad) — aceptable en una red doméstica de confianza, pero
vale saberlo: no hay autenticación."""

import asyncio
import base64
import datetime
import ipaddress
import json
import mimetypes
import os
import queue
import socket
import ssl
import threading

import websockets
from websockets.datastructures import Headers
from websockets.http11 import Response

HOST = "0.0.0.0"
PORT = 8765
# Puerto aparte, con HTTPS (certificado autofirmado), solo para el micrófono
# remoto del celular. NO se puede compartir el puerto 8765 de arriba: ese lo
# usa también la ventana de escritorio con un WebSocket plano (ws://
# localhost), y a un WebSocket no hay forma de "aceptarle" un certificado
# autofirmado como sí se le puede aceptar a una página — hubiera dejado de
# conectar la propia interfaz de escritorio.
REMOTE_PORT = 8767
INTERFACE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "interface")

# Archivos que el celular puede pedir por HTTPS normal antes de conectar el
# WebSocket (la página del "micrófono remoto" y todo lo que necesita).
_STATIC_FILES = {
    "/", "/remote.html", "/manifest.json", "/orb.js", "/remote-sw.js",
    "/icon-192.png", "/icon-512.png",
}

_loop = None
_clients = set()
_ready = threading.Event()
_text_queue: "queue.Queue[str]" = queue.Queue()
_audio_queue: "queue.Queue[tuple[bytes, str]]" = queue.Queue()


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


def _build_self_signed_context(ip: str) -> ssl.SSLContext:
    """Genera un certificado autofirmado nuevo en cada arranque (no hace
    falta que persista entre reinicios) válido para la IP actual de la red
    local — sin esto, el navegador del celular ni siquiera deja pedir
    permiso de micrófono: getUserMedia solo existe en un "contexto seguro"
    (HTTPS), y eso se comprobó de verdad con un http:// plano."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Rochy")])

    try:
        ip_addr = ipaddress.ip_address(ip)
        alt_names = [x509.IPAddress(ip_addr), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    except ValueError:
        alt_names = [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    alt_names.append(x509.DNSName("localhost"))

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .sign(key, hashes.SHA256())
    )

    cert_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".remote_cert")
    os.makedirs(cert_dir, exist_ok=True)
    cert_path = os.path.join(cert_dir, "cert.pem")
    key_path = os.path.join(cert_dir, "key.pem")
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context


def _serve_static(path: str) -> Response:
    if path == "/":
        path = "/remote.html"
    file_path = os.path.join(INTERFACE_DIR, path.lstrip("/"))
    try:
        with open(file_path, "rb") as f:
            body = f.read()
    except OSError:
        return Response(404, "Not Found", Headers(), b"Not found")
    content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    headers = Headers()
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(body))
    return Response(200, "OK", headers, body)


def _process_request(connection, request):
    """Se llama para CADA pedido que llega a este puerto, sea o no un
    WebSocket real — si es un GET normal de archivo (la página del celular,
    el ícono, orb.js), lo servimos aquí mismo; si es un pedido de conexión
    WebSocket de verdad, devolvemos None para que siga su curso normal."""
    if "Upgrade" in request.headers and request.headers["Upgrade"].lower() == "websocket":
        return None
    path = request.path.split("?")[0]
    if path in _STATIC_FILES:
        return _serve_static(path)
    return Response(404, "Not Found", Headers(), b"Not found")


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
            elif data.get("type") == "gesture_event" and data.get("label"):
                # Lo manda el proyecto aparte de control por gestos (carpeta
                # gestos_control, otro microservicio, se conecta acá como un
                # cliente WebSocket más). No es una orden para la IA — solo se
                # reenvía a la interfaz para mostrar qué gesto se detectó.
                print(f"[gesto] {data['label']}")
                _broadcast({"type": "gesture_event", "label": data["label"]})
            elif data.get("type") == "gesture_frame" and data.get("image"):
                # Frame de la cámara de gestos_control, ya en JPEG+base64 y
                # a baja resolución (ver main.py de ese proyecto) — se
                # reenvía tal cual, sin loguearlo (llegan varios por segundo).
                _broadcast({"type": "gesture_frame", "image": data["image"]})
    finally:
        _clients.discard(websocket)


async def _main() -> None:
    global _loop
    _loop = asyncio.get_running_loop()
    ssl_context = _build_self_signed_context(get_lan_ip())
    # Dos servidores en el mismo hilo/loop: el de siempre (plano, para la
    # ventana de escritorio) y uno nuevo con HTTPS (para el celular). Ambos
    # comparten el mismo _handler y el mismo set de _clients, así que
    # transmitir el estado/transcript le llega a los dos por igual.
    async with websockets.serve(_handler, HOST, PORT), websockets.serve(
        _handler, HOST, REMOTE_PORT, ssl=ssl_context, process_request=_process_request
    ):
        _ready.set()
        await asyncio.Future()  # corre para siempre


def start() -> None:
    """Arranca el servidor (WebSocket + HTTPS del micrófono remoto, todo en
    el mismo puerto) en un hilo de fondo. No bloquea."""
    thread = threading.Thread(target=lambda: asyncio.run(_main()), daemon=True)
    thread.start()
    _ready.wait(timeout=5)


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


def broadcast_camera_control(action: str) -> None:
    """Le pide al proyecto de gestos (gestos_control, conectado como cliente
    WebSocket) que oculte o muestre su ventana de cámara local — la detección
    de gestos sigue funcionando igual, esto solo esconde la ventana redundante
    (ya que la interfaz también muestra ese video, ver gesture_frame)."""
    _broadcast({"type": "camera_control", "action": action})


def broadcast_quality(level: str) -> None:
    """Le avisa a la interfaz el nivel de calidad de respuesta actual (ver
    mode_state.get_quality()/set_quality()) — así un selector en la interfaz
    se mantiene sincronizado aunque el cambio haya llegado por voz u otro
    canal, en vez de solo confiar en lo último que el propio usuario clickeó."""
    _broadcast({"type": "quality_update", "level": level})


def broadcast_remote_control(active: bool) -> None:
    """Le avisa a la interfaz si el 'control remoto' (micrófono del celular
    como entrada principal) está activo, para reflejarlo en el botón/card
    correspondiente sin que el usuario tenga que preguntarlo."""
    _broadcast({"type": "remote_control_update", "active": active})


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
