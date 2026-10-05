"""Tests de configuración y activación del modo demo."""
import pytest

from finlens.config import Settings

VARIABLES = (
    "DEMO_MODE", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_MODEL", "PRICE_STT_PER_MINUTE",
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


def test_con_ambas_claves_usa_apis_reales() -> None:
    settings = crear(anthropic_api_key="x", openai_api_key="y")
    assert not settings.is_demo
    assert settings.demo_reason is None


def test_una_sola_clave_sigue_en_demo() -> None:
    settings = crear(anthropic_api_key="x")
    assert settings.is_demo
    assert "OPENAI_API_KEY" in (settings.demo_reason or "")


def test_clave_en_blanco_cuenta_como_ausente() -> None:
    assert crear(anthropic_api_key="   ", openai_api_key="y").is_demo


def test_variables_de_entorno_sobrescriben_modelo_y_tarifa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "modelo-de-prueba")
    monkeypatch.setenv("PRICE_STT_PER_MINUTE", "0.01")
    settings = crear()
    assert settings.llm_model == "modelo-de-prueba"
    assert settings.price_stt_per_minute == 0.01


def test_las_claves_no_aparecen_en_el_repr() -> None:
    assert "secreto-123" not in repr(crear(anthropic_api_key="secreto-123"))
