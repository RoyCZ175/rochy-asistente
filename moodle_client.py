"""Acceso de solo lectura a la plataforma Moodle de la universidad.

Reutiliza la sesión capturada por university_login.py (login manual, incluye
SSO/Google) y llama al mismo endpoint AJAX interno que usa el propio
JavaScript de Moodle para su Línea de tiempo — autenticado con la cookie de
sesión, sin necesitar usuario/contraseña ni un token de webservice (que no
aplica a cuentas con login por Google).

A propósito no existe ninguna función de escritura aquí (entregar, subir
archivos, etc.) — la IA no tiene forma de enviar nada en tu nombre.
"""

import json
import re
import time

import requests
from bs4 import BeautifulSoup

SESSION_PATH = "university_session.json"

_cookies = None
_sesskey = None


def invalidate_cache() -> None:
    """Olvida las cookies/sesskey cargadas en memoria — se llama después de
    un login nuevo (ver university_login.py) para que la próxima consulta
    relea la sesión recién guardada en vez de seguir usando la vieja."""
    global _cookies, _sesskey
    _cookies = None
    _sesskey = None


def _load_cookies() -> dict:
    global _cookies
    if _cookies is None:
        try:
            with open(SESSION_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            raise RuntimeError(
                "No hay sesión guardada de la plataforma universitaria. Corre university_login.py."
            )
        _cookies = {c["name"]: c["value"] for c in state.get("cookies", [])}
    return _cookies


def _get_sesskey(config) -> str:
    global _sesskey
    if _sesskey is not None:
        return _sesskey
    if not config.university_base_url:
        raise RuntimeError(
            "Falta UNIVERSITY_BASE_URL en tu .env. Corre university_login.py primero."
        )
    try:
        resp = requests.get(
            config.university_base_url.rstrip("/") + "/my/", cookies=_load_cookies(), timeout=15
        )
    except requests.exceptions.TooManyRedirects:
        # la sesión expiró y Moodle entra en un bucle intentando reautenticar
        # solo (ej. con Google SSO) sin poder completarlo
        raise RuntimeError(
            "Tu sesión de la plataforma universitaria expiró. Corre university_login.py de nuevo."
        )
    if "/login" in resp.url:
        raise RuntimeError(
            "Tu sesión de la plataforma universitaria expiró. Corre university_login.py de nuevo."
        )
    match = re.search(r'"sesskey":"([a-zA-Z0-9]+)"', resp.text)
    if not match:
        raise RuntimeError("No pude leer la clave de sesión de la plataforma.")
    _sesskey = match.group(1)
    return _sesskey


def _ajax_call(config, methodname: str, **args) -> dict:
    sesskey = _get_sesskey(config)
    payload = [{"index": 0, "methodname": methodname, "args": args}]
    resp = requests.post(
        config.university_base_url.rstrip("/") + "/lib/ajax/service.php",
        params={"sesskey": sesskey, "info": methodname},
        json=payload,
        cookies=_load_cookies(),
        timeout=15,
    )
    result = resp.json()[0]
    if result.get("error"):
        message = (result.get("exception") or {}).get("message", "Error de Moodle.")
        raise RuntimeError(message)
    return result["data"]


def _shorten(text: str, max_len: int = 180) -> str:
    """Recorta descripciones largas para el resumen de varias tareas juntas
    (hablar el enunciado completo de 10 tareas seguidas sería un muro de
    texto interminable por voz) — el enunciado completo sigue disponible
    pidiendo esa tarea puntual con get_task_detail."""
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"


def get_pending_tasks(config, limit: int = 10) -> str:
    """Replica la 'Línea de tiempo' del dashboard: próximas actividades con
    fecha de entrega, AHORA con un adelanto de la descripción de cada una
    (antes solo mostraba el título — que casi nunca dice de qué se trata de
    verdad, ej. "Tarea 3" o "Foro semana 5")."""
    data = _ajax_call(
        config,
        "core_calendar_get_action_events_by_timesort",
        limitnum=limit,
        timesortfrom=int(time.time()),
    )
    events = data.get("events", [])
    if not events:
        return "No tienes actividades pendientes próximas en la plataforma."

    lines = []
    for ev in events:
        course = (ev.get("course") or {}).get("fullname", "")
        due = time.strftime("%d/%m %H:%M", time.localtime(ev.get("timesort", 0)))
        name = ev.get("activityname") or ev.get("name")
        description = _shorten(_fetch_activity_description(ev.get("url")))
        lines.append(f"{name} ({course}) - {due}. {description}")
    return "Tus próximas entregas en la plataforma: " + "; ".join(lines) + "."


def get_task_detail(config, task_name: str) -> str:
    """Busca por nombre entre las próximas actividades y devuelve su enunciado."""
    data = _ajax_call(
        config,
        "core_calendar_get_action_events_by_timesort",
        limitnum=50,
        timesortfrom=int(time.time()) - 60 * 60 * 24 * 30,  # incluye vencidas recientes también
    )
    events = data.get("events", [])
    normalized = task_name.strip().lower()
    match = next(
        (ev for ev in events if normalized in (ev.get("activityname") or ev.get("name") or "").lower()),
        None,
    )
    if not match:
        return f"No encontré ninguna tarea llamada '{task_name}' en tu plataforma."

    course = (match.get("course") or {}).get("fullname", "")
    due = time.strftime("%d/%m/%Y %H:%M", time.localtime(match.get("timesort", 0)))
    name = match.get("activityname") or match.get("name")
    description = _fetch_activity_description(match.get("url"))
    return f"{name} ({course}), entrega {due}. {description}"


def _fetch_activity_description(url: str) -> str:
    if not url:
        return "No encontré un enlace directo a esta actividad."

    resp = requests.get(url, cookies=_load_cookies(), timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    intro = soup.select_one("#intro")
    if not intro:
        return "No encontré una descripción detallada en la plataforma."

    text = intro.get_text(" ", strip=True)
    if not text:
        return "No tiene descripción en texto, probablemente solo tiene un archivo adjunto en la plataforma."
    return f"Enunciado: {text}"
