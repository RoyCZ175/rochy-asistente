"""Funciones seguras de control del sistema para el asistente.

Cada función expone una acción concreta y acotada (sin ejecutar comandos
arbitrarios) para que pueda ser invocada de forma segura desde la IA
mediante function calling.
"""

import json
import os
import subprocess
import urllib.parse
import webbrowser
from datetime import datetime

import keyboard as kb
import pyautogui

pyautogui.FAILSAFE = True  # mover el mouse a una esquina aborta cualquier acción en curso

APP_ALIASES = {
    "notepad": "notepad.exe",
    "bloc de notas": "notepad.exe",
    "calculator": "calc.exe",
    "calculadora": "calc.exe",
    "explorer": "explorer.exe",
    "explorador": "explorer.exe",
    "explorador de archivos": "explorer.exe",
    "file explorer": "explorer.exe",
    "paint": "mspaint.exe",
    "cmd": "cmd.exe",
    "consola": "cmd.exe",
    "terminal": "wt.exe",
    "powershell": "powershell.exe",
    "task manager": "taskmgr.exe",
    "administrador de tareas": "taskmgr.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "spotify": "spotify.exe",
    "camara": "microsoft.windows.camera:",
    "cámara": "microsoft.windows.camera:",
    "camera": "microsoft.windows.camera:",
    "configuracion": "ms-settings:",
    "configuración": "ms-settings:",
    "ajustes": "ms-settings:",
    "settings": "ms-settings:",
    "tienda": "ms-windows-store:",
    "store": "ms-windows-store:",
    "fotos": "ms-photos:",
    "photos": "ms-photos:",
    "correo": "outlookmail:",
    "mail": "outlookmail:",
    "reloj": "ms-clock:",
    "clock": "ms-clock:",
    "recorte": "ms-screenclip:",
    "snipping tool": "ms-screenclip:",
}


def _find_start_app(name: str):
    """Busca la app entre TODAS las instaladas (clásicas y de Microsoft Store)
    con el mismo catálogo que usa la Búsqueda de Windows, vía Get-StartApps."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        apps = json.loads(result.stdout)
    except Exception:
        return None

    if isinstance(apps, dict):
        apps = [apps]

    best = None
    for app in apps or []:
        app_name = (app.get("Name") or "").lower()
        if not app_name:
            continue
        if name == app_name:
            return app.get("AppID")
        if best is None and (name in app_name or app_name in name):
            best = app.get("AppID")
    return best


def open_app(app_name: str) -> str:
    key = app_name.strip().lower()
    exe = APP_ALIASES.get(key)
    if not exe:
        for alias, mapped in APP_ALIASES.items():
            if alias in key or key in alias:
                exe = mapped
                break

    if exe:
        try:
            os.startfile(exe)
            return f"Abriendo {app_name}."
        except OSError:
            pass  # el alias no sirvió en este PC (ej. la app es la versión de Store), seguimos buscando

    app_id = _find_start_app(key)
    if app_id:
        try:
            subprocess.Popen(["explorer.exe", f"shell:appsFolder\\{app_id}"])
            return f"Abriendo {app_name}."
        except OSError as exc:
            return f"No pude abrir {app_name}: {exc}"

    return f"No encontré '{app_name}' entre tus aplicaciones instaladas."


def web_search(query: str) -> str:
    url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
    webbrowser.open(url)
    return f"Buscando '{query}' en el navegador."


def get_time() -> str:
    now = datetime.now()
    return f"La hora actual es {now.strftime('%H:%M')}, del día {now.strftime('%d/%m/%Y')}."


def type_text(text: str) -> str:
    kb.write(text, delay=0.02)
    return "Texto escrito."


def press_key(key: str) -> str:
    kb.press_and_release(key)
    return f"Tecla {key} presionada."


def hotkey(keys) -> str:
    combo = "+".join(keys)
    kb.press_and_release(combo)
    return f"Combinación {combo} ejecutada."


def move_mouse(x: int, y: int) -> str:
    pyautogui.moveTo(x, y, duration=0.2)
    return f"Ratón movido a ({x}, {y})."


def click_mouse(button: str = "left", clicks: int = 1) -> str:
    pyautogui.click(button=button, clicks=clicks)
    return f"Clic {button} realizado."


def scroll(amount: int) -> str:
    pyautogui.scroll(amount)
    return "Scroll realizado."


def _volume_interface():
    from comtypes import CLSCTX_ALL
    from ctypes import cast, POINTER
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def set_volume(level: int) -> str:
    level = max(0, min(100, level))
    vol = _volume_interface()
    vol.SetMasterVolumeLevelScalar(level / 100, None)
    return f"Volumen ajustado al {level} por ciento."


def volume_step(direction: str, steps: int = 10) -> str:
    vol = _volume_interface()
    current = vol.GetMasterVolumeLevelScalar()
    delta = steps / 100 if direction == "up" else -steps / 100
    new_val = max(0.0, min(1.0, current + delta))
    vol.SetMasterVolumeLevelScalar(new_val, None)
    verb = "subido" if direction == "up" else "bajado"
    return f"Volumen {verb} al {round(new_val * 100)} por ciento."


def mute_toggle() -> str:
    vol = _volume_interface()
    muted = bool(vol.GetMute())
    vol.SetMute(not muted, None)
    return "Silenciado." if not muted else "Sonido activado."
