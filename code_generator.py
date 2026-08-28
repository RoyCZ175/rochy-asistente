"""Creación de carpetas y programas por voz: el asistente escribe archivos y
carpetas reales, pero SOLO dentro de un conjunto fijo de ubicaciones seguras
(la carpeta proyectos/ del propio asistente, o Documentos/Escritorio/Descargas
del usuario) — nunca en una ruta arbitraria del sistema."""

import os
import re
import webbrowser

from groq import Groq

import creation_log


def _cascade_complete(config, system_prompt: str, instruction: str, temperature: float, max_tokens: int) -> str:
    """Genera texto probando Groq -> Gemini -> IA local, en ese orden — el
    mismo respaldo que ya usa la conversación normal (ver
    voice_assistant._generate_response). Antes create_document/
    create_webpage/create_script dependían SOLO de Groq: si se quedaba sin
    cupo diario, fallaban por completo aunque hubiera otros respaldos
    configurados y disponibles."""
    try:
        client = Groq(api_key=config.groq_api_key, max_retries=0)
        response = client.chat.completions.create(
            model=config.groq_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": instruction},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort="medium",
        )
        return response.choices[0].message.content or ""
    except Exception as exc:
        print(f"[aviso] Groq falló generando contenido ({exc}), pruebo el siguiente respaldo.")

    if config.gemini_api_key:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=config.gemini_api_key,
                http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
            )
            response = client.models.generate_content(
                model=config.gemini_model,
                contents=instruction,
                config=types.GenerateContentConfig(system_instruction=system_prompt, temperature=temperature),
            )
            return response.text or ""
        except Exception as exc:
            print(f"[aviso] Gemini también falló generando contenido ({exc}), pruebo el modelo local.")

    import local_ai_brain

    if local_ai_brain.is_available(config.ollama_model):
        try:
            return local_ai_brain.simple_complete(config.ollama_model, system_prompt, instruction)
        except Exception as exc:
            print(f"[aviso] El modelo local también falló generando contenido ({exc}).")

    raise RuntimeError("Groq, Gemini y el modelo local fallaron o no están disponibles ahora mismo.")

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
    """Devuelve (ruta_base, reconocida).

    Si hay una materia activa en modo estudio, TODO lo que se cree (carpetas,
    documentos, páginas, scripts) va dentro de la carpeta fija de esa materia
    — se ignora a propósito el 'location' pedido, para que nunca queden
    archivos regados fuera de Documentos/RAG_Rochy mientras estás estudiando.
    Fuera de modo estudio funciona como siempre: si la ubicación pedida no
    coincide con ninguna conocida (ej. el micrófono transcribió mal
    "Descargas"), cae a la carpeta interna del asistente en vez de inventar
    una carpeta con un nombre sin sentido en Documentos/Escritorio reales."""
    import study_state
    import study_rag

    subject = study_state.get_subject()
    if subject is not None:
        return study_rag.subject_dir(subject), True

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
    creation_log.record("folder", folder)
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
    text = _cascade_complete(config, CODE_SYSTEM_PROMPT, instruction, temperature=0.4, max_tokens=4000)
    return _strip_code_fence(text)


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
    creation_log.record("webpage", folder)
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

    creation_log.record("script", folder)
    return f"Listo, creé tu script en {folder}\\main.{ext}.{_location_note(location, recognized)}"


DOCUMENT_SYSTEM_PROMPT = (
    "Eres un escritor experto. Genera SOLO el texto pedido (el cuento, carta, ensayo, resumen, "
    "lo que sea), sin explicaciones ni comentarios editoriales, sin bloques de markdown, listo "
    "para guardarse directamente en un archivo de texto tal cual."
)


def _generate_text(config, instruction: str) -> str:
    text = _cascade_complete(config, DOCUMENT_SYSTEM_PROMPT, instruction, temperature=0.7, max_tokens=4000)
    return _strip_code_fence(text)


DOCUMENT_EXTENSIONS = {"txt": "txt", "word": "docx", "docx": "docx", "pdf": "pdf"}


def _write_txt(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _write_docx(path: str, text: str) -> None:
    from docx import Document

    doc = Document()
    for paragraph in text.split("\n"):
        doc.add_paragraph(paragraph)
    doc.save(path)


def _write_pdf(path: str, text: str) -> None:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for paragraph in text.split("\n"):
        # latin-1 cubre bien los acentos y la ñ del español — las fuentes base
        # de fpdf no traen soporte unicode completo sin cargar una fuente TTF
        # aparte, y para texto en español esto alcanza sin agregar esa carga.
        safe = paragraph.encode("latin-1", errors="replace").decode("latin-1")
        # Sin new_x="LMARGIN", multi_cell deja el cursor pegado al margen
        # DERECHO después de cada línea — la siguiente llamada calcula un
        # ancho disponible casi nulo y revienta con "Not enough horizontal
        # space to render a single character" (reproducido de verdad).
        pdf.multi_cell(0, 8, safe, new_x="LMARGIN", new_y="NEXT")
    pdf.output(path)


def create_document(
    config, description: str, name: str = "documento", location: str = "documentos", format: str = "txt"
) -> str:
    """Escribe un documento real (cuento, carta, ensayo...) en el formato pedido
    (texto plano, Word o PDF) y lo guarda y abre de verdad — a diferencia de
    pedirle a la IA que solo "diga" que lo hizo."""
    base, recognized = _resolve_base(location)
    os.makedirs(base, exist_ok=True)
    ext = DOCUMENT_EXTENSIONS.get(format.strip().lower(), "txt")
    path = os.path.join(base, _safe_name(name) + "." + ext)

    text = _generate_text(config, description)
    if ext == "docx":
        _write_docx(path, text)
    elif ext == "pdf":
        _write_pdf(path, text)
    else:
        _write_txt(path, text)

    try:
        os.startfile(path)
    except OSError:
        pass

    creation_log.record("document", path)
    return f"Listo, escribí el documento y lo guardé en {path}. Lo abrí para que lo veas.{_location_note(location, recognized)}"
