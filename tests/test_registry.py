"""Tests de la selección de proveedores por capacidad (claves y *_PROVIDER)."""
import pytest

from finlens.config import Settings
from finlens.providers import openrouter_provider as orp
from finlens.providers.anthropic_provider import AnthropicLLM, AnthropicVision
from finlens.providers.base import ProviderInfo
from finlens.providers.mock import MockImage, MockLLM, MockSTT, MockTTS, MockVision
from finlens.providers.openai_provider import OpenAIImage, OpenAISTT, OpenAITTS
from finlens.providers.registry import build_mock_providers, build_providers, resolve_backend

CAPACIDADES = ("llm", "vision", "stt", "tts", "image", "embeddings")
ENTORNO = (
    "DEMO_MODE", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    *(f"{c.upper()}_PROVIDER" for c in CAPACIDADES), "LLM_MIN_OUTPUT_TOKENS",
)


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch: pytest.MonkeyPatch) -> None:
    for nombre in ENTORNO:
        monkeypatch.delenv(nombre, raising=False)


def crear(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


def backends(providers) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return {i.capability: i.backend for i in providers.info}


def test_sin_claves_todo_es_mock_y_demo() -> None:
    p = build_providers(crear())
    assert p.is_demo and set(backends(p).values()) == {"mock"}
    assert p.mock_capabilities == CAPACIDADES and p.warnings == ()
    assert isinstance(p.llm, MockLLM) and isinstance(p.image, MockImage)


def test_build_mock_providers_describe_las_seis_capacidades() -> None:
    p = build_mock_providers()
    assert p.is_demo and p.mock_capabilities == CAPACIDADES
    assert p.info[0] == ProviderInfo("llm", "mock", "mock-llm")
    assert [i.capability for i in p.info] == list(CAPACIDADES)


def test_solo_openrouter_lo_usa_en_las_cinco_capacidades() -> None:
    p = build_providers(crear(openrouter_api_key="k"))
    assert not p.is_demo and p.mock_capabilities == ()
    assert set(backends(p).values()) == {"openrouter"}
    assert isinstance(p.llm, orp.OpenRouterLLM) and isinstance(p.vision, orp.OpenRouterVision)
    assert isinstance(p.stt, orp.OpenRouterSTT) and isinstance(p.tts, orp.OpenRouterTTS)
    assert isinstance(p.image, orp.OpenRouterImage)
    modelos = {i.capability: i.model for i in p.info}
    assert modelos == {
        "llm": "anthropic/claude-sonnet-5.5", "vision": "google/gemini-3.8-flash",
        "stt": "openai/whisper-large-v3-turbo", "tts": "hexgrad/kokoro-82m",
        "image": "black-forest-labs/flux.2-klein-4b", "embeddings": "baai/bge-m3",
    }
    assert p.tts._voice == "ef_dora"


def test_modelos_de_openrouter_configurables() -> None:
    p = build_providers(crear(openrouter_api_key="k", openrouter_llm_model="x/y", openrouter_tts_voice="v"))
    assert p.llm.model == "x/y" and p.tts._voice == "v"


def test_solo_claves_nativas_usan_anthropic_y_openai() -> None:
    p = build_providers(crear(anthropic_api_key="a", openai_api_key="o"))
    assert backends(p) == {
        "llm": "anthropic", "vision": "anthropic", "stt": "openai", "tts": "openai", "image": "openai",
        "embeddings": "openai",
    }
    assert isinstance(p.llm, AnthropicLLM) and isinstance(p.vision, AnthropicVision)
    assert isinstance(p.stt, OpenAISTT) and isinstance(p.tts, OpenAITTS) and isinstance(p.image, OpenAIImage)
    assert not p.is_demo and p.mock_capabilities == ()


def test_solo_anthropic_deja_voz_e_imagen_en_mock() -> None:
    p = build_providers(crear(anthropic_api_key="a"))
    assert p.mock_capabilities == ("stt", "tts", "image", "embeddings") and not p.is_demo
    assert isinstance(p.llm, AnthropicLLM) and isinstance(p.stt, MockSTT) and isinstance(p.tts, MockTTS)


def test_solo_openai_deja_llm_y_vision_en_mock() -> None:
    p = build_providers(crear(openai_api_key="o"))
    assert p.mock_capabilities == ("llm", "vision") and not p.is_demo
    assert isinstance(p.llm, MockLLM) and isinstance(p.vision, MockVision) and isinstance(p.image, OpenAIImage)


def test_openrouter_tiene_prioridad_sobre_las_nativas_en_auto() -> None:
    p = build_providers(crear(openrouter_api_key="r", anthropic_api_key="a", openai_api_key="o"))
    assert set(backends(p).values()) == {"openrouter"}


def test_demo_mode_fuerza_mock_aunque_haya_claves() -> None:
    p = build_providers(crear(demo_mode=True, openrouter_api_key="r", anthropic_api_key="a", openai_api_key="o"))
    assert p.is_demo and p.warnings == ()


def test_provider_explicito_por_capacidad_mezcla_backends() -> None:
    settings = crear(
        openrouter_api_key="r", anthropic_api_key="a", openai_api_key="o",
        llm_provider="anthropic", vision_provider="openrouter", stt_provider="openai",
        tts_provider="mock", image_provider="openrouter",
    )
    p = build_providers(settings)
    assert backends(p) == {
        "llm": "anthropic", "vision": "openrouter", "stt": "openai", "tts": "mock", "image": "openrouter",
        "embeddings": "openrouter",
    }
    assert p.mock_capabilities == ("tts",) and not p.is_demo and p.warnings == ()


def test_provider_mock_explicito_en_todo_es_demo() -> None:
    settings = crear(
        openrouter_api_key="r",
        **{f"{c}_provider": "mock" for c in CAPACIDADES},
    )
    assert build_providers(settings).is_demo


@pytest.mark.parametrize(
    ("capacidad", "backend"),
    [(c, b) for c in CAPACIDADES for b in ("openrouter", "anthropic", "openai")],
)
def test_proveedor_explicito_sin_su_clave_cae_a_mock_con_aviso(capacidad: str, backend: str) -> None:
    settings = crear(**{f"{capacidad}_provider": backend})
    nombre, aviso = resolve_backend(settings, capacidad)
    assert nombre == "mock" and aviso is not None
    assert capacidad.upper() in aviso or "no ofrece" in aviso


def test_el_aviso_nombra_la_clave_que_falta() -> None:
    p = build_providers(crear(llm_provider="openrouter"))
    assert p.warnings == (
        "LLM_PROVIDER=openrouter pero falta OPENROUTER_API_KEY: «llm» usa el modo simulado.",
    )
    assert p.mock_capabilities == CAPACIDADES


def test_proveedor_que_no_ofrece_la_capacidad_cae_a_mock() -> None:
    settings = crear(anthropic_api_key="a", openai_api_key="o", stt_provider="anthropic", llm_provider="openai")
    p = build_providers(settings)
    assert backends(p)["stt"] == "mock" and backends(p)["llm"] == "mock"
    assert len(p.warnings) == 2 and all("no ofrece" in w for w in p.warnings)


def test_valor_de_proveedor_desconocido_cae_a_mock_con_aviso() -> None:
    nombre, aviso = resolve_backend(crear(openrouter_api_key="r", tts_provider="inventado"), "tts")
    assert nombre == "mock" and "no es válido" in (aviso or "")


def test_el_valor_del_proveedor_no_distingue_mayusculas_ni_espacios() -> None:
    nombre, _ = resolve_backend(crear(openrouter_api_key="r", llm_provider=" OpenRouter "), "llm")
    assert nombre == "openrouter"


def test_claves_en_blanco_cuentan_como_ausentes() -> None:
    assert build_providers(crear(openrouter_api_key="  ")).is_demo


def test_anthropic_nativo_recibe_el_minimo_de_tokens_configurado() -> None:
    p = build_providers(crear(anthropic_api_key="a", llm_min_output_tokens=1234, llm_effort="high"))
    assert p.llm._min_output_tokens == 1234 and p.vision._min_output_tokens == 1234


def test_las_claves_no_se_filtran_en_info_ni_avisos() -> None:
    p = build_providers(crear(openrouter_api_key="secreto-xyz", llm_provider="anthropic"))
    assert "secreto-xyz" not in repr(p.info) + repr(p.warnings)


def test_openrouter_recibe_razonamiento_minimo_de_tokens_stt_y_embeddings() -> None:
    p = build_providers(crear(
        openrouter_api_key="k", openrouter_reasoning_effort="medium", openrouter_min_output_tokens=5000,
        stt_language="es", openrouter_stt_fallback_model="x/y", openrouter_embeddings_model="a/emb",
    ))
    for objeto in (p.llm, p.vision):
        assert objeto._reasoning_effort == "medium" and objeto._min_output_tokens == 5000
    assert p.stt._fallback == "x/y" and p.stt._language == "es"
    assert isinstance(p.embeddings, orp.OpenRouterEmbeddings) and p.embeddings.model == "a/emb"


def test_por_defecto_razonamiento_low_sin_idioma_forzado_y_respaldo_stt() -> None:
    p = build_providers(crear(openrouter_api_key="k"))
    assert p.llm._reasoning_effort == "low" and p.llm._min_output_tokens == 4000
    assert p.stt._language == "" and p.stt._fallback == "openai/gpt-4o-mini-transcribe"


def test_embeddings_provider_explicito_y_nativo() -> None:
    from finlens.providers.openai_provider import OpenAIEmbeddings

    p = build_providers(crear(openrouter_api_key="r", openai_api_key="o", embeddings_provider="openai"))
    assert isinstance(p.embeddings, OpenAIEmbeddings) and p.embeddings.model == "text-embedding-3-small"
    sin_clave = build_providers(crear(openrouter_api_key="r", embeddings_provider="openai"))
    assert backends(sin_clave)["embeddings"] == "mock" and "OPENAI_API_KEY" in sin_clave.warnings[0]


def test_tarifa_tts_segun_el_backend() -> None:
    assert crear(openrouter_api_key="k").effective_price_tts_per_mchar == 0.62
    assert crear(openai_api_key="k").effective_price_tts_per_mchar == 15.0
    assert crear(openrouter_api_key="k", tts_provider="openai").effective_price_tts_per_mchar == 15.0


def test_is_demo_es_robusto_sin_info() -> None:
    from dataclasses import replace

    mock = build_mock_providers()
    assert replace(mock, info=()).is_demo and replace(mock, info=()).mock_capabilities == CAPACIDADES
    real = build_providers(crear(openrouter_api_key="k"))
    assert not replace(real, info=()).is_demo and replace(real, info=()).mock_capabilities == ()
    parcial = replace(real, llm=mock.llm, info=())
    assert parcial.mock_capabilities == ("llm",) and not parcial.is_demo
