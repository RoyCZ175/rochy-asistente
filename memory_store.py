"""Memoria persistente simple: hechos clave-valor sobre el usuario, guardados en disco
para que el asistente te recuerde entre sesiones."""

import json
import os

MEMORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_memory.json")


def load_facts() -> dict:
    if not os.path.exists(MEMORY_PATH):
        return {}
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_facts(facts: dict) -> None:
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(facts, f, ensure_ascii=False, indent=2)


def remember(key: str, value: str) -> str:
    facts = load_facts()
    key = key.strip().lower()
    facts[key] = value.strip()
    save_facts(facts)
    return f"Anotado: {key} es {value}."


def forget(key: str) -> str:
    facts = load_facts()
    key = key.strip().lower()
    if key in facts:
        del facts[key]
        save_facts(facts)
        return f"Olvidé lo que sabía sobre {key}."
    return f"No tenía nada guardado sobre {key}."


def as_prompt_context() -> str:
    facts = load_facts()
    if not facts:
        return ""
    lines = "\n".join(f"- {k}: {v}" for k, v in facts.items())
    return f"\n\nCosas que ya sabes del usuario, de conversaciones anteriores:\n{lines}"
