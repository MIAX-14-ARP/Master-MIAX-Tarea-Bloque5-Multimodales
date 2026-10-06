"""Contraseña de la demo pública (APP_PASSWORD): sin ella no se muestra la app."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from finlens.config import get_settings

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(autouse=True)
def demo_con_clave(monkeypatch: pytest.MonkeyPatch) -> None:
    for nombre in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(nombre, "")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("APP_PASSWORD", "clave-de-prueba")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _html(at: AppTest) -> str:
    return "\n".join(m.value for m in at.markdown)


def test_sin_contrasena_no_se_muestra_la_app() -> None:
    at = AppTest.from_file(str(APP)).run()
    assert not at.exception
    assert "Demo privada" in _html(at)
    assert 'class="fl-brand"' not in _html(at)


def test_contrasena_incorrecta_no_da_acceso() -> None:
    at = AppTest.from_file(str(APP)).run()
    at.text_input[0].input("otra")
    at.button[0].click().run()
    assert at.error and "incorrecta" in at.error[0].value
    assert 'class="fl-brand"' not in _html(at)


def test_contrasena_correcta_da_acceso() -> None:
    at = AppTest.from_file(str(APP)).run()
    at.text_input[0].input("clave-de-prueba")
    at.button[0].click().run()
    assert not at.exception
    assert 'class="fl-brand"' in _html(at)


def test_sin_app_password_el_acceso_es_libre(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_PASSWORD")
    at = AppTest.from_file(str(APP)).run()
    assert 'class="fl-brand"' in _html(at)
