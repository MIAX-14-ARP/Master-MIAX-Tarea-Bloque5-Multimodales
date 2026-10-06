"""Tests de humo contra las APIs REALES (de pago). Desactivados por defecto.

Para ejecutarlos (consumen crédito, del orden de céntimos en total):

    FINLENS_LIVE_TESTS=1 pytest -m live -v -s      # con las claves en .env o en el entorno

Usan la misma selección de proveedores que la app (OPENROUTER_API_KEY y/o claves nativas, más los
`*_PROVIDER`); las capacidades que quedarían simuladas se omiten. Primero comprueban de forma
gratuita que los modelos configurados existen (catálogo público de OpenRouter o API de modelos del
proveedor nativo); después hacen una llamada mínima por capacidad e imprimen latencia y consumo.
"""
import json
import os
import time
import urllib.request

import pytest

from finlens.config import Settings
from finlens.domain.cost import Tariffs, text_result_cost
from finlens.domain.schemas import ChartReading, InfographicPrompt
from finlens.domain.structured import ask_structured, ask_structured_vision
from finlens.providers.base import Message, Providers
from finlens.providers.registry import build_providers
from finlens.ui.demo_samples import demo_chart_png

pytestmark = pytest.mark.live

if os.environ.get("FINLENS_LIVE_TESTS") != "1":
    pytest.skip("Pruebas en vivo desactivadas (FINLENS_LIVE_TESTS=1 para activarlas)", allow_module_level=True)

SETTINGS = Settings()  # lee .env y el entorno
PROVIDERS = build_providers(SETTINGS)
if PROVIDERS.is_demo:
    pytest.skip(f"Faltan claves para las pruebas en vivo: {SETTINGS.demo_reason}", allow_module_level=True)

CATALOGO_URL = "https://openrouter.ai/api/v1/models?output_modalities=all"


@pytest.fixture(scope="module")
def providers() -> Providers:
    return PROVIDERS


def real(capacidad: str) -> str:
    """Backend de la capacidad; omite el test si es simulado."""
    backend = next(i.backend for i in PROVIDERS.info if i.capability == capacidad)
    if backend == "mock":
        pytest.skip(f"«{capacidad}» está simulada con la configuración actual")
    return backend


def medir(etiqueta: str, inicio: float, extra: str = "") -> None:
    print(f"\n[vivo] {etiqueta}: {time.perf_counter() - inicio:.2f} s {extra}")


def test_los_modelos_configurados_existen() -> None:
    """Gratuito: pregunta a cada proveedor si conoce el modelo configurado."""
    de_openrouter = [i for i in PROVIDERS.info if i.backend == "openrouter"]
    if de_openrouter:
        # El catálogo es público: no hace falta clave ni cuesta nada.
        with urllib.request.urlopen(CATALOGO_URL, timeout=30) as respuesta:  # noqa: S310
            ids = {m["id"] for m in json.load(respuesta)["data"]}
        for info in de_openrouter:
            assert info.model in ids, f"{info.capability}: {info.model} no está en el catálogo de OpenRouter"

    nativas = {i.capability: i for i in PROVIDERS.info if i.backend in ("anthropic", "openai")}
    if any(i.backend == "anthropic" for i in nativas.values()):
        import anthropic

        cliente = anthropic.Anthropic(api_key=SETTINGS.anthropic_api_key.get_secret_value())
        for info in (i for i in nativas.values() if i.backend == "anthropic"):
            assert cliente.models.retrieve(info.model).id, info.model
    if any(i.backend == "openai" for i in nativas.values()):
        import openai

        cliente_openai = openai.OpenAI(api_key=SETTINGS.openai_api_key.get_secret_value())
        for info in (i for i in nativas.values() if i.backend == "openai"):
            assert cliente_openai.models.retrieve(info.model).id, info.model


def test_llm_devuelve_json_estructurado(providers: Providers) -> None:
    real("llm")
    inicio = time.perf_counter()
    resultado = ask_structured(
        providers.llm, "Redactas prompts de imagen.",
        [Message("user", "Ilustración abstracta para una infografía financiera.")], InfographicPrompt,
    )
    llamada = resultado.calls[-1]
    coste = text_result_cost(Tariffs.from_settings(SETTINGS), llamada)
    origen = "real" if llamada.cost_usd is not None else "estimado"
    medir("LLM", inicio, f"({llamada.tokens_in} tok in, {llamada.tokens_out} tok out, {coste:.5f} USD {origen})")
    assert resultado.value.prompt


def test_vision_lee_un_grafico(providers: Providers) -> None:
    real("vision")
    inicio = time.perf_counter()
    resultado = ask_structured_vision(
        providers.vision, demo_chart_png(), "image/png", "Describe este gráfico de velas.", ChartReading
    )
    medir("Visión", inicio, f"({resultado.calls[-1].tokens_in} tok in)")
    assert resultado.value.description


def test_tts_y_stt_dan_la_vuelta_completa(providers: Providers) -> None:
    """Sintetiza una frase y la transcribe: valida ambos proveedores con coste mínimo."""
    real("tts")
    inicio = time.perf_counter()
    voz = providers.tts.synthesize("Hola, esto es una prueba de FinLens.")
    medir("TTS", inicio, f"({len(voz.audio)} bytes)")
    assert voz.audio and voz.mime == "audio/mpeg"

    real("stt")
    inicio = time.perf_counter()
    texto = providers.stt.transcribe(voz.audio, "prueba.mp3")
    medir("STT", inicio, f"({texto.duration_s:.1f} s de audio)")
    assert "prueba" in texto.text.lower()


def test_imagen_se_genera(providers: Providers) -> None:
    real("image")
    inicio = time.perf_counter()
    imagen = providers.image.generate(
        "Ilustración abstracta y minimalista de formas ascendentes doradas sobre fondo oscuro, sin texto."
    )
    medir("Imagen", inicio, f"({len(imagen.image)} bytes, mime {imagen.mime})")
    assert imagen.image[:4] == b"\x89PNG" or imagen.image[:3] == b"\xff\xd8\xff" or imagen.image[:4] == b"RIFF"
