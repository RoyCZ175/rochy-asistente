"""Cerebro conversacional local, sin internet, vía Ollama (https://ollama.com).

Reutiliza las mismas herramientas que el cerebro en la nube (ai_brain.py),
pero llama a un modelo pequeño corriendo en tu propia PC en vez de a Groq.
Requiere tener Ollama instalado y corriendo, con un modelo ya descargado
(ver setup_ollama.md o el mensaje de error si falta).

Es intencionalmente más simple que AIBrain: los modelos locales pequeños son
mucho menos fiables encadenando varias herramientas seguidas, así que aquí
nos limitamos a una sola ronda de herramientas por turno.
"""

import json

import requests

import concurrent.futures

from ai_brain import (
    TOOLS,
    VERBATIM_TOOLS,
    TYPING_TOOLS,
    TOOL_TIMEOUT_SECONDS,
    _tool_executor,
    _typing_intent_present,
    build_tool_functions,
)
import memory_store as mem

OLLAMA_BASE = "http://localhost:11434"
TIMEOUT = 60

SYSTEM_PROMPT_LOCAL = """Eres {name}, un asistente de voz personal, hablas en español.
Estás en modo local (sin internet), con un modelo más simple y pequeño que el habitual,
así que sé directo y breve (1 a 2 frases), sin listas ni markdown.
Tienes herramientas para tareas básicas del PC (abrir apps, hora, volumen, teclado, mouse,
carpetas) y para recordar datos del usuario. Las herramientas que necesitan internet (Spotify,
Google, la universidad, create_document/create_webpage/create_script porque generan el contenido
con IA en la nube) probablemente no funcionen ahora mismo — si fallan, dilo con naturalidad.
Usa una herramienta solo cuando el usuario pida una acción concreta.
IMPORTANTE: teclear (type_text/press_key/hotkey) escribe literalmente en la ventana que tenga el
foco en ese momento. Úsalo SOLO si el usuario pide explícitamente escribir algo en otra app. Tu
propia respuesta NUNCA se teclea, siempre va hablada/en el chat.
REGLA CRÍTICA: NUNCA digas que creaste, escribiste o guardaste un archivo si no llamaste a la
herramienta de verdad y esta tuvo éxito — si la herramienta falló, dilo, no inventes que
funcionó.{memory_context}"""


def is_available(model: str) -> bool:
    """Comprueba si Ollama está corriendo y el modelo pedido está descargado."""
    try:
        resp = requests.get(f"{OLLAMA_BASE}/api/tags", timeout=2)
        resp.raise_for_status()
    except Exception:
        return False
    names = [m.get("name", "") for m in resp.json().get("models", [])]
    return any(model == n or n.startswith(model + ":") for n in names)


class LocalAIBrain:
    def __init__(self, config, model: str = "llama3.2"):
        self.model = model
        self.functions = build_tool_functions(config)
        self._system_content = SYSTEM_PROMPT_LOCAL.format(
            name=config.assistant_name, memory_context=mem.as_prompt_context()
        )
        self.history = [{"role": "system", "content": self._system_content}]
        self.max_turns = 8

    def reset(self) -> None:
        self.history = [{"role": "system", "content": self._system_content}]

    def ask(self, user_text: str, cancel_event=None) -> str:
        self.history.append({"role": "user", "content": user_text})
        self._trim_history()

        if cancel_event is not None and cancel_event.is_set():
            return None

        message = self._chat(tools=TOOLS)

        if cancel_event is not None and cancel_event.is_set():
            return None

        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            final_text = message.get("content") or ""
            self.history.append({"role": "assistant", "content": final_text})
            return final_text

        self.history.append({"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls})

        verbatim_result = None
        for call in tool_calls:
            name = call["function"]["name"]
            raw_args = call["function"].get("arguments", {})
            args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")

            func = self.functions.get(name)
            if not func:
                result = f"Herramienta desconocida: {name}"
            elif name in TYPING_TOOLS and not _typing_intent_present(self.history):
                result = "No hice eso: no pediste explícitamente escribir o teclear algo en otra aplicación."
            else:
                try:
                    # mismo límite de tiempo por herramienta que el cerebro en la nube
                    # (ai_brain.py): sin esto, algo como una llamada a Spotify colgada
                    # podía bloquear este hilo sin límite.
                    future = _tool_executor.submit(func, args)
                    result = future.result(timeout=TOOL_TIMEOUT_SECONDS)
                except concurrent.futures.TimeoutError:
                    result = (
                        f"Cancelé '{name}' porque tardó demasiado (más de "
                        f"{TOOL_TIMEOUT_SECONDS} segundos) sin responder."
                    )
                except Exception as exc:
                    result = f"No se pudo ejecutar {name}: {exc}"

            if name in VERBATIM_TOOLS:
                verbatim_result = str(result)

            self.history.append({"role": "tool", "name": name, "content": str(result)})

        if verbatim_result is not None:
            self.history.append({"role": "assistant", "content": verbatim_result})
            return verbatim_result

        if cancel_event is not None and cancel_event.is_set():
            return None

        followup = self._chat(tools=None)
        final_text = followup.get("content") or ""
        self.history.append({"role": "assistant", "content": final_text})
        return final_text

    def _chat(self, tools) -> dict:
        payload = {
            "model": self.model,
            "messages": self.history,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        resp = requests.post(f"{OLLAMA_BASE}/api/chat", json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("message", {})

    def _trim_history(self) -> None:
        limit = self.max_turns * 2 + 1
        if len(self.history) > limit:
            self.history = [self.history[0]] + self.history[-(limit - 1):]
