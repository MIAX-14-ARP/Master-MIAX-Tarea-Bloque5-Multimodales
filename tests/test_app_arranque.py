"""La app de Streamlit arranca en modo demo sin claves."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from finlens.config import get_settings

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture(autouse=True)
def sin_claves(monkeypatch: pytest.MonkeyPatch) -> None:
    for nombre in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(nombre, "")
    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_app_arranca_en_modo_demo() -> None:
    at = AppTest.from_file(str(APP)).run()
    assert not at.exception
    html = "\n".join(m.value for m in at.markdown)
    assert 'class="fl-brand"' in html and "Fin<em>Lens</em>" in html  # mancheta
    assert "Modo demo" in html  # honestidad: se avisa de que todo es simulado
    assert html.count('class="fl-prov__cell') == html.count("fl-prov__cell is-mock") >= 5  # todas, simuladas
