"""Sirve por HTTP simple (sin TLS, nunca sale de 127.0.0.1) la carpeta de la
interfaz nueva — UI-ROCHY, un proyecto/carpeta completamente aparte — para
que pywebview pueda cargarla.

Hace falta un servidor de verdad y no simplemente abrir el archivo porque
sus scripts son módulos de JavaScript (`<script type="module">`), y los
motores de navegador (incluido el que usa pywebview) se niegan a cargar
módulos sobre file:// — se comprobó de verdad (error de CORS en consola).
No hace falta TLS acá: a diferencia del micrófono remoto del celular (que sí
lo necesita para getUserMedia), esto nunca sale de la propia PC."""

import functools
import http.server
import os
import threading

HOST = "127.0.0.1"
PORT = 5173

# Ruta a la otra carpeta/proyecto — UI-ROCHY es su propio proyecto a
# propósito (sin depender de este); esto solo sabe DÓNDE está para poder
# servirlo, no comparte código con él. Se arma con el usuario de Windows
# ACTUAL (no "roger" fijo) para que funcione igual en la PC de un
# colaborador, siempre que también tenga la carpeta en su propio Documents.
UI_ROCHY_DIR = os.path.join(os.path.expanduser("~"), "Documents", "UI-ROCHY")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # SimpleHTTPRequestHandler por defecto imprime una línea por cada
        # archivo pedido (index.html, style.css, app.js, cada frame de la
        # cámara de gestos...) — eso llenaría rochy.log de ruido sin aportar
        # nada que ui_server.py no registre ya a su manera.
        pass


def start() -> str | None:
    """Arranca el servidor en un hilo de fondo si UI-ROCHY existe de verdad
    en esta PC. Devuelve la URL de su index.html, o None si no está (o si el
    puerto ya está en uso) — así quien la llame puede caer de vuelta a la
    interfaz vieja sin que la app deje de abrir por esto."""
    if not os.path.isfile(os.path.join(UI_ROCHY_DIR, "index.html")):
        return None

    handler = functools.partial(_QuietHandler, directory=UI_ROCHY_DIR)
    try:
        server = http.server.ThreadingHTTPServer((HOST, PORT), handler)
    except OSError:
        return None

    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://{HOST}:{PORT}/index.html"
