import datetime
import os
import re
import sys
import threading
import traceback
import unicodedata

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rochy.log")

# Cuando se corre sin consola (pythonw.exe, para no mostrar ninguna ventana de
# terminal), sys.stdout/stderr son None y cualquier print() haría crashear la
# app. Los mandamos a un archivo de registro real (no a la nada), para poder
# diagnosticar un fallo después en vez de que desaparezca sin dejar rastro.
if sys.stdout is None or sys.stderr is None:
    _log_file = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    sys.stdout = _log_file
    sys.stderr = _log_file
    print(f"\n=== Sesión iniciada {datetime.datetime.now().isoformat(timespec='seconds')} ===")

import connectivity
import control_signal
import local_brain
import system_control as sc
import ui_server

INTERFACE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "interface", "index.html")


def parse_command(text: str):
    t = text.lower().strip()

    if "hora" in t or "tiempo" in t:
        return {"action": "time", "target": None}

    if "bloc de notas" in t or "notepad" in t:
        return {"action": "open_app", "target": "notepad"}

    if "explorador" in t or "file explorer" in t or "explorer" in t:
        return {"action": "open_app", "target": "explorer"}

    return {"action": "chat", "target": None, "text": t}


def build_response(text: str) -> str:
    """Camino rápido local para comandos triviales, sin pasar por la IA."""
    command = parse_command(text)

    if command["action"] == "time":
        return sc.get_time()

    if command["action"] == "open_app":
        return sc.open_app(command["target"])

    return "Puedo ayudarte con tareas y control del sistema, y también seguir una conversación natural."


# Segundos de silencio dentro de una conversación de voz antes de volver a esperar la palabra clave.
CONVERSATION_TIMEOUT = 30

# Frases que cancelan lo que se esté procesando, respondidas al instante (sin
# esperar turno ni gastar tokens de IA) — chequeadas antes de tomar el lock
# compartido, para que un "cancela" nunca se quede esperando detrás de algo
# que está tardando.
CANCEL_PHRASES = {"cancela", "cancelar", "detente", "para", "olvidalo"}


def _is_cancel(text: str) -> bool:
    # "para" se deja como coincidencia EXACTA (no de subcadena/raíz): es una
    # palabra demasiado común en español ("ábrelo para mí") como para
    # detectarla dentro de cualquier frase sin generar falsos positivos.
    normalized = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", _normalize_text(text))
    return normalized in CANCEL_PHRASES


def _normalize_text(text: str) -> str:
    """minúsculas y sin acentos, para no depender de coincidencias exactas
    ('Apágate', 'apagate', 'Apágate, deja de escuchar' deben reconocerse igual)."""
    text = text.strip().lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def _has_word_starting_with(text: str, *roots: str) -> bool:
    words = re.findall(r"[a-z]+", text)
    return any(word.startswith(root) for word in words for root in roots)


def _classify_control_intent(command_text: str) -> str:
    """Detecta frases de control (salir/pausar/reiniciar) tolerando variaciones
    de conjugación, acentos y palabras de más alrededor — no exige una
    coincidencia exacta con una frase fija. Devuelve 'exit', 'end_conversation',
    'reset' o 'none'."""
    text = _normalize_text(command_text)

    if _has_word_starting_with(text, "apag", "desactiv") or "adios" in text or "hasta luego" in text or "salir" in text:
        return "exit"

    if _has_word_starting_with(text, "descans") or "gracias" in text or "eso es todo" in text or "nada mas" in text:
        return "end_conversation"

    if (
        ("olvida" in text and ("todo" in text or "conversacion" in text))
        or ("reinicia" in text and "conversacion" in text)
        or "empecemos de nuevo" in text
        or ("borra" in text and "conversacion" in text)
    ):
        return "reset"

    return "none"


def _handle_command(command_text: str, config, brain, local_brain_ai, voice) -> str:
    """Procesa un comando (venga de voz o de texto) y devuelve 'exit',
    'end_conversation' o 'handled'. Compartido por ambos canales de entrada."""
    print(f"Tú: {command_text}")
    ui_server.broadcast_transcript("user", command_text)
    intent = _classify_control_intent(command_text)

    if intent == "exit":
        farewell = "Hasta luego."
        voice.speak(farewell)
        ui_server.broadcast_transcript("assistant", farewell)
        return "exit"

    if intent == "end_conversation":
        reply = "De acuerdo, aquí estaré si me necesitas."
        voice.speak(reply)
        ui_server.broadcast_transcript("assistant", reply)
        return "end_conversation"

    if intent == "reset":
        # vía de escape si el modelo se queda "atascado" (ej. sigue negándose a
        # cosas normales tras rechazar un pedido anterior) — sin cerrar la app.
        brain.reset()
        if local_brain_ai is not None:
            local_brain_ai.reset()
        reply = "Listo, empezamos de cero."
        voice.speak(reply)
        ui_server.broadcast_transcript("assistant", reply)
        return "handled"

    ui_server.broadcast_state("thinking")
    quick = parse_command(command_text)
    if quick["action"] in {"time", "open_app"}:
        response = build_response(command_text)
    else:
        response = local_brain.try_local_answer(command_text, config.assistant_name)
        if response is None:
            if connectivity.is_online():
                try:
                    response = brain.ask(command_text)
                except Exception as exc:
                    # Groq puede fallar aunque haya internet (cupo agotado, caída del
                    # servicio, etc.) — si hay IA local, la usamos en vez de solo fallar.
                    if local_brain_ai is not None:
                        print(f"[aviso] Groq falló ({exc}), uso la IA local de respaldo.")
                        response = local_brain_ai.ask(command_text)
                    else:
                        raise
            elif local_brain_ai is not None:
                response = local_brain_ai.ask(command_text)
            else:
                response = (
                    "No tengo internet ni un modelo de IA local instalado ahora mismo. "
                    "Solo puedo ayudarte con comandos básicos por ahora."
                )

    print(f"{config.assistant_name}: {response}")
    ui_server.broadcast_transcript("assistant", response)
    voice.speak(response)

    # Respaldo semántico: si el filtro rápido no detectó nada pero la IA, con
    # el contexto completo, decidió que sí querías pausar/apagar (herramienta
    # end_session), respetamos esa decisión también.
    signal = control_signal.pop()
    if signal == "exit":
        return "exit"
    if signal == "pause":
        return "end_conversation"

    return "handled"


def _report_error(voice, exc: Exception) -> None:
    """Avisa el fallo al usuario (voz + chat) y deja el traceback completo en
    rochy.log — nunca solo por consola: en modo silencioso (pythonw) nadie
    vería un print() y el motivo real del fallo se perdería para siempre."""
    print(f"[error] {exc}")
    traceback.print_exc()
    text = str(exc).lower()
    if "rate_limit" in text or "429" in text or "tokens per day" in text:
        friendly = "Se me acabó el cupo de IA por hoy. Inténtalo de nuevo en unos minutos."
    else:
        friendly = "Tuve un problema procesando eso. ¿Puedes repetirlo?"

    ui_server.broadcast_transcript("assistant", friendly)
    try:
        voice.speak(friendly)
    except Exception:
        pass
    ui_server.broadcast_state("idle")


def _handle_cancel_if_requested(text: str, voice) -> bool:
    """Si el texto es una frase de cancelación, responde al instante (sin tocar
    el lock ni la IA) y devuelve True. No puede interrumpir a la mitad algo que
    ya está en curso, pero garantiza que cancelar nunca se quede esperando
    detrás de algo lento (eso lo cubre el límite de tiempo de las herramientas)."""
    if not _is_cancel(text):
        return False
    print(f"Tú: {text}")
    ui_server.broadcast_transcript("user", text)
    reply = "Listo, cancelado."
    ui_server.broadcast_transcript("assistant", reply)
    try:
        voice.speak(reply)
    except Exception:
        pass
    ui_server.broadcast_state("idle")
    return True


def _voice_loop(
    config, brain, local_brain_ai, voice, listener, lock: threading.Lock, stop_event: threading.Event
) -> None:
    while not stop_event.is_set():
        try:
            ui_server.broadcast_state("idle")
            heard = listener.listen(timeout=5, phrase_time_limit=4)
            if not heard or config.wake_word not in heard.lower():
                continue

            voice.speak("Dime.")

            # Modo conversación: una vez activado, sigue escuchando turno tras
            # turno sin necesitar la palabra clave otra vez, hasta que haya
            # silencio o el usuario indique que terminó.
            while not stop_event.is_set():
                ui_server.broadcast_state("listening")
                command_text = listener.listen(timeout=CONVERSATION_TIMEOUT, phrase_time_limit=15)
                if not command_text:
                    break

                if _handle_cancel_if_requested(command_text, voice):
                    continue

                with lock:
                    status = _handle_command(command_text, config, brain, local_brain_ai, voice)
                if status == "exit":
                    stop_event.set()
                    break
                if status == "end_conversation":
                    break
        except Exception as exc:
            # cualquier fallo puntual (red, TTS, una herramienta) no debe matar
            # el hilo del asistente ni dejar la interfaz congelada — y siempre
            # se le avisa al usuario, nunca falla en silencio.
            _report_error(voice, exc)


def _text_loop(
    config, brain, local_brain_ai, voice, lock: threading.Lock, stop_event: threading.Event
) -> None:
    """Atiende los comandos escritos en la interfaz, en paralelo a la voz.
    Escribir no necesita palabra clave: es una acción explícita del usuario."""
    while not stop_event.is_set():
        text = ui_server.get_text_command(timeout=1.0)
        if text is None:
            continue
        if _handle_cancel_if_requested(text, voice):
            continue
        try:
            with lock:
                status = _handle_command(text, config, brain, local_brain_ai, voice)
            if status == "exit":
                stop_event.set()
        except Exception as exc:
            _report_error(voice, exc)


def _assistant_loop(window) -> None:
    """Arranca ambos canales de entrada (voz y texto) y corre hasta que uno
    de los dos reciba una orden de salir."""
    from config import Config
    from stt import SpeechListener
    from tts import VoiceOutput
    from ai_brain import AIBrain

    try:
        config = Config.load()
    except RuntimeError as exc:
        print(f"\n{exc}\n")
        return

    listener = SpeechListener(config)
    voice = VoiceOutput(config.edge_tts_voice)
    brain = AIBrain(config)

    local_brain_ai = None
    try:
        import local_ai_brain

        if local_ai_brain.is_available(config.ollama_model):
            local_brain_ai = local_ai_brain.LocalAIBrain(config, config.ollama_model)
            print(f"IA local ({config.ollama_model}, vía Ollama) disponible como respaldo sin internet.")
        else:
            print("IA local no disponible (Ollama no está corriendo o falta el modelo).")
    except Exception as exc:
        print(f"No se pudo preparar la IA local: {exc}")

    print(f"{config.assistant_name} está en línea. Di '{config.wake_word}' o escríbele para activarlo.")
    voice.speak(f"{config.assistant_name} en línea. Estoy escuchando.")

    lock = threading.Lock()
    stop_event = threading.Event()

    text_thread = threading.Thread(
        target=_text_loop, args=(config, brain, local_brain_ai, voice, lock, stop_event), daemon=True
    )
    text_thread.start()

    _voice_loop(config, brain, local_brain_ai, voice, listener, lock, stop_event)

    if window is not None:
        window.destroy()

    # Cierre forzado y completo del proceso: aunque algún hilo o recurso
    # (audio, sockets) se quede colgado, esto garantiza que no quede ningún
    # proceso "zombi" corriendo en segundo plano después de cerrar.
    os._exit(0)


def _already_running() -> bool:
    """Comprueba si ya hay otra instancia usando el puerto del asistente,
    para no abrir una segunda ventana "zombi" que compita con la primera."""
    import socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((ui_server.HOST, ui_server.PORT))
        return False
    except OSError:
        return True
    finally:
        probe.close()


def run() -> None:
    """Punto de entrada de la app: abre la ventana compacta tipo widget con
    la interfaz, y arranca el asistente (voz + texto) en segundo plano."""
    import webview
    from dotenv import load_dotenv

    load_dotenv()
    assistant_name = os.getenv("ASSISTANT_NAME", "Rochy")

    if _already_running():
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0,
                f"{assistant_name} ya está abierto en otra ventana. Ciérrala antes de abrir una nueva.",
                assistant_name,
                0x40,  # ícono de información
            )
        except Exception:
            print(f"{assistant_name} ya está abierto en otra ventana.")
        return

    ui_server.start()
    window = webview.create_window(
        assistant_name,
        INTERFACE_PATH,
        width=380,
        height=620,
        background_color="#05070d",
        on_top=True,
    )
    webview.start(_assistant_loop, window)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nApagando asistente.")
        sys.exit(0)
