"""Tests de ask_structured: validación, reintento único y degradación con mensaje claro."""
import json
from typing import Sequence

import pytest

from finlens.domain.schemas import ChartReading, InfographicPrompt
from finlens.domain.structured import StructuredOutputError, ask_structured, ask_structured_vision
from finlens.providers.base import Message, TextResult
from finlens.providers.mock import MockLLM, MockVision
from finlens.ui.demo_samples import demo_chart_png

PEDIDO = [Message("user", "Analiza el gráfico")]
VALIDO = json.dumps({"prompt": "una infografía"})


class LLMGuionizado:
    """LLM de prueba que devuelve respuestas predefinidas y registra las llamadas."""

    def __init__(self, *respuestas: str) -> None:
        self.respuestas = list(respuestas)
        self.llamadas: list[Sequence[Message]] = []

    def complete(
        self, system: str, messages: Sequence[Message], max_tokens: int = 2048
    ) -> TextResult:
        self.llamadas.append(list(messages))
        return TextResult(self.respuestas.pop(0), "guion")


def test_json_valido_se_acepta_a_la_primera() -> None:
    llm = LLMGuionizado(VALIDO)
    resultado = ask_structured(llm, "sistema", PEDIDO, InfographicPrompt)
    assert resultado.value.prompt == "una infografía"
    assert len(resultado.calls) == 1


def test_acepta_json_dentro_de_valla_de_codigo() -> None:
    llm = LLMGuionizado(f"Aquí tienes:\n```json\n{VALIDO}\n```")
    assert ask_structured(llm, "s", PEDIDO, InfographicPrompt).value.prompt == "una infografía"


def test_json_invalido_reintenta_una_vez_y_se_recupera() -> None:
    llm = LLMGuionizado("esto no es json", VALIDO)
    resultado = ask_structured(llm, "s", PEDIDO, InfographicPrompt)
    assert resultado.value.prompt == "una infografía"
    assert len(resultado.calls) == 2
    reintento = llm.llamadas[1]
    assert reintento[-1].role == "user" and "no es JSON válido" in reintento[-1].content


def test_json_que_incumple_el_esquema_tambien_reintenta() -> None:
    llm = LLMGuionizado(json.dumps({"otro_campo": 1}), VALIDO)
    assert len(ask_structured(llm, "s", PEDIDO, InfographicPrompt).calls) == 2


def test_dos_fallos_degradan_con_mensaje_claro_y_sin_mas_reintentos() -> None:
    llm = LLMGuionizado("basura", "más basura")
    with pytest.raises(StructuredOutputError, match="tras 2 intentos"):
        ask_structured(llm, "s", PEDIDO, InfographicPrompt)
    assert len(llm.llamadas) == 2


def test_el_system_prompt_incluye_marcador_de_esquema() -> None:
    capturado: list[str] = []

    class Espia(LLMGuionizado):
        def complete(self, system, messages, max_tokens=2048):  # type: ignore[no-untyped-def]
            capturado.append(system)
            return super().complete(system, messages, max_tokens)

    ask_structured(Espia(VALIDO), "sistema", PEDIDO, InfographicPrompt)
    assert "ESQUEMA: InfographicPrompt" in capturado[0]


def test_mock_llm_responde_el_esquema_pedido() -> None:
    resultado = ask_structured(MockLLM(), "sistema", PEDIDO, ChartReading)
    assert resultado.value.trend == "alcista"
    assert resultado.calls[0].tokens_in > 0


class VisionGuionizada:
    """Visión de prueba con respuestas predefinidas; guarda los prompts recibidos."""

    def __init__(self, *respuestas: str) -> None:
        self.respuestas = list(respuestas)
        self.prompts: list[str] = []

    def describe_image(self, image: bytes, mime: str, prompt: str) -> TextResult:
        self.prompts.append(prompt)
        return TextResult(self.respuestas.pop(0), "guion")


def test_vision_estructurada_con_mock() -> None:
    resultado = ask_structured_vision(MockVision(), demo_chart_png(), "image/png", "describe", ChartReading)
    assert resultado.value.trend == "alcista"


def test_vision_estructurada_reintenta_con_la_correccion_en_el_prompt() -> None:
    valido = json.dumps({"trend": "lateral", "description": "rango estrecho"})
    vision = VisionGuionizada("no json", valido)
    resultado = ask_structured_vision(vision, b"img", "image/png", "describe", ChartReading)
    assert resultado.value.trend == "lateral" and len(resultado.calls) == 2
    assert "ESQUEMA: ChartReading" in vision.prompts[0]
    assert "no es JSON válido" in vision.prompts[1]


def test_vision_estructurada_degrada_tras_dos_fallos() -> None:
    with pytest.raises(StructuredOutputError, match="tras 2 intentos"):
        ask_structured_vision(VisionGuionizada("x", "y"), b"img", "image/png", "d", ChartReading)
