"""Cerebro conversacional de respaldo: Gemini (Google), con capa gratuita.

Se usa cuando Groq falla o se queda sin cupo diario (ver _generate_response en
voice_assistant.py) — un segundo intento en la nube antes de caer al modelo
local. Mismas herramientas y mismas reglas de comportamiento que ai_brain.py
(reutilizadas de ahí, no reescritas), solo cambia el SDK/formato de mensajes
porque Gemini no usa el mismo esquema que Groq/OpenAI.
"""

import concurrent.futures

from google import genai
from google.genai import types

from ai_brain import (
    MAX_TOOL_ROUNDS,
    SYSTEM_PROMPT,
    TOOL_TIMEOUT_SECONDS,
    TOOLS,
    TYPING_INTENT_KEYWORDS,
    TYPING_TOOLS,
    VERBATIM_TOOLS,
    _tool_executor,
    build_tool_functions,
)
import memory_store as mem
import mode_state

# Preset por nivel de "calidad" (ver mode_state.get_quality()/set_quality()).
# thinking_level es el equivalente en Gemini al reasoning_effort de Groq (ver
# QUALITY_PRESETS en ai_brain.py) — "minimal" prácticamente no razona antes
# de responder, "high" sí, y probado en vivo consume tanto presupuesto de
# pensamiento que con max_output_tokens bajo puede no dejar nada para la
# respuesta visible, por eso "alto" también sube el tope de tokens.
QUALITY_PRESETS = {
    "bajo": {"thinking_level": "minimal", "max_output_tokens": 350},
    "medio": {"thinking_level": "medium", "max_output_tokens": 600},
    "alto": {"thinking_level": "high", "max_output_tokens": 1200},
}


def _build_gemini_tool() -> types.Tool:
    # Los esquemas de parámetros ya están en formato JSON Schema estándar (los
    # mismos que usa Groq/OpenAI) — Gemini los acepta tal cual vía
    # parameters_json_schema, sin necesidad de traducir nada a mano.
    declarations = [
        types.FunctionDeclaration(
            name=t["function"]["name"],
            description=t["function"]["description"],
            parameters_json_schema=t["function"]["parameters"],
        )
        for t in TOOLS
    ]
    return types.Tool(function_declarations=declarations)


def _last_user_text(history: list) -> str:
    for content in reversed(history):
        if content.role == "user" and content.parts:
            texts = [p.text for p in content.parts if getattr(p, "text", None)]
            if texts:
                return " ".join(texts).lower()
    return ""


def _typing_intent_present(history: list) -> bool:
    text = _last_user_text(history)
    return any(k in text for k in TYPING_INTENT_KEYWORDS)


class GeminiBrain:
    def __init__(self, config):
        # Por defecto el SDK reintenta hasta 5 veces con espera exponencial
        # (1s, 2s, 4s, 8s...) ante un error como "servidor con mucha demanda"
        # — eso solo, sin contar el tiempo de la petición en sí, puede sumar
        # 15-30 segundos de espera ANTES de que Gemini termine de fallar de
        # verdad. Como ya tenemos nuestra propia cadena de respaldo (Groq ->
        # Gemini -> local, ver voice_assistant.py), esos reintentos internos
        # son pura demora redundante: mejor que falle rápido una vez y deje
        # que el siguiente respaldo (local) entre en acción cuanto antes.
        http_options = types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
        self.client = genai.Client(api_key=config.gemini_api_key, http_options=http_options)
        self.model = config.gemini_model
        self.functions = build_tool_functions(config)
        self._system_content = SYSTEM_PROMPT.format(
            name=config.assistant_name, wake_word=config.wake_word, memory_context=mem.as_prompt_context()
        )
        self._tool = _build_gemini_tool()
        self.max_turns = 12
        self.history: list = []

    def reset(self) -> None:
        self.history = []

    def _config(self) -> types.GenerateContentConfig:
        preset = QUALITY_PRESETS[mode_state.get_quality()]
        return types.GenerateContentConfig(
            system_instruction=self._system_content,
            tools=[self._tool],
            temperature=0.6,
            max_output_tokens=preset["max_output_tokens"],
            thinking_config=types.ThinkingConfig(thinking_level=preset["thinking_level"]),
            # Control manual, igual que ai_brain.py/local_ai_brain.py: ejecutamos
            # las herramientas nosotros mismos (con límite de tiempo, logging,
            # reglas de tipeo, etc.) en vez de dejar que el SDK las llame solo.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def ask(self, user_text: str, cancel_event=None) -> str:
        self.history.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
        self._trim_history()

        # Si ya se ejecutó una herramienta de verdad en este turno y LUEGO la
        # llamada de "resumen final" falla (ej. se acabó la cuota gratuita de
        # Gemini a mitad de turno — pasó de verdad: creó un documento real y
        # después no pudo ni contarlo), es mejor devolver el resultado real de
        # la herramienta que dejar que todo el turno se reinicie desde cero en
        # otro cerebro que no tiene ni idea de que ya se hizo algo.
        last_tool_results: list = []

        for _ in range(MAX_TOOL_ROUNDS):
            if cancel_event is not None and cancel_event.is_set():
                return None

            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=self.history, config=self._config()
                )
            except Exception:
                if last_tool_results:
                    return " ".join(last_tool_results)
                raise

            if cancel_event is not None and cancel_event.is_set():
                return None

            candidate_content = response.candidates[0].content
            self.history.append(candidate_content)

            calls = response.function_calls or []
            if not calls:
                return response.text or ""

            verbatim_result = None
            response_parts = []
            for call in calls:
                name = call.name
                args = call.args or {}
                print(f"[tool] {name}({args})")

                func = self.functions.get(name)
                if not func:
                    result = f"Herramienta desconocida: {name}"
                elif name in TYPING_TOOLS and not _typing_intent_present(self.history):
                    result = "No hice eso: no pediste explícitamente escribir o teclear algo en otra aplicación."
                else:
                    try:
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

                last_tool_results.append(str(result))
                response_parts.append(
                    types.Part(function_response=types.FunctionResponse(name=name, response={"result": str(result)}))
                )

            self.history.append(types.Content(role="user", parts=response_parts))

            if verbatim_result is not None:
                # Mismo trato que en ai_brain.py: para respuestas de seguridad
                # crítica (confirmar antes de enviar un correo) se devuelve el
                # texto exacto de la herramienta, sin dejar que el modelo lo
                # reformule ni siga encadenando otra herramienta.
                self.history.append(types.Content(role="model", parts=[types.Part(text=verbatim_result)]))
                return verbatim_result

        final_text = "Hice varias acciones seguidas, pero me quedé sin poder resumirlo. ¿Revisamos si quedó bien?"
        self.history.append(types.Content(role="model", parts=[types.Part(text=final_text)]))
        return final_text

    def _trim_history(self) -> None:
        # A diferencia de ai_brain.py, aquí no hay un mensaje "system" dentro
        # del propio historial (Gemini lo recibe aparte en cada llamada vía
        # system_instruction), así que no hace falta preservarlo aparte.
        limit = self.max_turns * 2
        if len(self.history) > limit:
            self.history = self.history[-limit:]
