"""Calendario local de entregas universitarias.

No accede a ninguna plataforma por sí mismo — es solo el almacén de fechas
que el asistente usa para ayudarte a organizarte. La lectura real de tareas
pendientes desde el portal de la universidad se añade aparte (requiere
conocer la estructura de esa página primero)."""

import json
import os

DEADLINES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "university_deadlines.json")


def _load() -> list:
    if not os.path.exists(DEADLINES_PATH):
        return []
    try:
        with open(DEADLINES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save(deadlines: list) -> None:
    with open(DEADLINES_PATH, "w", encoding="utf-8") as f:
        json.dump(deadlines, f, ensure_ascii=False, indent=2)


def add_deadline(task: str, due_date: str, course: str = "") -> str:
    """due_date en formato libre tal como lo dice el usuario, ej: '2026-08-25' o 'viernes'."""
    deadlines = _load()
    deadlines.append({"task": task.strip(), "due_date": due_date.strip(), "course": course.strip()})
    _save(deadlines)
    curso = f" ({course})" if course else ""
    return f"Anotado: {task}{curso}, entrega {due_date}."


def list_deadlines() -> str:
    deadlines = _load()
    if not deadlines:
        return "No tienes entregas registradas todavía."
    lines = []
    for d in deadlines:
        curso = f" [{d['course']}]" if d.get("course") else ""
        lines.append(f"{d['due_date']}: {d['task']}{curso}")
    return "Tus entregas pendientes: " + "; ".join(lines) + "."


def remove_deadline(task: str) -> str:
    deadlines = _load()
    remaining = [d for d in deadlines if d["task"].strip().lower() != task.strip().lower()]
    if len(remaining) == len(deadlines):
        return f"No tenía registrada ninguna entrega llamada '{task}'."
    _save(remaining)
    return f"Listo, quité '{task}' de tus entregas pendientes."
