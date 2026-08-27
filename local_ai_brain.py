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
    LOCAL_TOOLS,
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
Estás en modo local (sin internet o modo ahorro activado a propósito), con un modelo más
simple y pequeño que el habitual, así que sé directo y breve (1 a 2 frases), sin listas ni
markdown.
La palabra clave configurada para activarte por voz (la que hay que decir antes de darte una orden) es
"{wake_word}" — NO es necesariamente tu nombre. Si te preguntan qué decir para activarte, di exactamente
esa palabra, nunca inventes ni asumas que es tu propio nombre.
Tienes herramientas para tareas básicas del PC (abrir apps, hora, volumen, teclado, mouse,
carpetas) y para recordar datos del usuario. Las que necesitan internet (Spotify, Google, la
universidad) probablemente no funcionen ahora mismo si de verdad no hay conexión — si fallan,
dilo con naturalidad.
NO tienes disponibles create_document, create_webpage ni create_script (necesitan generar el
contenido con IA en la nube, y eso no aplica en modo local): si te piden crear un documento,
página web o script, dilo claramente y sugiere pasar a "modo online" en vez de intentarlo o de
inventar que lo hiciste.
Si el usuario está en "modo estudio" con una materia activa, create_folder ignora automáticamente
la ubicación pedida y crea todo dentro de la carpeta fija de esa materia.
Puedes ver o borrar tus propias creaciones recientes (list_recent_creations / delete_recent_creations)
— nunca afectan al modo estudio ni a archivos que el usuario ya tenía de antes.
REGLA CRÍTICA: delete_recent_creations borra de verdad y no se puede deshacer. NUNCA la llames en el
mismo turno en que se pide: primero confirma en voz qué vas a borrar y espera una respuesta afirmativa
explícita en un mensaje posterior antes de llamarla.
Usa una herramienta solo cuando el usuario pida una acción concreta.
REGLA CRÍTICA: si te preguntan la hora o la fecha, SIEMPRE llama a get_time — nunca inventes una
hora, ni siquiera aproximada. Si te piden abrir una app, SIEMPRE llama a open_app — nunca digas
que la abriste sin haber llamado a la herramienta de verdad.
IMPORTANTE: cuando uses una herramienta, hazlo SIEMPRE mediante el mecanismo real de function
calling (tool_calls) que tienes disponible. NUNCA escribas el nombre de una función ni su
sintaxis como si fuera texto normal de tu respuesta (ej. nunca escribas algo como
open_app("calculadora") en tu mensaje) — eso no ejecuta nada de verdad.
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
            name=config.assistant_name, wake_word=config.wake_word, memory_context=mem.as_prompt_context()
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

        message = self._chat(tools=LOCAL_TOOLS)

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
            "options": {
                # Con la temperatura por defecto del modelo (más alta, pensada para
                # charla), un modelo de 7B era inconsistente decidiendo cuándo usar
                # una herramienta (a veces inventaba una respuesta en vez de llamarla,
                # ej. una hora falsa en vez de get_time) — con esto es mucho más fiable.
                "temperature": 0.2,
                # Sin fijarlo, Ollama usa una ventana de contexto chica por
                # defecto — con el modo estudio (RAG) pegando fragmentos de
                # apuntes a cada pregunta, eso podía truncar justo el contexto
                # que queríamos darle. Medido en esta PC: con 16384 el modelo
                # usa ~5.3GB de VRAM (de 8GB), deja de sobra para lo demás.
                "num_ctx": 16384,
            },
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
