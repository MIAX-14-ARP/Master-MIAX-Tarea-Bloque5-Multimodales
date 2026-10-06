"""Salidas del LLM como JSON validado con Pydantic: un reintento y error claro si sigue fallando."""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from finlens.providers.base import LLMProvider, Message, TextResult, VisionProvider

T = TypeVar("T", bound=BaseModel)

SCHEMA_MARKER = "ESQUEMA:"

# Recibe (respuesta_anterior, motivo_del_fallo) en el reintento, o None en el primer intento.
_Invocador = Callable[["tuple[str, str] | None"], TextResult]


class StructuredOutputError(Exception):
    """El modelo no devolvió un JSON válido tras el reintento. El mensaje es apto para la UI."""


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    """Valor validado y las llamadas al modelo realizadas (para trazar tokens y coste)."""

    value: T
    calls: tuple[TextResult, ...]


def _extract_json(raw: str) -> str:
    """Quita vallas de código y texto alrededor del objeto JSON."""
    texto = re.sub(r"```(?:json)?", "", raw).strip()
    inicio, fin = texto.find("{"), texto.rfind("}")
    return texto[inicio : fin + 1] if inicio != -1 and fin > inicio else texto


def parse_model(model_cls: type[T], raw: str) -> T:
    """Valida `raw` contra `model_cls`. Lanza ValueError con un motivo breve si no cumple."""
    try:
        return model_cls.model_validate(json.loads(_extract_json(raw)))
    except json.JSONDecodeError as exc:
        raise ValueError(f"no es JSON válido ({exc.msg})") from exc
    except ValidationError as exc:
        detalle = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:3])
        raise ValueError(f"no cumple el esquema ({detalle})") from exc


def _with_schema(text: str, model_cls: type[BaseModel]) -> str:
    esquema = json.dumps(model_cls.model_json_schema(), ensure_ascii=False)
    return (
        f"{text}\n\nResponde ÚNICAMENTE con un objeto JSON válido, sin texto adicional "
        f"ni bloques de código.\n{SCHEMA_MARKER} {model_cls.__name__}\n{esquema}"
    )


def _correccion(motivo: str) -> str:
    return f"Tu respuesta anterior {motivo}. Responde únicamente con el JSON corregido."


def _run(model_cls: type[T], invoke: _Invocador) -> StructuredResult[T]:
    """Llama al modelo y valida; si falla, reintenta una vez con el motivo del error."""
    llamadas: list[TextResult] = []
    feedback: tuple[str, str] | None = None
    for _ in range(2):
        resultado = invoke(feedback)
        llamadas.append(resultado)
        try:
            return StructuredResult(parse_model(model_cls, resultado.text), tuple(llamadas))
        except ValueError as exc:
            feedback = (resultado.text, str(exc))
    motivo = feedback[1] if feedback else "sin respuesta"
    raise StructuredOutputError(
        f"El modelo no devolvió una respuesta estructurada válida tras 2 intentos ({motivo}). "
        "Inténtalo de nuevo o simplifica la consulta."
    )


def ask_structured(
    llm: LLMProvider,
    system: str,
    messages: Sequence[Message],
    model_cls: type[T],
    max_tokens: int = 2048,
) -> StructuredResult[T]:
    """Pide al LLM un JSON del tipo `model_cls`; si es inválido, reintenta una vez."""
    system_completo = _with_schema(system, model_cls)

    def invocar(feedback: tuple[str, str] | None) -> TextResult:
        conversacion = list(messages)
        if feedback:
            conversacion += [Message("assistant", feedback[0]), Message("user", _correccion(feedback[1]))]
        return llm.complete(system_completo, conversacion, max_tokens)

    return _run(model_cls, invocar)


def ask_structured_vision(
    vision: VisionProvider, image: bytes, mime: str, prompt: str, model_cls: type[T]
) -> StructuredResult[T]:
    """Como `ask_structured` pero con una imagen; el reintento añade la corrección al prompt."""
    prompt_completo = _with_schema(prompt, model_cls)

    def invocar(feedback: tuple[str, str] | None) -> TextResult:
        extra = f"\n\n{_correccion(feedback[1])}" if feedback else ""
        return vision.describe_image(image, mime, prompt_completo + extra)

    return _run(model_cls, invocar)
