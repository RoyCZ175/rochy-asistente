@echo off
cd /d "%~dp0"

echo Creando entorno virtual...
python -m venv .venv

call .venv\Scripts\activate.bat

echo Instalando dependencias...
pip install --upgrade pip
pip install -r requirements.txt

if not exist .env (
    copy .env.example .env
    echo.
    echo Se creo el archivo .env
    echo Abrelo y pega tu GROQ_API_KEY de https://console.groq.com/keys antes de ejecutar Jarvis.
)

echo.
echo Listo. Usa run_jarvis.bat para iniciar la app.
pause
