"""§0 Cerebro (red 3D de modelos) y vista de Mercado: datos de la escena, escape y tolerancia."""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from finlens.config import get_settings
from finlens.orchestration.trace import TraceStep
from finlens.providers.registry import build_mock_providers
from finlens.ui import brain
from finlens.ui import components as ui


@pytest.fixture(autouse=True)
def entorno_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")
    for nombre in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(nombre, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _nodos(datos: dict) -> dict[str, dict]:
    return {n["id"]: n for capa in datos["layers"] for n in capa["nodes"]}


def _resultado(pasos: list[TraceStep]) -> SimpleNamespace:
    informe = SimpleNamespace(key_figures=[], management_statements=[], correlations=[])
    checks = (SimpleNamespace(status="verificada"), SimpleNamespace(status="no_encontrada"))
    return SimpleNamespace(trace=tuple(pasos), report=informe, figure_checks=checks, total_seconds=1.0)


def test_en_reposo_solo_se_encienden_las_entradas_aportadas() -> None:
    datos = brain.build_brain(build_mock_providers(), aportes={"pdf", "question"}, detalles={"pdf": "1.5 MB"})
    nodos = _nodos(datos)
    assert datos["mode"] == "idle"
    assert nodos["in_pdf"]["state"] == "on" and nodos["in_pdf"]["value"] == "1.5 MB"  # tamaño, no «1.000»
    assert nodos["in_question"]["value"] == "aportado"
    assert nodos["in_audio"]["state"] == "off" and nodos["in_audio"]["value"] == "—"
    assert "in_ticker" not in nodos  # sin datos de mercado no se dibujan sus neuronas
    assert nodos["analysis"]["sub"].startswith("mock")  # proveedor y modelo reales de la capacidad
    assert all(len(e) == 2 and e[0] in nodos and e[1] in nodos for e in datos["edges"])


def test_la_reproduccion_sigue_el_orden_y_el_paralelismo_de_la_traza() -> None:
    pasos = [
        TraceStep("Ingesta e índice", "pypdf + TF-IDF", 1.0),
        TraceStep("Lectura del gráfico", "mock-vision", 2.0, parallel=True),
        TraceStep("Transcripción de audio", "mock-stt", 2.0, parallel=True),
        TraceStep("Análisis (LLM)", "mock-llm", 1.0),
        TraceStep("Resumen en audio", "—", 0.5, "sin saldo", ok=False),
    ]
    media = SimpleNamespace(trace=(), audio=None, image=None, total_seconds=0.0)
    datos = brain.build_brain(build_mock_providers(), aportes={"pdf", "chart", "audio"},
                              result=_resultado(pasos), media=media)
    n = _nodos(datos)
    assert datos["mode"] == "replay" and "5 pasos" in datos["headline"]
    assert n["vision"]["t0"] == n["stt"]["t0"] > n["ingest"]["t0"]  # visión ‖ STT arrancan a la vez
    assert n["analysis"]["t0"] >= n["vision"]["t1"]
    assert n["vision"]["state"] == "sim" and n["tts"]["state"] == "fail" and n["prompt"]["state"] == "off"
    assert n["out_figures"]["value"] == "1/2 ✓" and n["out_report"]["winner"] is True
    assert n["out_audio"]["state"] == "off" and n["out_report"]["t0"] > 0
    assert max(x["t1"] for x in n.values()) <= brain.PLAYBACK_S


def test_started_s_se_usa_si_existe() -> None:
    pasos = [TraceStep("Ingesta e índice", "p", 1.0), TraceStep("Análisis (LLM)", "l", 1.0)]
    for paso, inicio in zip(pasos, (0.0, 3.0), strict=True):
        object.__setattr__(paso, "started_s", inicio)
    horario = brain._schedule(pasos)
    assert horario["Análisis (LLM)"][0] - horario["Ingesta e índice"][1] > 1.0  # respeta el hueco real


def test_el_json_incrustado_no_puede_cerrar_el_script() -> None:
    datos = brain.build_brain(build_mock_providers(), aportes=set())
    datos["headline"] = "</script><script>alert(1)</script>"
    html = brain.brain_html(datos)
    bloque = re.search(r'<script type="application/json" id="fl-data">(.*?)</script>', html, re.S)
    assert bloque and json.loads(bloque.group(1))["headline"] == datos["headline"]
    assert "</script><script>alert" not in html
    assert brain.THREE_URL.startswith("https://cdnjs.cloudflare.com/") and "prefers-reduced-motion" in html


def test_contraste_vision_datos() -> None:
    from finlens.domain.chart_check import ChartCheck, ChartCheckItem

    check = ChartCheck(0.5, (
        ChartCheckItem("tendencia alcista", "confirmada", "pendiente +12 %"),
        ChartCheckItem("soporte en <b>90</b>", "discrepa", "mínimo del periodo 70,1"),
        ChartCheckItem("volumen creciente", "no_verificable", "sin dato"),
    ))
    html = ui.contrast_html(check)
    assert "50%" in html and "1 confirmadas · 1 discrepan · 1 no verificables" in html
    assert "La IA vio" in html and "Los datos dicen" in html and "&lt;b&gt;90" in html
    assert "fl-stamp v" in html and "fl-stamp x" in html and "fl-stamp s" in html


def _vista_mercado() -> None:
    from types import SimpleNamespace

    from finlens.domain.chart_check import ChartCheck, ChartCheckItem
    from finlens.domain.technicals import compute_technicals
    from finlens.sources.mock import MockDerivatives, MockFundamentals, MockPrices
    from finlens.ui import views

    serie = MockPrices().fetch_prices("ACME")
    mercado = SimpleNamespace(
        series=serie, technicals=compute_technicals(serie), derivatives=MockDerivatives().fetch_derivatives("BTC"),
        fundamentals=MockFundamentals().fetch_fundamentals("AAPL"), chart_png=None,
        chart_check=ChartCheck(1.0, (ChartCheckItem("tendencia", "confirmada", "ok"),)),
    )
    views.show_market(mercado)


def test_la_pestana_mercado_pinta_tecnicos_derivados_sec_y_contraste() -> None:
    at = AppTest.from_function(_vista_mercado, default_timeout=30).run()
    assert not at.exception
    texto = "\n".join(m.value for m in at.markdown)
    assert "La IA vio" in texto and "Indicadores técnicos" in texto and "RSI 14" in texto
    assert "Funding anualizado" in texto


def test_el_cerebro_esta_en_la_app() -> None:
    app = Path(__file__).resolve().parents[1] / "app.py"
    at = AppTest.from_file(str(app), default_timeout=60).run()
    assert not at.exception
    assert "Cerebro" in "\n".join(m.value for m in at.markdown)
