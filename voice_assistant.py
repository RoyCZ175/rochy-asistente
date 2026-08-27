import datetime
import os
import re
import sys
import threading
import time
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
import mode_state
import processing_state as proc
import study_rag
import study_state
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
# que está tardando (ej. Spotify colgado esperando una respuesta de la red).
CANCEL_PHRASES = {
    "cancela", "cancelar", "detente", "para", "olvidalo",
    "ya no", "ya no lo hagas", "no lo hagas", "mejor olvidalo",
    "cancela eso", "detente ya", "espera",
}


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


# "Apagar"/"desactivar" son verbos genéricos que la gente también usa para
# otras cosas (wifi, volumen, modo oscuro...). Si el texto menciona alguno de
# estos objetivos, la orden NO es sobre apagar/pausar al asistente mismo —
# esto es justo lo que pasó con "desactiva el wifi", que cerraba la app entera
# por error.
OTHER_TARGET_WORDS = (
    "wifi", "wi-fi", "online", "internet", "volumen", "modo", "notificacion",
    "pantalla", "luz", "bluetooth", "brillo", "sonido", "microfono", "camara",
    "bateria", "avion",
)


# Frases para forzar modo local a propósito (ahorrar tokens de Groq) aunque
# SÍ haya internet, sin tener que desconectar el wifi de verdad — y su
# contraparte para volver al modo automático (nube si hay internet).
FORCE_LOCAL_PHRASES = (
    "modo local", "modo ahorro", "ahorra tokens", "ahorrar tokens",
    "usa el modelo local", "usa la ia local", "no uses la nube", "no uses internet",
)
FORCE_ONLINE_PHRASES = (
    "modo online", "modo nube", "modo normal", "modo automatico",
    "usa groq", "vuelve a la nube", "usa el modelo grande",
)


def _classify_control_intent(command_text: str) -> str:
    """Detecta frases de control (salir/pausar/reiniciar/modo local) tolerando
    variaciones de conjugación, acentos y palabras de más alrededor — no exige
    una coincidencia exacta con una frase fija. Devuelve 'exit',
    'end_conversation', 'reset', 'force_local', 'force_online' o 'none'."""
    text = _normalize_text(command_text)
    targets_something_else = any(word in text for word in OTHER_TARGET_WORDS)

    if "adios" in text or "hasta luego" in text or "salir" in text:
        return "exit"
    if not targets_something_else and _has_word_starting_with(text, "apag", "desactiv"):
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

    # Las frases de forzar modo local/online son cortas por naturaleza
    # ("pasa a modo local", "modo ahorro"). Si aparecen dentro de un mensaje
    # largo es casi siempre porque el usuario está PREGUNTANDO sobre el modo
    # ("¿qué funciones tienes en modo local?"), no pidiendo activarlo — de lo
    # contrario esa pregunta nunca llega a la IA y solo repite el mensaje
    # fijo de activación una y otra vez.
    is_short_command = len(text.split()) <= 6
    if is_short_command and any(p in text for p in FORCE_LOCAL_PHRASES):
        return "force_local"
    if is_short_command and any(p in text for p in FORCE_ONLINE_PHRASES):
        return "force_online"

    return "none"


# Patrones para crear/activar/salir/olvidar el "modo estudio" de una materia
# (ver study_rag.py). El grupo capturado es el nombre de la materia tal cual
# lo dijo el usuario (con acentos/mayúsculas), para poder hablárselo de
# vuelta de forma natural — study_rag.py normaliza esto para la carpeta.
#
# "crear zona de estudio" es la vía pensada para alguien que recién empieza:
# crea la carpeta Y abre de una el selector de archivos de Windows para que
# elijas tus PDFs/apuntes ahí mismo, sin tener que ir manualmente a buscar la
# carpeta en el explorador. "modo estudio de X" (más abajo) asume que la
# carpeta ya tiene archivos (ej. si vuelves a estudiar otro día).
STUDY_CREATE_PATTERNS = (
    r"cr[eé]a(?:me)? (?:la |una |esta )?zona de estudio (?:de |para )(.+)",
    r"hazme (?:la |una |esta )?zona de estudio (?:de |para )(.+)",
    r"nueva zona de estudio (?:de |para )(.+)",
    r"cr[eé]a(?:me)? (?:la |una |esta )?carpeta de estudio (?:de |para )(.+)",
)
STUDY_START_PATTERNS = (
    r"modo estudio de (.+)",
    r"modo estudio (.+)",
    r"estudiemos (?:sobre )?(.+)",
    r"quiero estudiar (?:sobre )?(.+)",
    r"estudia conmigo (.+)",
    r"vamos a estudiar (?:sobre )?(.+)",
)
STUDY_STOP_PHRASES = (
    "sal del modo estudio", "salir del modo estudio", "termina el modo estudio",
    "deja de estudiar", "termine de estudiar", "ya acabe de estudiar",
    "acabe de estudiar", "acabamos de estudiar",
)
STUDY_FORGET_PATTERNS = (
    r"olvida (?:el estudio de |lo que sabes de |la materia de |la materia )(.+)",
    r"borra (?:el estudio de |el indice de |lo indexado de )(.+)",
)


def _extract_subject(text: str, patterns) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            subject = match.group(1).strip(" .!?¡¿,")
            if subject:
                return subject
    return ""


def _classify_study_intent(command_text: str):
    """Devuelve ('create', materia) / ('start', materia) / ('stop', None) /
    ('forget', materia) / ('none', None). Se revisa en texto normalizado solo
    para las frases fijas (stop) — para el resto se usa el texto original,
    así el nombre de la materia capturado conserva acentos y mayúsculas para
    hablarlo de vuelta."""
    normalized = _normalize_text(command_text)

    if normalized in STUDY_STOP_PHRASES:
        return "stop", None

    subject = _extract_subject(command_text, STUDY_FORGET_PATTERNS)
    if subject:
        return "forget", subject

    subject = _extract_subject(command_text, STUDY_CREATE_PATTERNS)
    if subject:
        return "create", subject

    subject = _extract_subject(command_text, STUDY_START_PATTERNS)
    if subject:
        return "start", subject

    return "none", None


def _handle_study_intent(command_text: str, voice, lock, stop_event):
    """Atiende las órdenes de 'modo estudio' (activar/salir/olvidar). Activar
    puede tardar unos segundos (indexar archivos nuevos), así que se despacha
    a un hilo aparte igual que las peticiones a la IA — nunca bloquea el
    micrófono/texto. Devuelve el estado, o None si el texto no es sobre esto."""
    kind, subject = _classify_study_intent(command_text)
    if kind == "none":
        return None

    print(f"Tú: {command_text}")
    ui_server.broadcast_transcript("user", command_text)

    if kind == "stop":
        active = study_state.get_subject()
        if active is None:
            reply = "No estabas en modo estudio de ninguna materia."
        else:
            study_state.set_subject(None)
            reply = f"Listo, salimos del modo estudio de {active}."
        print(f"Rochy: {reply}")
        ui_server.broadcast_transcript("assistant", reply)
        voice.speak(reply)
        _broadcast_mode()
        return "handled"

    if kind == "forget":
        if proc.busy_event.is_set():
            proc.cancel_event.set()
        reply = study_rag.forget_subject(subject)
        if study_state.get_subject() and _normalize_text(study_state.get_subject()) == _normalize_text(subject):
            study_state.set_subject(None)
        print(f"Rochy: {reply}")
        ui_server.broadcast_transcript("assistant", reply)
        voice.speak(reply)
        _broadcast_mode()
        return "handled"

    if kind == "create":
        # Solo crea la carpeta (instantáneo) y le pide a la INTERFAZ que abra
        # el selector de archivos — nunca lo abrimos nosotros directamente
        # desde este hilo (ver study_rag.pick_and_copy_files). El copiado e
        # indexado de verdad pasa después, cuando la interfaz responda.
        study_rag.ensure_subject_folder(subject)
        reply = (
            f"Listo, creé la zona de estudio de {subject}. Elige tus archivos (PDF, Word o texto) "
            "en la ventana que se va a abrir."
        )
        print(f"Rochy: {reply}")
        ui_server.broadcast_transcript("assistant", reply)
        voice.speak(reply)
        ui_server.broadcast_open_file_picker(subject)
        return "handled"

    # kind == "start"
    if proc.busy_event.is_set():
        proc.cancel_event.set()
    thread = threading.Thread(
        target=_process_study_start,
        args=(subject, voice, lock, stop_event),
        daemon=True,
    )
    thread.start()
    return "dispatched"


def _process_study_start(subject: str, voice, lock, stop_event) -> None:
    with lock:
        proc.cancel_event.clear()
        proc.busy_event.set()
        ui_server.broadcast_state("thinking")
        try:
            summary = study_rag.index_subject(subject)
            if "No encontré archivos" not in summary:
                study_state.set_subject(subject)
                reply = f"{summary} Modo estudio de {subject} activado."
            else:
                reply = summary
        except Exception as exc:
            reply = f"No pude preparar el modo estudio de '{subject}': {exc}"
        finally:
            proc.busy_event.clear()
            ui_server.broadcast_state("idle")

    print(f"Rochy: {reply}")
    ui_server.broadcast_transcript("assistant", reply)
    voice.speak(reply)
    _broadcast_mode()


def _broadcast_mode() -> None:
    """Le avisa a la interfaz el modo de IA actual (local/online) y la
    materia activa en modo estudio (o ninguna), para que lo muestre en la
    barra de estado — así el usuario ve en qué modo está sin tener que
    preguntarlo por voz."""
    ai_mode = "local" if mode_state.is_forced_local() else "online"
    ui_server.broadcast_mode(ai_mode, study_state.get_subject())


def _handle_fast_intent(command_text: str, config, brain, local_brain_ai, voice):
    """Atiende al instante las órdenes de control (salir/pausar/reiniciar/
    cambiar de modo) — ninguna necesita IA, así que nunca tardan. Devuelve el
    estado si aplicó alguna, o None si es charla/tarea normal y debe seguir a
    la IA (la parte que sí puede tardar, y por eso corre aparte)."""
    print(f"Tú: {command_text}")
    ui_server.broadcast_transcript("user", command_text)
    intent = _classify_control_intent(command_text)

    # Cualquier orden de control explícita (incluso "reinicia la conversación"
    # o cambiar de modo) significa que lo que se estuviera procesando de fondo
    # ya no le importa al usuario — que no reaparezca hablando solo cuando por
    # fin termine (o se destrabe, si estaba colgado con algo como Spotify).
    if intent != "none" and proc.busy_event.is_set():
        proc.cancel_event.set()

    if intent == "exit":
        farewell = "Hasta luego."
        print(f"{config.assistant_name}: {farewell} [cerrando la app]")
        voice.speak(farewell)
        ui_server.broadcast_transcript("assistant", farewell)
        return "exit"

    if intent == "end_conversation":
        reply = "De acuerdo, aquí estaré si me necesitas."
        print(f"{config.assistant_name}: {reply} [pausa, sigue abierta]")
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
        print(f"{config.assistant_name}: {reply} [conversación reiniciada]")
        voice.speak(reply)
        ui_server.broadcast_transcript("assistant", reply)
        return "handled"

    if intent == "force_local":
        if local_brain_ai is None:
            reply = "No tengo ninguna IA local instalada (Ollama) para poder hacer eso."
        else:
            mode_state.set_forced_local(True)
            reply = "Listo, modo local activado. No voy a usar la nube hasta que me digas lo contrario, aunque haya internet."
        print(f"{config.assistant_name}: {reply} [modo local forzado]")
        voice.speak(reply)
        ui_server.broadcast_transcript("assistant", reply)
        _broadcast_mode()
        return "handled"

    if intent == "force_online":
        mode_state.set_forced_local(False)
        reply = "Listo, vuelvo a usar la nube normalmente cuando haya internet."
        print(f"{config.assistant_name}: {reply} [modo local desactivado]")
        voice.speak(reply)
        ui_server.broadcast_transcript("assistant", reply)
        _broadcast_mode()
        return "handled"

    return None


def _generate_response(command_text: str, config, brain, local_brain_ai, cancel_event) -> str:
    """La parte que sí puede tardar (llamadas a la IA y sus herramientas —
    incluida una que se cuelgue, como Spotify sin sesión). Corre en un hilo
    aparte para no bloquear el micrófono/texto mientras dura. Devuelve None
    si se pidió cancelar mientras se procesaba (nada que decir ya)."""
    quick = parse_command(command_text)
    if quick["action"] in {"time", "open_app"}:
        return build_response(command_text)

    response = local_brain.try_local_answer(command_text, config.assistant_name)
    if response is not None:
        return response

    # Modo estudio activo: busca los fragmentos de tus apuntes más parecidos
    # a la pregunta y se los pega como contexto real antes de mandarla a la
    # IA (local o nube) — así responde con lo que de verdad dicen tus
    # archivos, en vez de solo lo que el modelo ya sabía de memoria.
    ai_input = command_text
    subject = study_state.get_subject()
    if subject is not None:
        chunks = study_rag.search(subject, command_text)
        if chunks:
            context_block = "\n\n".join(f"- {c}" for c in chunks)
            ai_input = (
                f"Contexto de mis apuntes de {subject} (úsalo si es relevante para responder, "
                f"y dilo con naturalidad si no lo es):\n{context_block}\n\nPregunta: {command_text}"
            )

    if mode_state.is_forced_local() and local_brain_ai is not None:
        return local_brain_ai.ask(ai_input, cancel_event=cancel_event)

    if connectivity.is_online():
        try:
            return brain.ask(ai_input, cancel_event=cancel_event)
        except Exception as exc:
            # Groq puede fallar aunque haya internet (cupo agotado, caída del
            # servicio, etc.) — si hay IA local, la usamos en vez de solo fallar.
            if local_brain_ai is not None:
                print(f"[aviso] Groq falló ({exc}), uso la IA local de respaldo.")
                return local_brain_ai.ask(ai_input, cancel_event=cancel_event)
            raise

    if local_brain_ai is not None:
        return local_brain_ai.ask(ai_input, cancel_event=cancel_event)

    return (
        "No tengo internet ni un modelo de IA local instalado ahora mismo. "
        "Solo puedo ayudarte con comandos básicos por ahora."
    )


def _finish_response(config, voice, response) -> str:
    """Dice y registra la respuesta ya generada. Si response es None, la
    petición se canceló mientras se procesaba (el usuario dijo "olvídalo" o
    dio otra orden) y no hay nada que decir — se salta en silencio."""
    if response is None:
        return "handled"

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


def _process_slow_command(command_text, config, brain, local_brain_ai, voice, lock, stop_event) -> None:
    """Ejecuta la parte lenta (IA/herramientas) en su propio hilo. Se queda
    esperando el lock compartido si otra petición sigue en curso — así solo
    una a la vez toca el historial de la IA — pero eso nunca bloquea al
    micrófono/texto, que siguen escuchando mientras tanto en su propio hilo."""
    with lock:
        # Se limpia justo aquí (no al pedir la cancelación) para que solo
        # afecte a la petición que de verdad estaba corriendo cuando se pidió.
        proc.cancel_event.clear()
        proc.busy_event.set()
        ui_server.broadcast_state("thinking")
        try:
            response = _generate_response(command_text, config, brain, local_brain_ai, proc.cancel_event)
            status = _finish_response(config, voice, response)
        except Exception as exc:
            _report_error(voice, exc)
            status = "handled"
        finally:
            proc.busy_event.clear()
            ui_server.broadcast_state("idle")

    if status == "exit":
        stop_event.set()


def _should_silently_ignore(command_text: str) -> bool:
    """Mientras Rochy está procesando algo, cualquier cosa que el micrófono/
    texto capte que NO sea un comando de control reconocido (cancelar, salir,
    pausar, reiniciar, cambiar de modo, modo estudio) se descarta ANTES de
    escribirse en el chat o quedar en el registro — no solo se ignora al
    final, se ignora sin dejar rastro visible. Antes cualquier frase suelta
    se mostraba en el chat aunque luego no se hiciera nada con ella, y eso
    confundía la conversación con fragmentos que en realidad nunca se
    atendieron."""
    if not proc.busy_event.is_set():
        return False
    if _is_cancel(command_text):
        return False
    study_kind, _ = _classify_study_intent(command_text)
    if study_kind != "none":
        return False
    if _classify_control_intent(command_text) != "none":
        return False
    return True


def _handle_command(command_text: str, config, brain, local_brain_ai, voice, lock, stop_event) -> str:
    """Punto de entrada único para un comando de voz o texto. Las órdenes de
    control (salir/pausar/reiniciar/cambiar de modo) se atienden al instante;
    todo lo demás (charla, tareas con IA) se despacha a un hilo aparte para
    que el micrófono/texto sigan activos mientras se genera la respuesta."""
    if _should_silently_ignore(command_text):
        # Solo queda en la consola/rochy.log para poder diagnosticar (nunca
        # llega al chat visible ni se habla) — es justo lo que antes SÍ se
        # mostraba y generaba confusión.
        print(f"[info] Ignorado en silencio (procesando otra cosa): {command_text!r}")
        return "handled"

    study_status = _handle_study_intent(command_text, voice, lock, stop_event)
    if study_status is not None:
        return study_status

    fast_status = _handle_fast_intent(command_text, config, brain, local_brain_ai, voice)
    if fast_status is not None:
        return fast_status

    thread = threading.Thread(
        target=_process_slow_command,
        args=(command_text, config, brain, local_brain_ai, voice, lock, stop_event),
        daemon=True,
    )
    thread.start()
    return "dispatched"


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
    """Si el texto es una frase de cancelación, responde al instante (sin
    esperar turno) y devuelve True. Si hay algo procesándose de fondo (ej. una
    llamada a Spotify colgada), lo marca para que se abandone en cuanto sea
    posible en vez de esperar a que termine — así "olvídalo" nunca se queda
    atascado detrás de algo lento."""
    if not _is_cancel(text):
        return False
    print(f"Tú: {text}")
    ui_server.broadcast_transcript("user", text)
    if proc.busy_event.is_set():
        proc.cancel_event.set()
        reply = "Listo, cancelado. Dime qué necesitas."
    else:
        reply = "No hay nada que cancelar ahora mismo."
    ui_server.broadcast_transcript("assistant", reply)
    try:
        voice.speak(reply)
    except Exception:
        pass
    ui_server.broadcast_state("idle")
    return True


def _wait_while_speaking(stop_event: threading.Event) -> None:
    """Pausa aquí mientras Rochy esté hablando (ver processing_state.speaking_event)
    en vez de escuchar por el micrófono — si no, puede captar su propia voz
    saliendo por los parlantes y procesarla como si fuera una orden nueva
    (esto pasó de verdad: "abriendo explorer" hablado se escuchó a sí mismo y
    volvió a abrir explorer sin parar)."""
    while proc.speaking_event.is_set() and not stop_event.is_set():
        time.sleep(0.1)


def _voice_loop(
    config, brain, local_brain_ai, voice, listener, lock: threading.Lock, stop_event: threading.Event
) -> None:
    while not stop_event.is_set():
        try:
            ui_server.broadcast_state("idle")
            _wait_while_speaking(stop_event)
            heard = listener.listen(timeout=5, phrase_time_limit=4)
            if not heard or config.wake_word not in heard.lower():
                continue

            voice.speak("Dime.")

            # Modo conversación: una vez activado, sigue escuchando turno tras
            # turno sin necesitar la palabra clave otra vez, hasta que haya
            # silencio o el usuario indique que terminó. El procesamiento con
            # IA se despacha a otro hilo (ver _handle_command), así que este
            # bucle nunca deja de escuchar mientras Rochy "piensa" — pero SÍ
            # se pausa mientras habla, para no escucharse a sí misma.
            while not stop_event.is_set():
                ui_server.broadcast_state("listening")
                _wait_while_speaking(stop_event)
                command_text = listener.listen(timeout=CONVERSATION_TIMEOUT, phrase_time_limit=15)
                if not command_text:
                    # Si algo sigue procesándose de fondo, el silencio no cuenta
                    # como que la conversación terminó — seguimos escuchando.
                    if proc.busy_event.is_set():
                        continue
                    break

                if _handle_cancel_if_requested(command_text, voice):
                    continue

                status = _handle_command(command_text, config, brain, local_brain_ai, voice, lock, stop_event)
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
            status = _handle_command(text, config, brain, local_brain_ai, voice, lock, stop_event)
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
    _broadcast_mode()  # para que la interfaz muestre el modo correcto desde que conecta

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

    import ui_bridge

    ui_server.start()
    window = webview.create_window(
        assistant_name,
        INTERFACE_PATH,
        width=380,
        height=680,
        background_color="#05070d",
        on_top=True,
        js_api=ui_bridge.StudyFilesApi(),
    )

    # Cerrar con la X de la ventana no pasa por el bucle de voz/texto (que
    # sigue en su propio hilo esperando el micrófono) — sin esto, el proceso
    # se quedaba vivo en segundo plano aunque la ventana ya no se viera.
    window.events.closed += lambda: os._exit(0)

    webview.start(_assistant_loop, window)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nApagando asistente.")
        sys.exit(0)
