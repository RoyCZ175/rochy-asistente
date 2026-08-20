"""Creación de carpetas y programas por voz: el asistente escribe archivos y
carpetas reales, pero SOLO dentro de un conjunto fijo de ubicaciones seguras
(la carpeta proyectos/ del propio asistente, o Documentos/Escritorio/Descargas
del usuario) — nunca en una ruta arbitraria del sistema."""

import os
import re
import webbrowser

from groq import Groq

PROJECTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proyectos")

HOME = os.path.expanduser("~")
BASE_LOCATIONS = {
    "proyectos": PROJECTS_DIR,
    "documentos": os.path.join(HOME, "Documents"),
    "documents": os.path.join(HOME, "Documents"),
    "escritorio": os.path.join(HOME, "Desktop"),
    "desktop": os.path.join(HOME, "Desktop"),
    "descargas": os.path.join(HOME, "Downloads"),
    "downloads": os.path.join(HOME, "Downloads"),
}

CODE_SYSTEM_PROMPT = (
    "Eres un generador de código experto. Genera SOLO el código completo, funcional y "
    "bien estructurado que se te pide. No incluyas explicaciones ni bloques de markdown "
    "(```), solo el código puro, listo para guardarse directamente en un archivo."
)

LANGUAGE_EXTENSIONS = {
    "python": "py",
    "javascript": "js",
    "batch": "bat",
    "powershell": "ps1",
    "java": "java",
    "c#": "cs",
}


def _safe_name(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name.strip().lower())
    return name or "proyecto"


def _resolve_base(location: str):
    """Devuelve (ruta_base, reconocida). Si la ubicación pedida no coincide con
    ninguna conocida (ej. el micrófono transcribió mal "Descargas"), cae a la
    carpeta interna del asistente en vez de inventar una carpeta con un nombre
    sin sentido en Documentos/Escritorio reales del usuario."""
    key = (location or "").strip().lower()
    if key in BASE_LOCATIONS:
        return BASE_LOCATIONS[key], True
    return PROJECTS_DIR, False


def _location_note(location: str, recognized: bool) -> str:
    if recognized:
        return ""
    return (
        f" (no reconocí '{location}' como ubicación válida — dile que use "
        "Documentos, Escritorio, Descargas o proyectos)"
    )


def create_folder(name: str, location: str = "documentos") -> str:
    base, recognized = _resolve_base(location)
    folder = os.path.join(base, _safe_name(name))
    os.makedirs(folder, exist_ok=True)
    return f"Carpeta '{_safe_name(name)}' creada en {folder}.{_location_note(location, recognized)}"


def open_folder(location: str = "documentos") -> str:
    base, recognized = _resolve_base(location)
    os.makedirs(base, exist_ok=True)
    os.startfile(base)
    return f"Abriendo {base} en el explorador de archivos.{_location_note(location, recognized)}"


def list_files(location: str = "documentos") -> str:
    base, recognized = _resolve_base(location)
    if not os.path.isdir(base):
        return f"La carpeta {base} todavía no existe."
    entries = sorted(os.listdir(base))
    note = _location_note(location, recognized)
    if not entries:
        return f"La carpeta {base} está vacía.{note}"
    preview = entries[:20]
    listado = ", ".join(preview)
    if len(entries) > 20:
        listado += f", y {len(entries) - 20} más"
    return f"En {base} hay: {listado}.{note}"


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```[a-zA-Z0-9]*\n(.*)\n```$", text, re.DOTALL)
    return match.group(1) if match else text


def _generate_code(config, instruction: str) -> str:
    client = Groq(api_key=config.groq_api_key)
    response = client.chat.completions.create(
        model=config.groq_model,
        messages=[
            {"role": "system", "content": CODE_SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ],
        temperature=0.4,
        max_tokens=4000,
        reasoning_effort="medium",
    )
    return _strip_code_fence(response.choices[0].message.content or "")


def create_webpage(config, description: str, name: str = "mi_pagina", location: str = "proyectos") -> str:
    base, recognized = _resolve_base(location)
    folder = os.path.join(base, _safe_name(name))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "index.html")

    instruction = (
        "Crea una página web completa en un solo archivo HTML, con el CSS y JavaScript "
        f"incluidos dentro del mismo archivo, para lo siguiente: {description}"
    )
    code = _generate_code(config, instruction)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)

    webbrowser.open(f"file:///{path}")
    return (
        f"Listo, creé tu página web en {folder}\\index.html y la abrí en el navegador."
        f"{_location_note(location, recognized)}"
    )


def create_script(
    config, description: str, name: str = "mi_script", language: str = "python", location: str = "proyectos"
) -> str:
    ext = LANGUAGE_EXTENSIONS.get(language.strip().lower(), "txt")
    base, recognized = _resolve_base(location)
    folder = os.path.join(base, _safe_name(name))
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"main.{ext}")

    instruction = f"Crea un script completo y funcional en {language} para: {description}"
    code = _generate_code(config, instruction)
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)

    return f"Listo, creé tu script en {folder}\\main.{ext}.{_location_note(location, recognized)}"


DOCUMENT_SYSTEM_PROMPT = (
    "Eres un escritor experto. Genera SOLO el texto pedido (el cuento, carta, ensayo, resumen, "
    "lo que sea), sin explicaciones ni comentarios editoriales, sin bloques de markdown, listo "
    "para guardarse directamente en un archivo de texto tal cual."
)


def _generate_text(config, instruction: str) -> str:
    client = Groq(api_key=config.groq_api_key)
    response = client.chat.completions.create(
        model=config.groq_model,
        messages=[
            {"role": "system", "content": DOCUMENT_SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ],
        temperature=0.7,
        max_tokens=4000,
        reasoning_effort="medium",
    )
    return _strip_code_fence(response.choices[0].message.content or "")


def create_document(config, description: str, name: str = "documento", location: str = "documentos") -> str:
    """Escribe un documento de texto real (cuento, carta, ensayo...) y lo guarda
    y abre de verdad — a diferencia de pedirle a la IA que solo "diga" que lo hizo."""
    base, recognized = _resolve_base(location)
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, _safe_name(name) + ".txt")

    text = _generate_text(config, description)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    try:
        os.startfile(path)
    except OSError:
        pass

    return f"Listo, escribí el documento y lo guardé en {path}. Lo abrí para que lo veas.{_location_note(location, recognized)}"
