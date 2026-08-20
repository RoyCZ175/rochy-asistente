@echo off
cd /d "%~dp0"

if not exist .venv (
    echo No se encontro el entorno virtual. Ejecuta install.bat primero.
    pause
    exit /b 1
)

if not exist .env (
    echo No se encontro el archivo .env. Ejecuta install.bat primero y configura tu GROQ_API_KEY.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
python voice_assistant.py
pause
