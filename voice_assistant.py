import datetime
import difflib
import os
import random
import re
import subprocess
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

import audio_ducking
import connectivity
import control_signal
import local_brain
import mode_state
import processing_state as proc
import sound_cues
import study_rag
import study_state
import system_control as sc
import ui_rochy_server
import ui_server

# Ruta al otro proyecto/carpeta (gestos_control, aparte a propósito) — con
# el usuario de Windows actual, no "roger" fijo, mismo motivo que
# ui_rochy_server.UI_ROCHY_DIR: para que funcione igual en la PC de un
# colaborador si algún día tiene esa carpeta en su propio Documents.
GESTOS_CONTROL_DIR = os.path.join(os.path.expanduser("~"), "Documents", "gestos_control")

# Antes gestos_control se abría solo, junto con Rochy — ahora, a propósito,
# solo arranca cuando se pide por voz ("activa los gestos"), así la cámara
# nunca está encendida sin que el usuario lo haya pedido explícitamente.
_gestures_process: "subprocess.Popen | None" = None


def _start_gestures() -> str:
    global _gestures_process
    if _gestures_process is not None and _gestures_process.poll() is None:
        return "Los gestos ya estaban activados."
    pythonw = os.path.join(GESTOS_CONTROL_DIR, "venv", "Scripts", "pythonw.exe")
    main_script = os.path.join(GESTOS_CONTROL_DIR, "main.py")
    if not os.path.isfile(pythonw) or not os.path.isfile(main_script):
        return "No encontré el proyecto de control por gestos instalado en esta PC."
    _gestures_process = subprocess.Popen([pythonw, main_script], cwd=GESTOS_CONTROL_DIR)
    return "Listo, activé el control por gestos."


def _stop_gestures() -> str:
    global _gestures_process
    if _gestures_process is None or _gestures_process.poll() is not None:
        _gestures_process = None
        return "Los gestos ya estaban desactivados."
    _gestures_process.terminate()
    _gestures_process = None
    return "Listo, desactivé el control por gestos."


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


# Segundos de silencio dentro de una conversación de voz antes de volver a
# esperar la palabra clave. No es un número fijo: una respuesta larga (varios
# párrafos hablados) merece más margen para pensar la siguiente pregunta que
# una respuesta corta ("listo, hecho") — se calcula sumando un extra
# proporcional a cuánto duró lo último que Rochy dijo (ver
# processing_state.last_speech_seconds, actualizado en tts.py).
BASE_CONVERSATION_TIMEOUT = 18.0
MAX_CONVERSATION_TIMEOUT = 45.0
EXTRA_TIMEOUT_PER_SPOKEN_SECOND = 0.6

# Antes de dar por terminada la conversación en silencio (lo que se sentía
# como que Rochy "se desactivaba sola" sin avisar), se pregunta una vez si
# seguís ahí — le da una segunda oportunidad antes de exigir la palabra
# clave de nuevo.
STILL_THERE_PHRASE = "¿Sigues ahí?"


def _conversation_timeout() -> float:
    extra = proc.last_speech_seconds * EXTRA_TIMEOUT_PER_SPOKEN_SECOND
    return min(MAX_CONVERSATION_TIMEOUT, BASE_CONVERSATION_TIMEOUT + extra)

# Si una tarea (IA + herramientas, o indexar archivos del modo estudio) tarda
# más que esto sin terminar, se avisa con un acuse de recibo corto — para que
# no parezca que Rochy se quedó colgada en algo que en realidad solo tarda
# (ej. encadenar varias herramientas, o cargar el modelo de embeddings la
# primera vez). Las respuestas rápidas normales nunca llegan a dispararlo.
# (4s era demasiado poco: el modelo LOCAL con herramientas de por medio
# fácilmente pasa de eso, así que sonaba en casi cada respuesta — molesto en
# vez de útil. Con 7s solo se dispara en lo que de verdad tarda.)
ACK_DELAY_SECONDS = 7.0
ACK_PHRASES = ("Dame un momento.", "Un segundo, sigo en eso.", "Ya casi termino con eso.")

# Ratito extra de "modo cancelación solamente" justo después de que Rochy
# termina de hablar (ver processing_state.speech_ended_at) — sin auriculares,
# el eco físico del parlante puede seguir sonando en el cuarto un instante
# después de que speaking_event ya se limpió. Solo mirar el flag de estado
# no alcanza: el micrófono puede haber EMPEZADO a grabar antes de que
# arrancara a hablar y terminado de grabar recién cuando ya llevaba un rato
# en silencio, sin que ninguno de los dos chequeos (antes/después) coincida
# con el momento exacto en que sí estaba hablando.
POST_SPEECH_GRACE_SECONDS = 1.5


def _speak_ack(voice) -> None:
    if proc.cancel_event.is_set():
        return  # ya se pidió cancelar, no tiene sentido avisar de algo que se va a abandonar
    try:
        voice.speak(random.choice(ACK_PHRASES))
    except Exception:
        pass


def _start_ack_timer(voice) -> threading.Timer:
    timer = threading.Timer(ACK_DELAY_SECONDS, _speak_ack, args=(voice,))
    timer.daemon = True
    timer.start()
    return timer

# Frases que cancelan lo que se esté procesando, respondidas al instante (sin
# esperar turno ni gastar tokens de IA) — chequeadas antes de tomar el lock
# compartido, para que un "cancela" nunca se quede esperando detrás de algo
# que está tardando (ej. Spotify colgado esperando una respuesta de la red).
CANCEL_PHRASES = {
    "cancela", "cancelar", "detente", "para", "olvidalo",
    "ya no", "ya no lo hagas", "no lo hagas", "mejor olvidalo",
    "cancela eso", "detente ya", "espera",
}

# Frases que pausan la conversación — coincidencia EXACTA (como CANCEL_PHRASES
# arriba), no de subcadena. "gracias" se quitó por completo: el micrófono a
# veces la "escucha" de la nada (ruido/mala transcripción) en medio de una
# conversación normal, y pausar la app de golpe por eso era muy molesto. Para
# pausar de verdad, usa "descansa" (root-word, más abajo) u otra de estas.
END_CONVERSATION_PHRASES = {
    "eso es todo", "eso seria todo", "nada mas",
}


def _is_cancel(text: str) -> bool:
    # "para" se deja como coincidencia EXACTA (no de subcadena/raíz): es una
    # palabra demasiado común en español ("ábrelo para mí") como para
    # detectarla dentro de cualquier frase sin generar falsos positivos.
    normalized = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", _normalize_text(text))
    return normalized in CANCEL_PHRASES


# Qué tan parecido (0 a 1) tiene que ser lo oído a lo último que Rochy dijo
# para descartarlo como eco de su propia voz colándose por el micrófono (sin
# auriculares) en vez de tratarlo como un comando real del usuario.
SELF_ECHO_SIMILARITY = 0.65


def _sounds_like_self_echo(heard_text: str) -> bool:
    """Compara lo recién oído contra lo último que salió por los parlantes
    (ver processing_state.last_spoken_text, actualizado en tts.py). Cubre el
    caso en que el eco físico del parlante llega al micrófono DESPUÉS de que
    speaking_event ya se limpió (el sonido tarda un instante en apagarse del
    todo en el cuarto) — el chequeo de estado por sí solo no alcanza a
    detectar esto porque, para cuando se oye, Rochy ya "no está hablando"
    según el estado interno. Esto pasó de verdad: dijo la hora y se escuchó
    a sí misma diciéndola de nuevo como si fuera el usuario repitiéndola."""
    last = proc.last_spoken_text
    if not last or not heard_text:
        return False
    a = _normalize_text(heard_text)
    b = _normalize_text(last)
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    return ratio >= SELF_ECHO_SIMILARITY


# Qué tan parecida (0 a 1) tiene que ser una palabra oída a la palabra clave
# para aceptarla igual, aunque Whisper la haya transcrito distinto ("ola", sin
# la hache muda) en vez de exigir la ortografía exacta configurada.
#
# 0.75 (el valor original) resultó ser demasiado permisivo — se comprobó de
# verdad que palabras comunes del español coinciden por accidente con "hola"
# a exactamente esa similitud: "hora", "sola", "cola", "bola", "olla", "hala".
# Con ruido de fondo (una tele, alguien más hablando) que solo tenga que
# mencionar la HORA para activar a Rochy sin que nadie le hablara a propósito
# — y peor, lo que se transcriba después de eso se procesa como si fuera un
# pedido real. Subido a 0.80: sigue agarrando "ola" (0.86, la variante real
# más común, sin la hache) pero ya no esas palabras comunes (todas en 0.75).
WAKE_WORD_SIMILARITY = 0.80


def _sounds_like_wake_word(heard_text: str, wake_word: str) -> tuple[bool, str | None]:
    """Coincidencia exacta primero (rápido); si no, compara palabra por
    palabra por si la transcripción varió fonéticamente en vez de perder
    activaciones reales solo por una letra distinta. Devuelve además CON QUÉ
    coincidió (o None) para poder dejarlo registrado — antes una activación
    por parecido fonético no dejaba ningún rastro de qué fue lo que "sonó
    parecido a hola", solo lo rechazado quedaba en el log."""
    wake_norm = _normalize_text(wake_word)
    heard_norm = _normalize_text(heard_text)
    if wake_norm in heard_norm:
        return True, heard_text
    for word in re.findall(r"[a-z]+", heard_norm):
        if difflib.SequenceMatcher(None, word, wake_norm).ratio() >= WAKE_WORD_SIMILARITY:
            return True, word
    return False, None


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
    "bateria", "avion", "remoto", "calidad", "gestos",
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

# Frases para pasar al "control remoto" (micrófono del celular como entrada
# principal, ver interface/remote.html) y su contraparte para volver al
# micrófono normal de la PC. Ojo: NO se usa "modo normal" aquí — esa frase ya
# significa "vuelve a la nube" arriba (FORCE_ONLINE_PHRASES); usar la misma
# frase para dos cosas distintas sería ambiguo.
REMOTE_CONTROL_ON_PHRASES = (
    "control remoto", "activa el control remoto", "modo control remoto",
    "pasa a control remoto", "usa el celular como microfono",
)
REMOTE_CONTROL_OFF_PHRASES = (
    "desactiva el control remoto", "sal del control remoto",
    "termina el control remoto", "apaga el control remoto",
    "deja el control remoto", "vuelve al microfono normal",
)

# Frases para ajustar la "calidad" de las respuestas de la IA en la nube (ver
# mode_state.get_quality()/set_quality() y QUALITY_PRESETS en ai_brain.py):
# "bajo" prioriza velocidad/gasto, "alto" prioriza razonamiento. A propósito
# NO se reutiliza "modo ahorro"/"ahorra tokens" aquí: esas frases ya
# significan "fuerza el modelo local" (FORCE_LOCAL_PHRASES) y usarlas también
# para esto sería ambiguo.
QUALITY_LOW_PHRASES = (
    "calidad baja", "baja calidad", "calidad minima", "modo economico",
    "calidad en baja", "baja la calidad", "menos calidad",
)
QUALITY_MEDIUM_PHRASES = (
    "calidad media", "media calidad", "calidad normal", "modo balanceado",
    "calidad en media", "calidad estandar",
)
# Frases para activar/desactivar el proyecto de gestos (gestos_control) por
# completo — antes se abría solo junto con Rochy; ahora, a propósito, no
# arranca hasta que se pida (así la cámara nunca está encendida sin que el
# usuario lo haya pedido). "activar/desactivar" ya está en OTHER_TARGET_WORDS
# vía "remoto"/"camara" para otras cosas — acá se agrega "gestos" al mismo
# fin, para no confundirse con "apágate"/"desactiva el control remoto".
GESTURES_ON_PHRASES = (
    "activa los gestos", "activa el control por gestos", "enciende los gestos",
)
GESTURES_OFF_PHRASES = (
    "desactiva los gestos", "apaga los gestos", "desactiva el control por gestos",
)

# Frases para esconder/mostrar el panel de video de gestos_control en la
# interfaz de Rochy (el ÚNICO lugar donde se puede ver — ya no tiene ventana
# propia) sin desactivar la detección de gestos en sí.
CAMERA_HIDE_PHRASES = (
    "oculta la camara", "esconde la camara", "quita la camara",
)
CAMERA_SHOW_PHRASES = (
    "muestra la camara", "vuelve a mostrar la camara",
)

QUALITY_HIGH_PHRASES = (
    "calidad alta", "alta calidad", "calidad maxima", "modo experto",
    "mejor razonamiento", "razona mejor", "piensa mejor",
    "calidad en alta", "sube la calidad", "mas calidad",
)


def _classify_control_intent(command_text: str) -> str:
    """Detecta frases de control (salir/pausar/reiniciar/modo local) tolerando
    variaciones de conjugación, acentos y palabras de más alrededor — no exige
    una coincidencia exacta con una frase fija. Devuelve 'exit',
    'end_conversation', 'reset', 'force_local', 'force_online',
    'remote_control_on', 'remote_control_off', 'quality_low', 'quality_medium',
    'quality_high', 'camera_hide', 'camera_show', 'gestures_on', 'gestures_off'
    o 'none'."""
    text = _normalize_text(command_text)
    targets_something_else = any(word in text for word in OTHER_TARGET_WORDS)

    if "adios" in text or "hasta luego" in text or "salir" in text:
        return "exit"
    if not targets_something_else and _has_word_starting_with(text, "apag", "desactiv"):
        return "exit"

    # "gracias"/"eso es todo" antes se buscaban como subcadena — cualquier
    # frase que las mencionara de pasada (ej. "gracias por lo de ayer, pero
    # necesito...") pausaba la app sin que el usuario quisiera terminar la
    # conversación. Ahora, igual que con "para" en CANCEL_PHRASES, se exige
    # que sea (casi) toda la frase, no una mención suelta en medio de otra cosa.
    stripped = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", text)
    if _has_word_starting_with(text, "descans") or stripped in END_CONVERSATION_PHRASES:
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

    # OFF se revisa antes que ON a propósito: "desactiva el control remoto"
    # también contiene la subcadena "control remoto" (la frase de ON), así
    # que si se revisara ON primero nunca se llegaría a detectar el OFF.
    if is_short_command and any(p in text for p in REMOTE_CONTROL_OFF_PHRASES):
        return "remote_control_off"
    if is_short_command and any(p in text for p in REMOTE_CONTROL_ON_PHRASES):
        return "remote_control_on"

    if is_short_command and any(p in text for p in CAMERA_HIDE_PHRASES):
        return "camera_hide"
    if is_short_command and any(p in text for p in CAMERA_SHOW_PHRASES):
        return "camera_show"

    # OFF antes que ON a propósito: "desactiva los gestos" contiene la
    # subcadena "activa los gestos" (des-ACTIVA), igual que ya pasaba con
    # control remoto — si se revisara ON primero nunca se llegaría al OFF.
    if is_short_command and any(p in text for p in GESTURES_OFF_PHRASES):
        return "gestures_off"
    if is_short_command and any(p in text for p in GESTURES_ON_PHRASES):
        return "gestures_on"

    if is_short_command and any(p in text for p in QUALITY_LOW_PHRASES):
        return "quality_low"
    if is_short_command and any(p in text for p in QUALITY_HIGH_PHRASES):
        return "quality_high"
    if is_short_command and any(p in text for p in QUALITY_MEDIUM_PHRASES):
        return "quality_medium"

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


def _handle_study_intent(command_text: str, voice, lock, stop_event, source: str = "voz"):
    """Atiende las órdenes de 'modo estudio' (activar/salir/olvidar). Activar
    puede tardar unos segundos (indexar archivos nuevos), así que se despacha
    a un hilo aparte igual que las peticiones a la IA — nunca bloquea el
    micrófono/texto. Devuelve el estado, o None si el texto no es sobre esto."""
    kind, subject = _classify_study_intent(command_text)
    if kind == "none":
        return None

    print(f"Tú ({source}): {command_text}")
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
        ack_timer = _start_ack_timer(voice)
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
            ack_timer.cancel()
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


def _handle_fast_intent(command_text: str, config, brain, gemini_brain_ai, local_brain_ai, voice, source: str = "voz"):
    """Atiende al instante las órdenes de control (salir/pausar/reiniciar/
    cambiar de modo) — ninguna necesita IA, así que nunca tardan. Devuelve el
    estado si aplicó alguna, o None si es charla/tarea normal y debe seguir a
    la IA (la parte que sí puede tardar, y por eso corre aparte)."""
    print(f"Tú ({source}): {command_text}")
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
        # Sin esto, pedir "descansa" por texto/celular mientras la conversación
        # seguía activa por VOZ no la cortaba — cada canal solo sabía terminar
        # SU PROPIA conversación. Esta señal la revisa el bucle de voz para
        # cortar la suya aunque la orden haya llegado por otro canal.
        proc.end_conversation_event.set()
        return "end_conversation"

    if intent == "reset":
        # vía de escape si el modelo se queda "atascado" (ej. sigue negándose a
        # cosas normales tras rechazar un pedido anterior) — sin cerrar la app.
        brain.reset()
        if gemini_brain_ai is not None:
            gemini_brain_ai.reset()
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

    if intent == "remote_control_on":
        mode_state.set_remote_control(True)
        reply = (
            "Listo, control remoto activado. Ya no escucho la palabra clave en la PC — "
            "usa el celular para hablarme. Si estoy hablando, puedes decir 'espera' o "
            "'cancela' y te sigo escuchando para eso."
        )
        print(f"{config.assistant_name}: {reply} [control remoto activado]")
        voice.speak(reply)
        ui_server.broadcast_transcript("assistant", reply)
        ui_server.broadcast_remote_control(True)
        return "handled"

    if intent == "remote_control_off":
        mode_state.set_remote_control(False)
        reply = "Listo, vuelvo a escuchar la palabra clave normalmente en la PC."
        print(f"{config.assistant_name}: {reply} [control remoto desactivado]")
        voice.speak(reply)
        ui_server.broadcast_transcript("assistant", reply)
        ui_server.broadcast_remote_control(False)
        return "handled"

    if intent in ("camera_hide", "camera_show"):
        hide = intent == "camera_hide"
        ui_server.broadcast_camera_control("hide" if hide else "show")
        reply = "Listo, oculté el video de la cámara." if hide else "Listo, mostrando el video de la cámara."
        print(f"{config.assistant_name}: {reply} [camara = {'oculta' if hide else 'visible'}]")
        voice.speak(reply)
        ui_server.broadcast_transcript("assistant", reply)
        return "handled"

    if intent in ("gestures_on", "gestures_off"):
        reply = _start_gestures() if intent == "gestures_on" else _stop_gestures()
        print(f"{config.assistant_name}: {reply} [gestos = {'activados' if intent == 'gestures_on' else 'desactivados'}]")
        voice.speak(reply)
        ui_server.broadcast_transcript("assistant", reply)
        return "handled"

    if intent in ("quality_low", "quality_medium", "quality_high"):
        level = {"quality_low": "bajo", "quality_medium": "medio", "quality_high": "alto"}[intent]
        mode_state.set_quality(level)
        reply = {
            "bajo": "Listo, calidad baja: respuestas más rápidas y con menos gasto de tokens.",
            "medio": "Listo, calidad media: el balance de siempre.",
            "alto": "Listo, calidad alta: voy a razonar más antes de responder.",
        }[level]
        print(f"{config.assistant_name}: {reply} [calidad = {level}]")
        voice.speak(reply)
        ui_server.broadcast_transcript("assistant", reply)
        ui_server.broadcast_quality(level)
        return "handled"

    return None


def _generate_response(command_text: str, config, brain, gemini_brain_ai, local_brain_ai, cancel_event) -> str:
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
        # SIEMPRE se le avisa que el modo estudio está activo, aunque esta
        # pregunta puntual no encuentre fragmentos relevantes en los apuntes
        # (ej. una pregunta sobre el modo mismo, no sobre el tema) — antes,
        # sin fragmentos, la IA no tenía ninguna pista de que seguía en modo
        # estudio y llegó a negarlo ("no estoy en modo estudio") estando
        # activo de verdad, porque nunca se le dijo.
        try:
            chunks = study_rag.search(subject, command_text)
        except Exception as exc:
            # Un fallo cargando el modelo de embeddings (ej. una DLL de torch
            # que no cargó a tiempo) no debe tumbar la respuesta ENTERA — esto
            # pasó de verdad: con modo estudio activo, hasta preguntas sin
            # ninguna relación con la materia dejaron de responderse por
            # completo. Sin apuntes disponibles, seguimos igual que si
            # búsqueda no hubiera encontrado nada.
            print(f"[aviso] Modo estudio: no se pudo buscar en los apuntes ({exc}), sigo sin ese contexto.")
            chunks = []
        if chunks:
            context_block = "\n\n".join(f"- {c}" for c in chunks)
            ai_input = (
                f"[Modo estudio activo, materia: {subject}]\n"
                f"Contexto de mis apuntes de {subject} (úsalo si es relevante para responder, "
                f"y dilo con naturalidad si no lo es):\n{context_block}\n\nPregunta: {command_text}"
            )
        else:
            ai_input = (
                f"[Modo estudio activo, materia: {subject}. No encontré fragmentos de mis apuntes "
                f"relevantes para esta pregunta puntual.]\n\nPregunta: {command_text}"
            )

    if mode_state.is_forced_local() and local_brain_ai is not None:
        return local_brain_ai.ask(ai_input, cancel_event=cancel_event)

    if connectivity.is_online():
        try:
            return brain.ask(ai_input, cancel_event=cancel_event)
        except Exception as exc:
            # Groq puede fallar aunque haya internet (cupo agotado, caída del
            # servicio, etc.) — antes de caer a la IA local, se prueba un
            # segundo proveedor en la nube (Gemini, capa gratuita) si está
            # configurado: sigue siendo "en línea" de verdad, solo cambia de
            # proveedor, así que el pill no necesita avisar nada especial aquí.
            print(f"[aviso] Groq falló ({exc}), pruebo el siguiente respaldo.")
            if gemini_brain_ai is not None:
                try:
                    return gemini_brain_ai.ask(ai_input, cancel_event=cancel_event)
                except Exception as exc2:
                    print(f"[aviso] Gemini también falló ({exc2}), uso la IA local de respaldo.")
            if local_brain_ai is not None:
                # Antes esto pasaba en total silencio para la interfaz: el pill
                # seguía diciendo "En línea" aunque la respuesta se generara en
                # local — el usuario no tenía forma de saberlo (esto pasó de
                # verdad con el cupo diario de Groq agotado). Se avisa mientras
                # dura esta respuesta puntual, y se revierte al estado real
                # apenas termina (no queda "pegado" en local si no corresponde).
                ui_server.broadcast_mode("local", study_state.get_subject())
                try:
                    return local_brain_ai.ask(ai_input, cancel_event=cancel_event)
                finally:
                    _broadcast_mode()
            raise

    if local_brain_ai is not None:
        # Mismo aviso que arriba: sin internet detectado, se usa la IA local
        # para esta respuesta — el pill lo refleja mientras dura.
        ui_server.broadcast_mode("local", study_state.get_subject())
        try:
            return local_brain_ai.ask(ai_input, cancel_event=cancel_event)
        finally:
            _broadcast_mode()

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

    # El texto se muestra justo cuando el audio empieza a sonar de verdad
    # (on_start), no apenas se generó la respuesta — antes aparecía al
    # instante pero la síntesis de voz tardaba varios segundos en un texto
    # largo, así que para cuando por fin hablaba ya habías terminado de leer.
    def _on_start():
        print(f"{config.assistant_name}: {response}")
        ui_server.broadcast_transcript("assistant", response)

    voice.speak(response, on_start=_on_start)

    # Respaldo semántico: si el filtro rápido no detectó nada pero la IA, con
    # el contexto completo, decidió que sí querías pausar/apagar (herramienta
    # end_session), respetamos esa decisión también.
    signal = control_signal.pop()
    if signal == "exit":
        return "exit"
    if signal == "pause":
        return "end_conversation"

    return "handled"


def _process_slow_command(command_text, config, brain, gemini_brain_ai, local_brain_ai, voice, lock, stop_event) -> None:
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
        ack_timer = _start_ack_timer(voice)
        try:
            response = _generate_response(command_text, config, brain, gemini_brain_ai, local_brain_ai, proc.cancel_event)
            status = _finish_response(config, voice, response)
        except Exception as exc:
            _report_error(voice, exc)
            status = "handled"
        finally:
            ack_timer.cancel()
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


def _handle_command(
    command_text: str, config, brain, gemini_brain_ai, local_brain_ai, voice, lock, stop_event, source: str = "voz"
) -> str:
    """Punto de entrada único para un comando de voz, texto o celular. Las
    órdenes de control (salir/pausar/reiniciar/cambiar de modo) se atienden
    al instante; todo lo demás (charla, tareas con IA) se despacha a un hilo
    aparte para que el micrófono/texto sigan activos mientras se genera la
    respuesta. "source" (voz/texto/celular) solo es para que rochy.log deje
    claro de dónde vino cada comando — antes todos se veían igual ("Tú: ..."),
    lo que hacía imposible saber si algo pasó por voz o si se escribió."""
    if _should_silently_ignore(command_text):
        # Solo queda en la consola/rochy.log para poder diagnosticar (nunca
        # llega al chat visible ni se habla) — es justo lo que antes SÍ se
        # mostraba y generaba confusión.
        print(f"[info] Ignorado en silencio (procesando otra cosa): {command_text!r}")
        return "handled"

    study_status = _handle_study_intent(command_text, voice, lock, stop_event, source)
    if study_status is not None:
        return study_status

    fast_status = _handle_fast_intent(command_text, config, brain, gemini_brain_ai, local_brain_ai, voice, source)
    if fast_status is not None:
        return fast_status

    thread = threading.Thread(
        target=_process_slow_command,
        args=(command_text, config, brain, gemini_brain_ai, local_brain_ai, voice, lock, stop_event),
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


def _handle_cancel_if_requested(text: str, voice, source: str = "voz") -> bool:
    """Si el texto es una frase de cancelación, responde al instante (sin
    esperar turno) y devuelve True. Si hay algo procesándose de fondo (ej. una
    llamada a Spotify colgada), lo marca para que se abandone en cuanto sea
    posible en vez de esperar a que termine — así "olvídalo" nunca se queda
    atascado detrás de algo lento."""
    if not _is_cancel(text):
        return False
    print(f"Tú ({source}): {text}")
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


def _run_conversation_turns(
    config, brain, gemini_brain_ai, local_brain_ai, voice, listener, lock: threading.Lock, stop_event: threading.Event
) -> None:
    """Modo conversación: una vez activado (palabra clave o gesto), sigue
    escuchando turno tras turno sin necesitar activarse de nuevo, hasta que
    haya silencio o el usuario indique que terminó. El procesamiento con IA
    se despacha a otro hilo (ver _handle_command), así que este bucle nunca
    deja de escuchar mientras Rochy "piensa".

    MIENTRAS HABLA, el micrófono también se queda activo (antes se pausaba
    del todo) — pero solo reacciona si lo que oye es una cancelación real
    (ver CANCEL_PHRASES): cualquier otra cosa se ignora en silencio sin
    mostrarse ni procesarse, así que aunque su propia voz se cuele por el
    micrófono (sin auriculares) nunca pasa nada raro — no coincide con esas
    frases exactas y se descarta. Esto es a propósito: antes, con el
    micrófono pausado del todo mientras hablaba, no había forma de
    interrumpirla a mitad de una respuesta larga, y eso se sentía como
    quedar "bloqueado" varios segundos sin poder decir nada."""
    still_there_asked = False
    while not stop_event.is_set():
        if proc.end_conversation_event.is_set():
            # "descansa" pedido desde otro canal (texto/celular) mientras
            # esta conversación por voz seguía activa — se corta acá aunque
            # la orden no haya llegado por este bucle. Se limpia enseguida:
            # es una señal de un solo uso.
            proc.end_conversation_event.clear()
            break
        speaking_now = proc.speaking_event.is_set()
        in_echo_grace = not speaking_now and (time.time() - proc.speech_ended_at < POST_SPEECH_GRACE_SECONDS)
        treat_as_speaking = speaking_now or in_echo_grace
        ui_server.broadcast_state("speaking" if treat_as_speaking else "listening")
        if not treat_as_speaking:
            # Pitido corto: marca el momento exacto en que el micrófono
            # empieza a escuchar de verdad de un turno normal (no mientras
            # habla ni en el ratito justo después — ahí no, para no sonar
            # de más).
            sound_cues.listening_started()
        if treat_as_speaking:
            # Ventanas cortas mientras habla (o en el ratito justo después)
            # — así una cancelación se detecta rápido, en vez de esperar
            # hasta 15s a que la frase "termine" (que con su propia voz de
            # fondo podría tardar en darse por terminada).
            command_text = listener.listen(timeout=1.5, phrase_time_limit=3)
        else:
            # Se escucha en dos mitades del tiempo total permitido (ver
            # _conversation_timeout, ya no es un número fijo): si la primera
            # mitad pasa en silencio, se pregunta "¿sigues ahí?" en vez de
            # cortar la conversación sin avisar — solo si la SEGUNDA mitad
            # también pasa en silencio se da por terminada de verdad.
            command_text = listener.listen(timeout=_conversation_timeout() / 2, phrase_time_limit=15)
        if not command_text:
            # Mientras habla (o en el ratito de gracia justo después), un
            # silencio corto no significa nada — es solo que esa ventana de
            # sondeo es breve a propósito. Antes esto podía cortar la
            # conversación entera por accidente: si justo en esos 1.5s de
            # gracia no se oía nada Y nada más seguía procesándose, se
            # trataba como si el usuario hubiera abandonado la conversación
            # de verdad.
            if treat_as_speaking or proc.busy_event.is_set() or proc.speaking_event.is_set():
                continue
            if not still_there_asked:
                still_there_asked = True
                voice.speak(STILL_THERE_PHRASE)
                continue
            break

        still_there_asked = False

        if treat_as_speaking or proc.speaking_event.is_set():
            # OJO: se filtra si estaba hablando (o recién terminó de hablar,
            # ver POST_SPEECH_GRACE_SECONDS) ANTES de escuchar
            # (treat_as_speaking) O JUSTO DESPUÉS (is_set() de nuevo aquí) —
            # cubre la carrera en los dos sentidos. Grabar + transcribir
            # tarda uno o dos segundos, tiempo de sobra para que Rochy
            # empiece o termine de hablar A MITAD de esa espera. Si solo
            # mirábamos un lado, su propia voz recién grabada se colaba
            # como si fuera un comando real del usuario. Esto pasó de
            # verdad: se escuchó preguntar algo y lo procesó como si el
            # usuario hubiera repetido la misma pregunta.
            if _is_cancel(command_text):
                print(f"Tú (voz): {command_text}")
                ui_server.broadcast_transcript("user", command_text)
                voice.stop_speaking()
                proc.cancel_event.set()
                ui_server.broadcast_transcript("assistant", "[interrumpido]")
                # Antes solo se veía "[interrumpido]" en el chat, sin decir
                # nada en voz — se sentía raro cortarla y que se quede en
                # silencio total sin reconocer que entendió.
                voice.speak("Entendido, cancelado.")
            # lo que no sea cancelación se ignora del todo, ni se registra —
            # es justo lo que se oye mientras habla.
            continue

        if _sounds_like_self_echo(command_text):
            # No estaba marcada como "hablando" (ya se filtró arriba), pero
            # lo oído es casi idéntico a lo último que ella misma dijo — eco
            # físico del parlante llegando al micrófono, no el usuario. Se
            # registra para diagnóstico, pero no se muestra ni se procesa
            # como comando real.
            print(f"[info] Ignorado por parecer eco de su propia voz: {command_text!r}")
            continue

        sound_cues.listening_stopped()

        if _handle_cancel_if_requested(command_text, voice):
            continue

        status = _handle_command(command_text, config, brain, gemini_brain_ai, local_brain_ai, voice, lock, stop_event)
        if status == "exit":
            stop_event.set()
            break
        if status == "end_conversation":
            break


def _voice_loop(
    config, brain, gemini_brain_ai, local_brain_ai, voice, listener, lock: threading.Lock, stop_event: threading.Event
) -> None:
    while not stop_event.is_set():
        try:
            if proc.gesture_wake_event.is_set():
                # Gesto de "quiero hablarte" (palma abierta sostenida, ver
                # gestos_control) — activa la conversación igual que la
                # palabra clave, sin importar si el control remoto está
                # activo (es una entrada física distinta al micrófono de la
                # PC, tiene sentido que siga funcionando en cualquier modo).
                proc.gesture_wake_event.clear()
                print("[info] Activada por gesto (quiero hablarte)")
                proc.end_conversation_event.clear()
                audio_ducking.duck()
                voice.speak("Dime.")
                _run_conversation_turns(config, brain, gemini_brain_ai, local_brain_ai, voice, listener, lock, stop_event)
                audio_ducking.restore()
                continue

            if mode_state.is_remote_control():
                # El celular (botón de mantener presionado) es la entrada
                # principal en este modo — no hace falta detectar la palabra
                # clave en la PC. El único caso en que el micrófono de la PC
                # sigue vivo es mientras Rochy habla, y solo para poder
                # cortarla (ver CANCEL_PHRASES) — eso nunca se desactiva, sin
                # importar el modo.
                speaking_now = proc.speaking_event.is_set()
                ui_server.broadcast_state("speaking" if speaking_now else "idle")
                if speaking_now:
                    command_text = listener.listen(timeout=1.5, phrase_time_limit=3)
                    if command_text and _is_cancel(command_text):
                        print(f"Tú (voz): {command_text}")
                        ui_server.broadcast_transcript("user", command_text)
                        voice.stop_speaking()
                        proc.cancel_event.set()
                        ui_server.broadcast_transcript("assistant", "[interrumpido]")
                else:
                    time.sleep(0.3)
                continue

            ui_server.broadcast_state("idle")
            _wait_while_speaking(stop_event)
            heard = listener.listen(timeout=5, phrase_time_limit=4)
            if not heard:
                continue
            matched, matched_on = _sounds_like_wake_word(heard, config.wake_word)
            if not matched:
                # Antes esto era completamente silencioso — si el micrófono
                # oía algo pero no coincidía con la palabra clave, no quedaba
                # ni rastro para saber por qué (¿transcribió mal? ¿oyó otra
                # cosa?). Ahora queda registrado para poder diagnosticarlo.
                print(f"[info] Oí algo pero no coincide con la palabra clave '{config.wake_word}': {heard!r}")
                continue

            # Registra también las activaciones que SÍ pasaron — antes esto no
            # dejaba rastro alguno, así que una activación por parecido
            # fonético con ruido de fondo (ej. "hora" en vez de "hola", ya
            # corregido, pero puede volver a pasar con otra palabra) no se
            # podía ni diagnosticar: no había forma de saber qué la disparó.
            print(f"[info] Activada por la palabra clave (coincidió con {matched_on!r}): {heard!r}")
            # Por si quedó marcada de un "descansa" dicho por otro canal
            # mientras no había ninguna conversación por voz activa que la
            # consumiera — sin esto, esta conversación RECIÉN empezada se
            # cortaría sola en su primera vuelta por una señal que ya no
            # tiene nada que ver con ella.
            proc.end_conversation_event.clear()
            audio_ducking.duck()
            voice.speak("Dime.")
            _run_conversation_turns(config, brain, gemini_brain_ai, local_brain_ai, voice, listener, lock, stop_event)
            audio_ducking.restore()
        except Exception as exc:
            # cualquier fallo puntual (red, TTS, una herramienta) no debe matar
            # el hilo del asistente ni dejar la interfaz congelada — y siempre
            # se le avisa al usuario, nunca falla en silencio.
            _report_error(voice, exc)


def _text_loop(
    config, brain, gemini_brain_ai, local_brain_ai, voice, lock: threading.Lock, stop_event: threading.Event
) -> None:
    """Atiende los comandos escritos en la interfaz, en paralelo a la voz.
    Escribir no necesita palabra clave: es una acción explícita del usuario."""
    while not stop_event.is_set():
        text = ui_server.get_text_command(timeout=1.0)
        if text is None:
            continue
        if _handle_cancel_if_requested(text, voice, source="texto"):
            continue
        try:
            status = _handle_command(
                text, config, brain, gemini_brain_ai, local_brain_ai, voice, lock, stop_event, source="texto"
            )
            if status == "exit":
                stop_event.set()
        except Exception as exc:
            _report_error(voice, exc)


def _remote_audio_loop(
    config, brain, gemini_brain_ai, local_brain_ai, voice, listener, lock: threading.Lock, stop_event: threading.Event
) -> None:
    """Atiende el audio grabado desde el celular usado como micrófono remoto
    (ver ui_server.py/remote.html) — un botón de "mantén presionado para
    hablar" ahí, así que igual que escribir, esto tampoco necesita la
    palabra clave: apretar el botón YA es la acción explícita del usuario."""
    while not stop_event.is_set():
        item = ui_server.get_audio_command(timeout=1.0)
        if item is None:
            continue
        audio_bytes, mime = item
        text = listener.transcribe_bytes(audio_bytes, mime)
        if not text:
            continue
        if _handle_cancel_if_requested(text, voice, source="celular"):
            continue
        # Apretar el botón del celular ya es "quiero hablarte" explícito —
        # baja la música igual que la palabra clave o el gesto, mientras
        # dura esta orden puntual (el control remoto es de a un botón por
        # vez, no una conversación de micrófono abierto como la de voz).
        audio_ducking.duck()
        try:
            status = _handle_command(
                text, config, brain, gemini_brain_ai, local_brain_ai, voice, lock, stop_event, source="celular"
            )
            if status == "exit":
                stop_event.set()
        except Exception as exc:
            _report_error(voice, exc)
        finally:
            audio_ducking.restore()


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

    gemini_brain_ai = None
    if config.gemini_api_key:
        try:
            from gemini_brain import GeminiBrain

            gemini_brain_ai = GeminiBrain(config)
            print(f"Gemini ({config.gemini_model}) disponible como segundo respaldo si Groq falla.")
        except Exception as exc:
            print(f"No se pudo preparar Gemini: {exc}")

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
        target=_text_loop, args=(config, brain, gemini_brain_ai, local_brain_ai, voice, lock, stop_event), daemon=True
    )
    text_thread.start()

    remote_audio_thread = threading.Thread(
        target=_remote_audio_loop,
        args=(config, brain, gemini_brain_ai, local_brain_ai, voice, listener, lock, stop_event),
        daemon=True,
    )
    remote_audio_thread.start()

    _voice_loop(config, brain, gemini_brain_ai, local_brain_ai, voice, listener, lock, stop_event)

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
    lan_ip = ui_server.get_lan_ip()
    print(
        f"Micrófono remoto: abre https://{lan_ip}:{ui_server.REMOTE_PORT}/remote.html "
        f"desde el navegador de tu celular (misma red WiFi). El certificado es "
        f"autofirmado — el navegador va a avisar que no es seguro la primera vez, "
        f"elegí \"Avanzado\" / \"Continuar de todas formas\", es esperado."
    )
    # UI-ROCHY (otra carpeta/proyecto) es la interfaz de escritorio — se sirve
    # por HTTP local (ver ui_rochy_server.py) porque sus scripts son módulos
    # de JavaScript, que no cargan sobre file://.
    interface_url = ui_rochy_server.start()
    if interface_url is None:
        print("No se encontró la interfaz (UI-ROCHY) en esta PC. No se puede abrir la ventana.")
        return
    window = webview.create_window(
        assistant_name,
        interface_url,
        width=1080,
        height=820,
        background_color="#05060b",
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
