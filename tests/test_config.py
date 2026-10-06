"""Tests de configuración y activación del modo demo."""
import pytest

from finlens.config import Settings

VARIABLES = (
    "DEMO_MODE", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_MODEL",
    "PRICE_STT_PER_MINUTE", "LLM_MIN_OUTPUT_TOKENS", "LLM_PROVIDER", "OPENROUTER_LLM_MODEL",
)


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla los tests del entorno real del usuario."""
    for nombre in VARIABLES:
        monkeypatch.delenv(nombre, raising=False)


def crear(**kwargs: object) -> Settings:
    return Settings(_env_file=None, **kwargs)  # type: ignore[arg-type]


def test_sin_claves_es_demo() -> None:
    settings = crear()
    assert settings.is_demo
    assert "ANTHROPIC_API_KEY" in (settings.demo_reason or "")


def test_demo_mode_fuerza_demo_aunque_haya_claves() -> None:
    settings = crear(demo_mode=True, anthropic_api_key="x", openai_api_key="y")
    assert settings.is_demo
    assert "DEMO_MODE" in (settings.demo_reason or "")


def test_con_cualquier_clave_ya_no_es_demo_global() -> None:
    # La decisión fina es por capacidad (ver test_registry); aquí solo "todo simulado o no".
    for clave in ("openrouter_api_key", "anthropic_api_key", "openai_api_key"):
        settings = crear(**{clave: "x"})
        assert not settings.is_demo and settings.demo_reason is None


def test_clave_en_blanco_cuenta_como_ausente() -> None:
    settings = crear(openrouter_api_key="   ", anthropic_api_key=" ")
    assert settings.is_demo and not settings.has_openrouter_key and not settings.has_anthropic_key


def test_valores_por_defecto_de_openrouter_y_tokens() -> None:
    settings = crear()
    assert settings.llm_provider == "auto" and settings.image_provider == "auto"
    assert settings.openrouter_llm_model == "anthropic/claude-sonnet-5.5"
    assert settings.openrouter_tts_voice == "ef_dora" and settings.llm_min_output_tokens == 4000


def test_los_proveedores_y_modelos_se_leen_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("OPENROUTER_LLM_MODEL", "otro/modelo")
    monkeypatch.setenv("LLM_MIN_OUTPUT_TOKENS", "123")
    settings = crear()
    assert (settings.llm_provider, settings.openrouter_llm_model, settings.llm_min_output_tokens) == (
        "mock", "otro/modelo", 123,
    )


def test_variables_de_entorno_sobrescriben_modelo_y_tarifa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "modelo-de-prueba")
    monkeypatch.setenv("PRICE_STT_PER_MINUTE", "0.01")
    settings = crear()
    assert settings.llm_model == "modelo-de-prueba"
    assert settings.price_stt_per_minute == 0.01


def test_las_claves_no_aparecen_en_el_repr() -> None:
    assert "secreto-123" not in repr(crear(anthropic_api_key="secreto-123"))
    assert "secreto-456" not in repr(crear(openrouter_api_key="secreto-456"))


def test_sec_user_agent_se_lee_del_entorno(monkeypatch: pytest.MonkeyPatch) -> None:
    assert crear().sec_user_agent == ""
    monkeypatch.setenv("SEC_USER_AGENT", "FinLens academic project a@b.com")
    assert crear().sec_user_agent == "FinLens academic project a@b.com"
