"""La app de Streamlit arranca en modo demo sin claves."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from finlens.config import get_settings

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(autouse=True)
def sin_claves(monkeypatch: pytest.MonkeyPatch) -> None:
    for nombre in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.setenv(nombre, "")
    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_app_arranca_en_modo_demo() -> None:
    at = AppTest.from_file(str(APP)).run()
    assert not at.exception
    assert at.title[0].value == "FinLens"
    assert any("Modo demo" in w.value for w in at.warning)
