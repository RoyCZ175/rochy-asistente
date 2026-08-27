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
