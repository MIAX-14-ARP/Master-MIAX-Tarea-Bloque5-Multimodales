"""Tests de humo contra las APIs REALES (de pago). Desactivados por defecto.

Para ejecutarlos (consumen crédito, del orden de céntimos en total):

    FINLENS_LIVE_TESTS=1 pytest -m live -v -s      # con las claves en .env o en el entorno

Primero comprueban de forma gratuita que los modelos configurados existen; después hacen una
llamada mínima por modalidad e imprimen latencia y consumo, útiles para la sección de viabilidad.
"""
import io
import os
import time

import pytest

from finlens.config import Settings
from finlens.domain.cost import Tariffs, text_result_cost
from finlens.domain.schemas import ChartReading
from finlens.domain.structured import ask_structured, ask_structured_vision
from finlens.providers.base import Message
from finlens.providers.registry import build_real_providers
from finlens.ui.demo_samples import demo_chart_png

pytestmark = pytest.mark.live

if os.environ.get("FINLENS_LIVE_TESTS") != "1":
    pytest.skip("Pruebas en vivo desactivadas (FINLENS_LIVE_TESTS=1 para activarlas)", allow_module_level=True)

SETTINGS = Settings()  # lee .env y el entorno
if SETTINGS.demo_reason and not SETTINGS.demo_mode:
    pytest.skip(f"Faltan claves para las pruebas en vivo: {SETTINGS.demo_reason}", allow_module_level=True)


@pytest.fixture(scope="module")
def providers():
    return build_real_providers(SETTINGS)


def medir(etiqueta: str, inicio: float, extra: str = "") -> None:
    print(f"\n[vivo] {etiqueta}: {time.perf_counter() - inicio:.2f} s {extra}")


def test_los_modelos_configurados_existen() -> None:
    """Gratuito: pregunta a cada proveedor si conoce el modelo configurado."""
    import anthropic
    import openai

    cliente_anthropic = anthropic.Anthropic(api_key=SETTINGS.anthropic_api_key.get_secret_value())
    for nombre in {SETTINGS.llm_model, SETTINGS.vision_model}:
        assert cliente_anthropic.models.retrieve(nombre).id, nombre

    cliente_openai = openai.OpenAI(api_key=SETTINGS.openai_api_key.get_secret_value())
    for nombre in (SETTINGS.stt_model, SETTINGS.tts_model, SETTINGS.image_model):
        assert cliente_openai.models.retrieve(nombre).id, nombre


def test_llm_devuelve_json_estructurado(providers) -> None:
    from finlens.domain.schemas import InfographicPrompt

    inicio = time.perf_counter()
    resultado = ask_structured(
        providers.llm, "Redactas prompts de imagen.", [Message("user", "Infografía sobre un margen del 18 %.")],
        InfographicPrompt,
    )
    llamada = resultado.calls[-1]
    coste = text_result_cost(Tariffs.from_settings(SETTINGS), llamada)
    medir("LLM", inicio, f"({llamada.tokens_in} tok in, {llamada.tokens_out} tok out, ~{coste:.5f} USD)")
    assert resultado.value.prompt


def test_vision_lee_un_grafico(providers) -> None:
    inicio = time.perf_counter()
    resultado = ask_structured_vision(
        providers.vision, demo_chart_png(), "image/png", "Describe este gráfico de velas.", ChartReading
    )
    medir("Visión", inicio, f"({resultado.calls[-1].tokens_in} tok in)")
    assert resultado.value.description


def test_tts_y_stt_dan_la_vuelta_completa(providers) -> None:
    """Sintetiza una frase y la transcribe: valida ambos proveedores con una sola frase de coste mínimo."""
    inicio = time.perf_counter()
    voz = providers.tts.synthesize("Hola, esto es una prueba de FinLens.")
    medir("TTS", inicio, f"({len(voz.audio)} bytes)")
    assert voz.audio and voz.mime == "audio/mpeg"

    inicio = time.perf_counter()
    texto = providers.stt.transcribe(voz.audio, "prueba.mp3")
    medir("STT", inicio, f"({texto.duration_s:.1f} s de audio)")
    assert "prueba" in texto.text.lower()


def test_imagen_se_genera(providers) -> None:
    inicio = time.perf_counter()
    imagen = providers.image.generate("Infografía minimalista con una flecha ascendente azul sobre fondo blanco.")
    medir("Imagen", inicio, f"({len(imagen.image)} bytes)")
    assert imagen.image[:4] == b"\x89PNG"
