"""Cerebro conversacional: Groq + function calling sobre system_control."""

import concurrent.futures
import json

from groq import Groq

import code_generator as cg
import control_signal
import creation_log
import google_services as goog
import memory_store as mem
import moodle_client as moodle
import spotify_control as spot
import system_control as sc
import university_tutor as uni

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": "Abre una aplicación conocida en el PC.",
            "parameters": {
                "type": "object",
                "properties": {"app_name": {"type": "string"}},
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Busca algo en internet abriendo el navegador.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Obtiene la hora y fecha actual del sistema.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Fija el volumen del sistema a un porcentaje exacto (0-100).",
            "parameters": {
                "type": "object",
                "properties": {"level": {"type": "integer"}},
                "required": ["level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "volume_step",
            "description": "Sube o baja el volumen del sistema de forma relativa.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down"]},
                    "steps": {"type": "integer"},
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mute_toggle",
            "description": "Silencia o reactiva el sonido del sistema.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "type_text",
            "description": (
                "Escribe texto tecleándolo en la ventana que tenga el foco en ese momento. "
                "Úsala SOLO cuando el usuario pida explícitamente escribir/teclear/dictar algo en "
                "otra aplicación (ej. 'escribe esto en el bloc de notas'). NUNCA la uses para dar tu "
                "propia respuesta o explicación — eso siempre va hablado/en el chat, jamás tecleado."
            ),
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "press_key",
            "description": "Presiona una tecla individual (ej: enter, esc, tab, f5).",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hotkey",
            "description": "Ejecuta una combinación de teclas, ej: ['ctrl', 'c'].",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["keys"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_mouse",
            "description": "Mueve el cursor del mouse a una posición en pantalla.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "click_mouse",
            "description": "Hace clic con el mouse en la posición actual del cursor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "button": {"type": "string", "enum": ["left", "right", "middle"]},
                    "clicks": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "scroll",
            "description": "Desplaza la pantalla verticalmente (positivo=arriba, negativo=abajo).",
            "parameters": {
                "type": "object",
                "properties": {"amount": {"type": "integer"}},
                "required": ["amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_search",
            "description": "Busca una canción o artista en Spotify y dice qué encontró.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Canción o artista a buscar."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_play",
            "description": (
                "Reproduce música en Spotify. Si se da una canción/artista la busca y la pone; "
                "si no, reanuda la reproducción en pausa. Requiere Spotify abierto en algún dispositivo."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Canción o artista a buscar, opcional."}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_pause",
            "description": "Pausa la música de Spotify.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_next",
            "description": "Salta a la siguiente canción en Spotify.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_previous",
            "description": "Vuelve a la canción anterior en Spotify.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_current_track",
            "description": "Dice qué canción está sonando ahora mismo en Spotify.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spotify_set_volume",
            "description": "Fija el volumen de reproducción de Spotify a un porcentaje (0-100).",
            "parameters": {
                "type": "object",
                "properties": {"level": {"type": "integer"}},
                "required": ["level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "university_pending_tasks",
            "description": (
                "Lee de la plataforma universitaria (Moodle) las próximas actividades y tareas "
                "pendientes con su fecha de entrega. Solo lectura, nunca entrega nada."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "university_task_detail",
            "description": (
                "Lee el enunciado completo de una tarea específica de la plataforma universitaria "
                "por su nombre. Solo lectura, nunca entrega nada."
            ),
            "parameters": {
                "type": "object",
                "properties": {"task_name": {"type": "string"}},
                "required": ["task_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_create_event",
            "description": "Crea un evento real en el Google Calendar del usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Título del evento."},
                    "start_iso": {
                        "type": "string",
                        "description": "Fecha y hora de inicio en formato ISO 8601, ej: 2026-08-25T14:00:00-05:00.",
                    },
                    "end_iso": {"type": "string", "description": "Fecha y hora de fin en ISO 8601, opcional."},
                    "description": {"type": "string", "description": "Notas del evento, opcional."},
                },
                "required": ["summary", "start_iso"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calendar_list_events",
            "description": "Lee los próximos eventos del Google Calendar real del usuario.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_draft_email",
            "description": (
                "Prepara un correo (destinatario, asunto, mensaje) y devuelve el texto para "
                "leérselo al usuario y pedirle confirmación. NUNCA envía nada por sí sola."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Correo del destinatario."},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_send_email",
            "description": (
                "Envía el correo previamente preparado con gmail_draft_email. Úsala SOLO después de "
                "que el usuario haya confirmado explícitamente en un mensaje posterior (ej. dijo 'sí, envíalo')."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_cancel_email",
            "description": "Cancela el correo que estaba preparado, sin enviarlo.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gmail_list_recent",
            "description": "Lee los correos recientes de la bandeja de entrada de Gmail del usuario.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_deadline",
            "description": "Guarda una fecha de entrega universitaria en el calendario local del usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Nombre de la tarea o entrega."},
                    "due_date": {"type": "string", "description": "Fecha de entrega, como la diga el usuario."},
                    "course": {"type": "string", "description": "Materia o curso, opcional."},
                },
                "required": ["task", "due_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_deadlines",
            "description": "Lee todas las entregas universitarias pendientes guardadas.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_deadline",
            "description": "Elimina una entrega del calendario, normalmente porque ya se completó.",
            "parameters": {
                "type": "object",
                "properties": {"task": {"type": "string"}},
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember_fact",
            "description": (
                "Guarda de forma permanente un dato sobre el usuario (nombre, preferencia, "
                "proyecto en curso, etc.) para recordarlo en futuras conversaciones."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Nombre corto del dato, ej: 'nombre'."},
                    "value": {"type": "string", "description": "El dato en sí."},
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget_fact",
            "description": "Elimina un dato guardado previamente sobre el usuario.",
            "parameters": {
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_folder",
            "description": "Crea una carpeta real en Documentos, Escritorio o Descargas del usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre de la carpeta."},
                    "location": {
                        "type": "string",
                        "description": "Dónde crearla: documentos, escritorio o descargas. Por defecto documentos.",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_document",
            "description": (
                "Escribe un documento de texto real (cuento, carta, ensayo, resumen, lo que sea) y lo "
                "guarda y abre de verdad en el PC. Úsala para cualquier pedido de 'escribe/redacta X y "
                "guárdalo' — NUNCA digas que ya lo escribiste/guardaste sin llamar a esta herramienta."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Qué debe decir el documento."},
                    "name": {"type": "string", "description": "Nombre corto del archivo (sin extensión)."},
                    "location": {
                        "type": "string",
                        "description": "Dónde guardarlo: documentos, escritorio o descargas. Por defecto documentos.",
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_folder",
            "description": "Abre el explorador de archivos directo en Documentos, Escritorio o Descargas del usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "documentos, escritorio, descargas o proyectos. Por defecto documentos.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "Lee qué archivos y carpetas hay de verdad en Documentos, Escritorio o Descargas del "
                "usuario — úsala para confirmar si algo existe en vez de asumir."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "documentos, escritorio, descargas o proyectos. Por defecto documentos.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_creations",
            "description": (
                "Lista lo más reciente que TÚ creaste con create_folder/create_document/create_webpage/"
                "create_script (nunca archivos que el usuario ya tenía de antes). Úsala si no estás "
                "seguro de qué fue lo último que creaste antes de borrar algo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Cuántas mostrar. Por defecto 5."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_recent_creations",
            "description": (
                "Borra de verdad las N cosas más recientes que TÚ creaste con create_folder/"
                "create_document/create_webpage/create_script — NUNCA archivos que el usuario ya tenía "
                "de antes, y NUNCA nada del modo estudio (eso se maneja aparte). Ej.: 'bórrame las dos "
                "últimas carpetas que creaste' -> count=2, kind='folder'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "Cuántas borrar, empezando por lo más reciente."},
                    "kind": {
                        "type": "string",
                        "enum": ["folder", "document", "webpage", "script"],
                        "description": "Opcional: solo borrar este tipo. Si no se da, borra las N más recientes de cualquier tipo.",
                    },
                },
                "required": ["count"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_webpage",
            "description": (
                "Genera y guarda en disco una página web real (HTML/CSS/JS) según la "
                "descripción del usuario, y la abre en el navegador."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Qué debe tener la página."},
                    "name": {"type": "string", "description": "Nombre corto del proyecto (será el nombre de la carpeta)."},
                    "location": {
                        "type": "string",
                        "description": (
                            "Dónde crear la carpeta del proyecto: documentos, escritorio, descargas, "
                            "o proyectos (carpeta interna del asistente). Por defecto proyectos."
                        ),
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_script",
            "description": "Genera y guarda en disco un script o programa según la descripción del usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Qué debe hacer el script."},
                    "name": {"type": "string", "description": "Nombre corto del proyecto (será el nombre de la carpeta)."},
                    "language": {
                        "type": "string",
                        "description": "Lenguaje: python, javascript, batch, powershell, java, c#.",
                    },
                    "location": {
                        "type": "string",
                        "description": (
                            "Dónde crear la carpeta del proyecto: documentos, escritorio, descargas, "
                            "o proyectos (carpeta interna del asistente). Por defecto proyectos."
                        ),
                    },
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "end_session",
            "description": (
                "Respaldo semántico: el sistema ya revisó frases comunes de pausar/apagar antes de "
                "llamarte, así que si ves esta herramienta disponible es porque ninguna coincidió. "
                "Úsala SOLO si, por el sentido COMPLETO de lo que dijo el usuario, está claro que quiere "
                "que dejes de escuchar activamente (mode=pause) o que cierres la aplicación entera "
                "(mode=exit) — aunque no haya usado una palabra clave exacta (ej. 'ya no te necesito por "
                "ahora' = pause, 'cierra el programa' = exit). Si hay CUALQUIER duda de que sea eso lo "
                "que pide, NO la uses, solo conversa."
            ),
            "parameters": {
                "type": "object",
                "properties": {"mode": {"type": "string", "enum": ["pause", "exit"]}},
                "required": ["mode"],
            },
        },
    },
]

# Estas herramientas SIEMPRE llaman a Groq (la nube) para generar el contenido,
# sin importar qué modelo esté "conversando" — no tiene sentido ofrecérselas al
# cerebro local: rompería la promesa de "modo local forzado" (nada de nube) y,
# peor, un modelo pequeño tiende a fabricar una respuesta falsa de éxito en vez
# de intentar llamarlas (ej. "el cuento se ha guardado" sin haber creado nada).
CLOUD_ONLY_TOOLS = {"create_document", "create_webpage", "create_script"}
LOCAL_TOOLS = [t for t in TOOLS if t["function"]["name"] not in CLOUD_ONLY_TOOLS]

# Herramientas cuyo resultado se habla tal cual, sin dejar que el modelo lo reformule
# (evita que "reinterprete" una pregunta de confirmación de seguridad).
VERBATIM_TOOLS = {"gmail_draft_email"}

# Herramientas que teclean literalmente en la ventana con foco. Los modelos (sobre
# todo los locales, más pequeños) a veces las usan para "escribir" su propia
# respuesta en vez de solo contestar — de código, exigimos que el último mensaje
# del usuario contenga una palabra que indique que de verdad pidió escribir algo.
TYPING_TOOLS = {"type_text", "press_key", "hotkey"}
TYPING_INTENT_KEYWORDS = (
    "escrib", "teclea", "dicta", "redacta", "anota", "presiona", "combinacion", "combinación", "atajo",
)


def _last_user_message(history) -> str:
    for msg in reversed(history):
        if msg.get("role") == "user":
            return (msg.get("content") or "").lower()
    return ""


def _typing_intent_present(history) -> bool:
    text = _last_user_message(history)
    return any(k in text for k in TYPING_INTENT_KEYWORDS)

# Máximo de rondas de llamadas a herramientas encadenadas por cada petición del usuario.
MAX_TOOL_ROUNDS = 5

# Ninguna herramienta puede bloquear la app más de esto (ej. una autorización
# de Spotify/Google que nunca se completa) — pasado este tiempo se da por
# cancelada y se le avisa al usuario, en vez de congelarse para siempre.
TOOL_TIMEOUT_SECONDS = 45
_tool_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")

SYSTEM_PROMPT = """Eres {name}, un asistente de voz personal estilo Jarvis de Iron Man, y hablas en español.
Responde siempre de forma breve, natural y hablada (1 a 3 frases), sin listas ni markdown, como en una llamada real.
La palabra clave configurada para activarte por voz (la que hay que decir antes de darte una orden) es
"{wake_word}" — NO es necesariamente tu nombre. Si te preguntan qué decir para activarte, di exactamente
esa palabra, nunca inventes ni asumas que es tu propio nombre.
Tienes herramientas para controlar el PC del usuario: abrir apps, buscar en la web, controlar volumen, teclado y mouse.
También puedes controlar la música de Spotify (spotify_search/play/pause/next/previous/current_track/set_volume;
si no hay dispositivo activo, dile al usuario que abra Spotify primero).
Además puedes recordar datos permanentes sobre el usuario (remember_fact/forget_fact), crear
carpetas reales (create_folder), escribir documentos de texto reales (create_document — cuentos,
cartas, ensayos), abrir el explorador en una carpeta concreta (open_folder) y ver qué archivos hay
de verdad (list_files) — todo esto solo dentro de Documentos, Escritorio, Descargas o la carpeta
interna del asistente, nunca en rutas arbitrarias del sistema. También puedes crear programas o
páginas web reales (create_webpage/create_script).
Si el usuario está en "modo estudio" con una materia activa, create_folder/create_document/
create_webpage/create_script ignoran automáticamente la ubicación pedida y crean todo dentro de la
carpeta fija de esa materia — no necesitas preguntarle dónde guardarlo en ese caso.
Puedes deshacer tus propias creaciones recientes con delete_recent_creations (ej. "bórrame las dos
últimas carpetas que creaste" -> count=2, kind="folder") y consultar qué creaste con
list_recent_creations si no estás seguro. Estas dos SOLO afectan cosas creadas con create_folder/
create_document/create_webpage/create_script — nunca el modo estudio ni archivos que el usuario ya
tenía de antes.
REGLA CRÍTICA: NUNCA digas que creaste, escribiste, guardaste o abriste un archivo si no llamaste
a la herramienta correspondiente de verdad — no existe ninguna otra forma de crear archivos. Si el
usuario pide guardar algo en un lugar que no reconoces claramente como Documentos/Escritorio/
Descargas (ej. el micrófono transcribió mal el nombre), pregúntale a cuál de esas tres se refería
en vez de inventar una ubicación.
Usa una herramienta solo cuando el usuario pida una acción concreta; para charla normal, simplemente conversa.
Cuando el usuario te cuente algo relevante y duradero sobre sí mismo (su nombre, una preferencia, un proyecto en
curso), guárdalo con remember_fact sin que tenga que pedírtelo explícitamente.
IMPORTANTE: type_text/press_key/hotkey teclean literalmente en la ventana que tenga el foco en ese momento
(puede ser cualquier cosa: el navegador, un documento, lo que sea). Úsalas SOLO cuando el usuario pida
explícitamente escribir o teclear algo en otra aplicación. Tu propia respuesta, explicación o charla NUNCA
se teclea — siempre va hablada o en el chat.

Modo tutor universitario: cuando el usuario hable de tareas, exámenes o entregas de la universidad, actúa
estrictamente como TUTOR, nunca como quien hace el trabajo:
- Puedes usar university_pending_tasks para ver qué tiene pendiente en la plataforma, y university_task_detail
  para leer el enunciado completo de una tarea concreta. Son de solo lectura: no existe ninguna herramienta
  para entregar ni enviar nada en su plataforma, ni la vas a inventar.
- Con el enunciado ya leído, puedes explicarlo, dar ejemplos paso a paso y aclarar conceptos.
- Puedes usar add_deadline/list_deadlines/remove_deadline para ayudarle a organizar sus fechas de entrega.
- Puedes sugerir por dónde empezar o qué pasos seguir.
- NUNCA le des la solución completa y lista para entregar (un ensayo terminado, código completo de una tarea,
  respuestas finales de un examen). Guíalo con preguntas y pistas para que el trabajo final lo haga él.

También tienes acceso al Google Calendar y Gmail reales del usuario:
- calendar_create_event / calendar_list_events: puedes usarlas libremente, crear o consultar eventos no es
  una acción peligrosa.
- Para correos, el envío es SIEMPRE un proceso de dos pasos, sin excepción:
  1) gmail_draft_email prepara el mensaje y te da un texto para leérselo al usuario pidiendo confirmación.
  2) SOLO llamas a gmail_send_email si el usuario respondió afirmativamente de forma explícita en un
     mensaje posterior (ej. "sí, envíalo", "confirmado"). Si dice que no, o cambia de tema, usa
     gmail_cancel_email en vez de enviarlo.
  NUNCA llames a gmail_draft_email y gmail_send_email en el mismo turno, y NUNCA envíes un correo que el
  usuario no te haya pedido explícitamente y confirmado.
Sé leal, servicial y con un toque de humor seco, igual que Jarvis.{memory_context}"""


def build_tool_functions(config) -> dict:
    """Construye el mapa nombre-de-herramienta -> función real. Se comparte
    entre el cerebro en la nube (AIBrain) y el local (LocalAIBrain, en
    local_ai_brain.py) para no duplicar esta lista en dos lugares."""
    return {
        "open_app": lambda args: sc.open_app(args["app_name"]),
        "web_search": lambda args: sc.web_search(args["query"]),
        "get_time": lambda args: sc.get_time(),
        "set_volume": lambda args: sc.set_volume(args["level"]),
        "volume_step": lambda args: sc.volume_step(args["direction"], args.get("steps", 10)),
        "mute_toggle": lambda args: sc.mute_toggle(),
        "type_text": lambda args: sc.type_text(args["text"]),
        "press_key": lambda args: sc.press_key(args["key"]),
        "hotkey": lambda args: sc.hotkey(args["keys"]),
        "move_mouse": lambda args: sc.move_mouse(args["x"], args["y"]),
        "click_mouse": lambda args: sc.click_mouse(args.get("button", "left"), args.get("clicks", 1)),
        "scroll": lambda args: sc.scroll(args["amount"]),
        "spotify_search": lambda args: spot.search(config, args["query"]),
        "spotify_play": lambda args: spot.play(config, args.get("query", "")),
        "spotify_pause": lambda args: spot.pause(config),
        "spotify_next": lambda args: spot.next_track(config),
        "spotify_previous": lambda args: spot.previous_track(config),
        "spotify_current_track": lambda args: spot.current_track(config),
        "spotify_set_volume": lambda args: spot.set_volume(config, args["level"]),
        "university_pending_tasks": lambda args: moodle.get_pending_tasks(config),
        "university_task_detail": lambda args: moodle.get_task_detail(config, args["task_name"]),
        "calendar_create_event": lambda args: goog.create_event(
            config, args["summary"], args["start_iso"], args.get("end_iso", ""), args.get("description", "")
        ),
        "calendar_list_events": lambda args: goog.list_upcoming_events(config),
        "gmail_draft_email": lambda args: goog.draft_email(args["to"], args["subject"], args["body"]),
        "gmail_send_email": lambda args: goog.send_email(config),
        "gmail_cancel_email": lambda args: goog.cancel_email(),
        "gmail_list_recent": lambda args: goog.list_recent_emails(config),
        "add_deadline": lambda args: uni.add_deadline(
            args["task"], args["due_date"], args.get("course", "")
        ),
        "list_deadlines": lambda args: uni.list_deadlines(),
        "remove_deadline": lambda args: uni.remove_deadline(args["task"]),
        "remember_fact": lambda args: mem.remember(args["key"], args["value"]),
        "forget_fact": lambda args: mem.forget(args["key"]),
        "create_folder": lambda args: cg.create_folder(args["name"], args.get("location", "documentos")),
        "create_document": lambda args: cg.create_document(
            config, args["description"], args.get("name", "documento"), args.get("location", "documentos")
        ),
        "open_folder": lambda args: cg.open_folder(args.get("location", "documentos")),
        "list_files": lambda args: cg.list_files(args.get("location", "documentos")),
        "list_recent_creations": lambda args: creation_log.list_recent_text(args.get("count", 5)),
        "delete_recent_creations": lambda args: creation_log.delete_recent(args["count"], args.get("kind")),
        "create_webpage": lambda args: cg.create_webpage(
            config, args["description"], args.get("name", "mi_pagina"), args.get("location", "proyectos")
        ),
        "create_script": lambda args: cg.create_script(
            config,
            args["description"],
            args.get("name", "mi_script"),
            args.get("language", "python"),
            args.get("location", "proyectos"),
        ),
        "end_session": lambda args: _end_session(args.get("mode", "pause")),
    }


def _end_session(mode: str) -> str:
    mode = "exit" if mode == "exit" else "pause"
    control_signal.request(mode)
    return "Entendido, cerrando la aplicación." if mode == "exit" else "Entendido, dejo de escuchar activamente."


class AIBrain:
    def __init__(self, config):
        self.client = Groq(api_key=config.groq_api_key)
        self.model = config.groq_model
        self.max_turns = 12
        self.functions = build_tool_functions(config)
        self._system_content = SYSTEM_PROMPT.format(
            name=config.assistant_name, wake_word=config.wake_word, memory_context=mem.as_prompt_context()
        )
        self.history = [{"role": "system", "content": self._system_content}]

    def reset(self) -> None:
        """Limpia la conversación y empieza de cero. Vía de escape si el modelo
        se queda 'atascado' repitiendo algo (ej. sigue negándose a cosas
        normales después de rechazar un pedido anterior) — sin reiniciar la app."""
        self.history = [{"role": "system", "content": self._system_content}]

    def ask(self, user_text: str, cancel_event=None) -> str:
        self.history.append({"role": "user", "content": user_text})
        self._trim_history()

        # Bucle real de herramientas: algunas peticiones necesitan varios pasos
        # encadenados (ej. "crea una carpeta y dentro una página web"), donde el
        # segundo paso depende del resultado del primero. Seguimos llamando al
        # modelo CON las tools disponibles hasta que responda solo con texto.
        for _ in range(MAX_TOOL_ROUNDS):
            # Si el usuario canceló (dijo "olvídalo" u otra orden nueva) mientras
            # esperábamos, no tiene sentido seguir encadenando rondas ni gastar
            # otra llamada a la IA por una respuesta que ya nadie va a escuchar.
            if cancel_event is not None and cancel_event.is_set():
                return None
            response = self.client.chat.completions.create(
                model=self.model,
                messages=self.history,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.6,
                max_tokens=600,
                reasoning_effort="medium",
            )
            if cancel_event is not None and cancel_event.is_set():
                return None
            message = response.choices[0].message

            if not message.tool_calls:
                final_text = message.content or ""
                self.history.append({"role": "assistant", "content": final_text})
                return final_text

            self.history.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            )
            verbatim_result = None
            for call in message.tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                func = self.functions.get(name)
                if not func:
                    result = f"Herramienta desconocida: {name}"
                elif name in TYPING_TOOLS and not _typing_intent_present(self.history):
                    result = "No hice eso: no pediste explícitamente escribir o teclear algo en otra aplicación."
                else:
                    try:
                        future = _tool_executor.submit(func, args)
                        result = future.result(timeout=TOOL_TIMEOUT_SECONDS)
                    except concurrent.futures.TimeoutError:
                        result = (
                            f"Cancelé '{name}' porque tardó demasiado (más de "
                            f"{TOOL_TIMEOUT_SECONDS} segundos) sin responder."
                        )
                    except Exception as exc:
                        result = f"No se pudo ejecutar {name}: {exc}"

                if name in VERBATIM_TOOLS:
                    verbatim_result = str(result)

                self.history.append(
                    {"role": "tool", "tool_call_id": call.id, "name": name, "content": str(result)}
                )

            if verbatim_result is not None:
                # Para respuestas de seguridad crítica (ej. pedir confirmación antes de enviar
                # un correo) devolvemos el texto exacto de la herramienta, sin dejar que el
                # modelo lo reformule — con temperature > 0 a veces "contesta" la pregunta en
                # vez de repetirla. Tampoco seguimos encadenando tools después de esto.
                self.history.append({"role": "assistant", "content": verbatim_result})
                return verbatim_result

            # si no fue una tool verbatim, seguimos el bucle: el modelo puede querer
            # encadenar otra herramienta más antes de responder con texto final.

        final_text = "Hice varias acciones seguidas, pero me quedé sin poder resumirlo. ¿Revisamos si quedó bien?"
        self.history.append({"role": "assistant", "content": final_text})
        return final_text

    def _trim_history(self) -> None:
        limit = self.max_turns * 2 + 1
        if len(self.history) > limit:
            self.history = [self.history[0]] + self.history[-(limit - 1):]
