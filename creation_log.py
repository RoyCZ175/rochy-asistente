"""Recuerda lo que Rochy ha creado de verdad (carpetas, documentos, páginas
web, scripts) vía code_generator.py — para poder deshacerlo por referencia
relativa ("bórrame las dos últimas carpetas que creaste") sin que el usuario
tenga que repetir el nombre o la ruta exacta.

Se guarda en disco (creation_log.json) para que sobreviva a cerrar y abrir la
app de nuevo, igual que memory_store.py.

IMPORTANTE: esto NO incluye las carpetas de materias del modo estudio (ver
study_rag.py) — esas pueden tener archivos reales del usuario (sus propios
PDFs/apuntes) y nunca deben poder borrarse por accidente con un "borra las
últimas carpetas que creaste" genérico. El modo estudio tiene su propio
comando explícito para eso ("olvida el estudio de X"), y ese solo borra el
índice calculado, nunca los archivos."""

import datetime
import json
import os
import shutil

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "creation_log.json")
MAX_ENTRIES = 200

KIND_LABELS = {
    "folder": "carpeta",
    "document": "documento",
    "webpage": "página web",
    "script": "script",
}


def _load() -> list:
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(entries: list) -> None:
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(entries[-MAX_ENTRIES:], f, ensure_ascii=False, indent=2)


def record(kind: str, path: str) -> None:
    """Registra una creación real. Se llama justo después de crear algo de
    verdad en disco (nunca antes, para no registrar algo que en realidad
    falló)."""
    entries = _load()
    entries.append(
        {
            "kind": kind,
            "path": path,
            "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
    )
    _save(entries)


def list_recent_text(count: int = 5) -> str:
    entries = _load()[-count:][::-1]
    if not entries:
        return "No tengo registro de haber creado nada todavía."
    lines = [f"- {KIND_LABELS.get(e['kind'], e['kind'])}: {e['path']}" for e in entries]
    return "Lo más reciente que creé:\n" + "\n".join(lines)


def delete_recent(count: int, kind: str = None) -> str:
    """Borra de disco las 'count' creaciones más recientes (opcionalmente
    filtrando por tipo, ej. solo carpetas) y las quita del registro."""
    entries = _load()
    matching_idx = [
        i for i in range(len(entries) - 1, -1, -1) if kind is None or entries[i]["kind"] == kind
    ][:count]

    if not matching_idx:
        objetivo = KIND_LABELS.get(kind, "nada") if kind else "nada"
        return f"No tengo registro de haber creado {objetivo} que pueda borrar."

    deleted = []
    failed = []
    for i in matching_idx:
        entry = entries[i]
        path = entry["path"]
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            elif os.path.isfile(path):
                os.remove(path)
            deleted.append(f"{KIND_LABELS.get(entry['kind'], entry['kind'])} ({path})")
        except Exception as exc:
            failed.append(f"{path} ({exc})")

    remaining = [e for i, e in enumerate(entries) if i not in matching_idx]
    _save(remaining)

    if not deleted:
        return "No pude borrar nada — revisa si ya no existía."
    summary = f"Borré {len(deleted)}: " + "; ".join(deleted) + "."
    if failed:
        summary += f" No pude borrar: {'; '.join(failed)}."
    return summary
