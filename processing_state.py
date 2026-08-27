"""Estado compartido para poder cancelar una petición mientras se está
procesando (la IA + herramientas puede tardar, o incluso colgarse con algo
como Spotify) sin tener que esperar a que termine.

Gracias a esto el micrófono/texto pueden seguir escuchando mientras Rochy
"piensa", y decir una frase de cancelación (o directamente otra orden)
abandona lo que estaba en curso en vez de quedarse atrapado esperándolo."""

import threading
import time

# Puesto mientras hay una petición (charla/tarea con IA) en curso.
busy_event = threading.Event()

# Puesto para pedir que la petición en curso se abandone en cuanto sea
# posible. Cada nueva petición lo limpia justo antes de empezar, así que
# solo afecta a la que estaba corriendo cuando se puso.
cancel_event = threading.Event()

# Puesto mientras VoiceOutput.speak() está reproduciendo audio (ver tts.py).
# Si el micrófono sigue escuchando mientras suena la propia voz de Rochy por
# los parlantes (en vez de auriculares), puede captarse a sí misma como si
# fuera una orden nueva del usuario y quedar en un bucle de retroalimentación
# (esto pasó de verdad: "Abriendo explorer" hablado se escuchó a sí mismo y
# volvió a abrir explorer una y otra vez). Mientras esto esté activo, el
# bucle de voz pausa el reconocimiento en vez de procesar lo que capte.
speaking_event = threading.Event()

# Último texto que de verdad salió por los parlantes (ver tts.py). Sin
# auriculares, el eco físico del parlante puede colarse en el micrófono
# incluso DESPUÉS de que speaking_event ya se limpió (el sonido tarda un
# instante en apagarse del todo en el cuarto) — esto pasó de verdad: Rochy
# dijo la hora y se "escuchó" a sí misma diciéndola de nuevo como si fuera
# el usuario. Comparar lo recién oído contra esto permite detectar y
# descartar ese eco aunque ya no esté marcada como "hablando".
last_spoken_text = ""

# Marca de tiempo (time.time()) de la última vez que speaking_event se
# limpió — ver tts.py. Sirve para dar un ratito extra de "modo cancelación
# solamente" justo después de hablar (ver POST_SPEECH_GRACE_SECONDS en
# voice_assistant.py): el eco físico del parlante puede seguir sonando en el
# cuarto un instante después de que el estado ya diga "no está hablando".
speech_ended_at = 0.0
