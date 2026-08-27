"""Estado compartido para poder cancelar una petición mientras se está
procesando (la IA + herramientas puede tardar, o incluso colgarse con algo
como Spotify) sin tener que esperar a que termine.

Gracias a esto el micrófono/texto pueden seguir escuchando mientras Rochy
"piensa", y decir una frase de cancelación (o directamente otra orden)
abandona lo que estaba en curso en vez de quedarse atrapado esperándolo."""

import threading

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
