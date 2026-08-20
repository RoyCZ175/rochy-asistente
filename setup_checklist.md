# Checklist de instalación y configuración

> **Atajo**: si ya tienes Python instalado, doble clic en `install.bat` hace los pasos 2-4
> automáticamente. Este checklist es la referencia manual, paso a paso.

## 1) Instalar Python
- Python 3.10 o superior (https://www.python.org/downloads/, marca "Add python.exe to PATH")
- Windows 10 o 11
- Micrófono y altavoces

## 2) Crear entorno virtual
```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

## 3) Instalar dependencias
```powershell
pip install -r requirements.txt
```
Si falla `PyAudio`:
```powershell
pip install pipwin
pipwin install pyaudio
```

## 4) Copiar variables de entorno
```powershell
copy .env.example .env
```

## 5) Obtener y rellenar tu clave de Groq
1. Crea una cuenta gratuita en https://console.groq.com/keys
2. Genera una API key
3. Pégala en `.env` como `GROQ_API_KEY=...`

## 6) Ejecutar el asistente
Doble clic en el acceso directo "Rochy" del Escritorio, o en `run_rochy_silent.vbs`
(sin consola) / `run_jarvis.bat` (con consola, útil para depurar), o manualmente:
```powershell
python voice_assistant.py
```
Se abre la ventana compacta de la app. Di tu palabra clave (por defecto "rochy") para activarlo,
o escríbele directo en el cuadro de texto.

## 7) Si el control de teclado/mouse no responde
Cierra la terminal y vuelve a abrirla **como administrador**: el módulo `keyboard`
necesita permisos elevados en Windows para enviar teclas a otras aplicaciones.

## 8) Personalización rápida (en `.env`)
- `WAKE_WORD`: cambia la palabra de activación (por defecto "rochy")
- `ASSISTANT_NAME`: nombre con el que se presenta
- `EDGE_TTS_VOICE`: otra voz, ejecuta `edge-tts --list-voices` para ver opciones en español
- `GROQ_MODEL`: modelo de chat (debe soportar function calling)

## 9) Modo offline (opcional pero recomendado)
- Voz y texto-a-voz locales ya vienen listos (Vosk + voces de Windows).
- Para conversación de IA real sin internet: instala Ollama (https://ollama.com/download)
  y corre `ollama pull llama3.2` una vez. Ver README para más detalle.

## 10) Correr los tests (no requieren micrófono ni clave de API)
```powershell
pip install pytest
pytest
```
