# Rochy — asistente personal tipo Iron Man

Asistente conversacional para Windows que:
- te escucha en segundo plano y se activa al oír la palabra clave (configurable, `WAKE_WORD` en `.env`),
- también acepta **texto escrito** en la propia interfaz, para cuando el reconocimiento de voz falla,
- entiende lo que dices (Groq Whisper) y piensa con una IA conversacional (Groq, con function calling),
- te contesta hablando con una voz neuronal (Microsoft Edge TTS, gratis),
- controla tu PC: abre aplicaciones, busca en la web, sube/baja volumen, mueve el mouse, hace clic, escribe texto y simula teclas,
- responde al instante y sin usar la IA para cosas básicas (saludos, hora, día, chistes, matemáticas simples),
- recuerda datos sobre ti entre sesiones (tu nombre, preferencias, proyectos en curso),
- crea programas reales por voz o texto: le pides una página web o un script y los genera y guarda en `proyectos/`,
- lee tus tareas pendientes de tu plataforma universitaria (Moodle) en modo tutor de solo lectura —
  explica, sugiere, organiza fechas, pero nunca hace el trabajo por ti,
- controla Spotify (buscar, reproducir, pausar, volumen) y tu Google Calendar / Gmail real
  (enviar correo siempre pide confirmación hablada antes de mandarlo),
- tiene una interfaz compacta tipo widget de asistente (no una ventana grande): un orbe animado que
  reacciona a si está en espera, escuchando, pensando o hablando, más el historial de la conversación,
- corre como una app de escritorio real (ventana nativa, no una pestaña del navegador), con
  acceso directo en el Escritorio para abrirla con doble clic,
- **funciona sin internet**: si detecta que no hay conexión, cambia solo a voz local (Vosk),
  texto a voz local (voces de Windows) e IA local (Ollama) — más simple que la versión en la
  nube, pero sigue respondiendo.

## Modo offline (sin internet)

Rochy detecta la conexión automáticamente y cambia de servicios en la nube a locales sin que
tengas que hacer nada. Para que el modo local funcione de verdad, necesitas dejarlo preparado
una vez, con internet:

1. **Voz → texto local**: ya viene listo (modelo Vosk en `vosk_model_es/`, se descarga durante
   la instalación — ver más abajo).
2. **Texto → voz local**: usa las voces de Windows ya instaladas en tu PC (no requiere nada extra,
   aunque suena más robótica que Edge TTS).
3. **IA conversacional local**: instala Ollama (https://ollama.com/download) y corre una vez:
   ```powershell
   ollama pull llama3.2
   ```
   Sin esto, sin internet Rochy solo puede ayudarte con comandos básicos (hora, abrir apps,
   chistes, matemáticas, recordar cosas) — sin conversación de IA real.

Con internet, siempre usa las versiones en la nube (mejor calidad); sin internet, cae automático
a las locales.

## Requisitos

- Python 3.10 o superior
- Windows 10 u 11
- Micrófono y altavoces
- Una clave gratuita de Groq: https://console.groq.com/keys

## Instalación

Doble clic en **`install.bat`**. Crea el entorno virtual, instala todas las dependencias
y genera tu archivo `.env`. Solo falta que lo abras y pegues tu `GROQ_API_KEY`.

Alternativa manual:
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

> **PyAudio en Windows**: si la instalación falla al compilar `PyAudio`, instala un wheel
> precompilado con `pip install pipwin && pipwin install pyaudio`.

## Ejecutar

Doble clic en el acceso directo del Escritorio (o en `run_jarvis.bat`).

Alternativa manual:
```powershell
.\.venv\Scripts\activate
python voice_assistant.py
```

Se abre una ventana pequeña tipo widget con un orbe animado. Di tu palabra clave (por defecto
"Rochy", configurable en `.env`) una vez para activarlo y, cuando responda "Dime.", empieza a
hablar con naturalidad. **También puedes escribirle** directamente en el cuadro de texto de abajo
en cualquier momento, sin necesitar la palabra clave — útil si el micrófono no te entiende bien.

**Modo conversación por voz**: no hace falta repetir la palabra clave en cada frase — una vez
activado se queda escuchando turno tras turno, como una charla normal. Vuelve a modo espera
(necesita la palabra clave de nuevo) solo si:
- te quedas 30 segundos en silencio, o
- dices "gracias" / "eso es todo" / **"descansa"** para pausar la escucha activa (la app sigue
  abierta, solo deja de estar en modo conversación).

Di **"adiós"** / **"apágate"** / "salir" (por voz o escrito) para cerrar la app por completo —
distinto de "descansa", que solo pausa.

## Ejemplos de comandos (voz o texto, igual de válidos)

- "qué hora es" / "abre el bloc de notas" / "busca en internet las noticias de hoy"
- "sube el volumen" / "silencia el sonido"
- "mueve el mouse a la posición 500, 300 y haz clic" / "escribe hola mundo"
- "cuéntame un chiste" / "cuánto es 45 más 30" (respuesta local, sin IA)
- "recuerda que mi color favorito es el azul" (memoria persistente)
- "necesito una página web para un restaurante de comida italiana" (crea `index.html` y lo abre)
- "créame un script en Python que renombre archivos de una carpeta"
- "escríbeme un cuento corto y guárdalo en documentos" (crea un .txt real y lo abre)
- "abre la carpeta de descargas" / "qué archivos hay en documentos" (funciona aunque tu
  Explorador esté en inglés — reconoce "documentos/escritorio/descargas" en español)
- "qué tareas tengo pendientes en la universidad" (lee tu plataforma, solo lectura)
- "explícame de qué se trata el Proyecto Final" (modo tutor, nunca resuelve por ti)
- "busca la canción Bohemian Rhapsody en Spotify"
- "qué tengo en mi calendario" / "agenda una reunión mañana a las 3pm"
- "mándale un correo a X diciendo Y" (pide confirmación hablada antes de enviarlo de verdad)
- "adiós" (para salir)

## Cómo funciona

- `stt.py`: captura audio del micrófono (`speech_recognition`) y lo transcribe con Whisper (Groq).
- `tts.py`: convierte el texto de respuesta en audio con Edge TTS y lo reproduce con `pygame`.
- `local_brain.py`: responde al instante, sin IA, a consultas básicas.
- `memory_store.py`: guarda datos sobre ti en `user_memory.json`, inyectados en el prompt en cada sesión.
- `code_generator.py`: genera páginas web y scripts con la IA, guardados en `proyectos/<nombre>/`.
- `moodle_client.py` + `university_login.py`: acceso de solo lectura a la plataforma universitaria,
  reutilizando una sesión de navegador capturada manualmente (soporta login con Google/SSO).
- `spotify_control.py` / `google_services.py`: búsqueda y control de Spotify, y Google Calendar/Gmail
  reales vía OAuth. El envío de correo es siempre un proceso de dos pasos con confirmación hablada.
- `ai_brain.py`: mantiene la conversación con el modelo de Groq y usa *function calling* para decidir
  cuándo ejecutar una acción real, recordar algo o generar código.
- `system_control.py`: funciones concretas y acotadas de control del sistema. No ejecuta comandos
  de shell arbitrarios.
- `ui_server.py` + `interface/index.html`: servidor WebSocket local (`ws://localhost:8765`) que
  transmite el estado (`idle`/`listening`/`thinking`/`speaking`) y el transcript a la interfaz, y
  recibe de vuelta los comandos escritos en el cuadro de texto.
- `voice_assistant.py`: `run()` abre la ventana nativa compacta (`pywebview`) en el hilo principal;
  `_assistant_loop` arranca dos canales de entrada en paralelo — voz (con palabra clave) y texto
  (sin necesitarla) — que comparten el mismo procesamiento de comandos (`_handle_command`).
- `install.bat` / `run_jarvis.bat`: instalador y lanzador de doble clic; el acceso directo del
  Escritorio apunta a `run_jarvis.bat`.

## Notas de seguridad

- El control de teclado/mouse está limitado a un conjunto fijo de funciones. El asistente **no**
  puede ejecutar comandos arbitrarios del sistema.
- `pyautogui.FAILSAFE` está activo: mover el mouse a cualquier esquina de la pantalla aborta
  la acción en curso.
- El módulo `keyboard` a veces requiere ejecutar la terminal **como administrador** en Windows.
- El asistente solo procesa audio como comando cuando detecta la palabra clave; el resto del
  tiempo descarta la transcripción localmente. El texto escrito, al ser una acción explícita del
  usuario, no necesita palabra clave.
- Enviar un correo con Gmail siempre requiere que el usuario confirme explícitamente en un mensaje
  posterior — nunca se manda nada en el mismo turno en que se redacta.
- El acceso a la plataforma universitaria y a Google es de solo lectura salvo por la creación de
  eventos de calendario y el envío de correo (con confirmación); no existe ninguna función para
  entregar tareas ni modificar tu plataforma universitaria.
