"""Integración de datos de mercado (ticker) en el pipeline, con fuentes y proveedores simulados (sin red)."""
import dataclasses
from dataclasses import replace

import pytest

from finlens.domain.cost import Tariffs
from finlens.domain.grounding import check_figures
from finlens.domain.ingest import Chunk, IngestedDocument
from finlens.domain.prompts import build_analysis_messages, format_fundamentals, format_market
from finlens.domain.schemas import AnalysisReport, Citation, KeyFigure
from finlens.domain.technicals import compute_technicals
from finlens.orchestration.cache import cache_key
from finlens.orchestration.pipeline import (
    AnalysisInput,
    MarketContext,
    PipelineError,
    analyze,
    answer_followup,
    generate_media,
)
from finlens.providers.registry import build_mock_providers
from finlens.sources.base import PriceSeries, SourceError
from finlens.sources.mock import MockDerivatives, MockFundamentals, MockPrices
from finlens.sources.registry import MarketSources, build_sources

TARIFAS = Tariffs(3.0, 15.0, 0.006, 15.0, 0.04)
PNG = b"\x89PNG"


def pasos(resultado) -> dict:
    return {s.step: s for s in resultado.trace}


def correr(**kwargs):
    entrada = AnalysisInput(**{"pdf": b"", "ticker": "ACME", **kwargs})
    return analyze(build_mock_providers(), TARIFAS, entrada, sources=build_sources(demo=True))


def test_market_context_tiene_exactamente_los_campos_que_consume_la_ui() -> None:
    campos = [f.name for f in dataclasses.fields(MarketContext)]
    assert campos == ["series", "technicals", "derivatives", "fundamentals", "chart_check", "chart_png", "kind"]


def test_demo_completo_con_ticker_sin_pdf_ni_red() -> None:
    r = correr()
    nombres = list(pasos(r))
    for prefijo in ("Datos de mercado", "Indicadores técnicos", "Gráfico generado", "Fundamentales SEC",
                    "Contraste visión ↔ datos"):
        assert any(n.startswith(prefijo) for n in nombres), prefijo
    assert "Ingesta e índice" not in nombres and "Recuperación" not in nombres
    assert all(s.ok for s in r.trace) and not r.warnings
    m = r.market
    assert m is not None and m.series.symbol == "ACME" and m.technicals.symbol == "ACME"
    assert m.chart_png and m.chart_png.startswith(PNG) and m.kind == "accion"
    assert m.chart_check is not None and 0 <= m.chart_check.agreement_score <= 1
    assert m.fundamentals is not None and m.derivatives is None
    assert r.chart is not None and r.retriever is None and r.document.n_pages == 0
    assert "mercado" in r.question.lower() or "ACME" in r.question
    assert pasos(r)["Datos de mercado"].model == "mock" and pasos(r)["Fundamentales SEC"].model == "SEC EDGAR"


def test_los_pasos_de_mercado_corren_en_paralelo_con_started_s() -> None:
    r = correr(audio=b"RIFF....WAVE", audio_name="a.wav")
    assert all(s.started_s is not None for s in r.trace)
    assert pasos(r)["Datos de mercado"].parallel and pasos(r)["Fundamentales SEC"].parallel


def test_cripto_incluye_derivados() -> None:
    r = correr(ticker="BTC")
    assert r.market is not None and r.market.kind == "cripto" and r.market.derivatives is not None
    assert "con derivados" in pasos(r)["Datos de mercado"].note
    assert pasos(r)["Fundamentales SEC"].note.startswith("sin fundamentales")
    assert r.market.fundamentals is None


def test_con_grafico_subido_no_se_genera_otro_y_se_contrasta() -> None:
    from finlens.providers.media import solid_png

    r = correr(chart=solid_png(8, 8, (0, 0, 0)))
    assert "Gráfico generado" not in pasos(r) and "Contraste visión ↔ datos" in pasos(r)
    assert r.market is not None and r.market.chart_png is None


def test_con_pdf_y_ticker_se_combinan_ambas_fuentes() -> None:
    from test_logging import pdf_minimo

    r = correr(pdf=pdf_minimo(), question="margen")
    nombres = list(pasos(r))
    assert "Ingesta e índice" in nombres and "Recuperación" in nombres and "Datos de mercado" in nombres
    assert r.retriever is not None and r.market is not None


def test_el_mercado_llega_al_prompt_del_analista() -> None:
    capturado: list[str] = []

    class Espia(type(build_mock_providers().llm)):
        def complete(self, system, messages, max_tokens=2048):
            capturado.append(messages[-1].content)
            return super().complete(system, messages, max_tokens)

    providers = replace(build_mock_providers(), llm=Espia())
    analyze(providers, TARIFAS, AnalysisInput(pdf=b"", ticker="BTC"), sources=build_sources(demo=True))
    analista = next(c for c in capturado if "<mercado>" in c)
    assert "<sec>" not in analista and "Derivados (perpetuo)" in analista and "Tendencia determinista" in analista
    capturado.clear()
    analyze(providers, TARIFAS, AnalysisInput(pdf=b"", ticker="ACME"), sources=build_sources(demo=True))
    assert "<sec>" in next(c for c in capturado if "<mercado>" in c)


def test_un_fallo_de_fuente_es_warning_y_el_analisis_sigue() -> None:
    class Rota:
        def fetch_prices(self, symbol, rango="6mo"):
            raise SourceError("Yahoo no responde")

    fuentes = MarketSources(Rota(), Rota(), MockDerivatives(), MockFundamentals(), demo=True)
    r = analyze(build_mock_providers(), TARIFAS, AnalysisInput(pdf=b"", ticker="ACME"), sources=fuentes)
    assert r.market is None and r.report.summary
    assert any("Datos de mercado" in w and "Yahoo no responde" in w for w in r.warnings)
    assert not pasos(r)["Datos de mercado"].ok and "Indicadores técnicos" not in pasos(r)


def test_sec_caida_no_impide_el_resto() -> None:
    class SecRota:
        def fetch_fundamentals(self, ticker):
            raise SourceError("SEC 403")

    fuentes = MarketSources(MockPrices(), MockPrices(), MockDerivatives(), SecRota(), demo=True)
    r = analyze(build_mock_providers(), TARIFAS, AnalysisInput(pdf=b"", ticker="ACME"), sources=fuentes)
    assert r.market is not None and r.market.fundamentals is None
    assert any("Fundamentales SEC" in w for w in r.warnings)


def test_serie_demasiado_corta_no_tumba_el_analisis() -> None:
    class Corta:
        def fetch_prices(self, symbol, rango="6mo"):
            return PriceSeries(symbol, "USD", "mock", tuple(MockPrices().fetch_prices(symbol).candles[:5]))

    fuentes = MarketSources(Corta(), Corta(), MockDerivatives(), MockFundamentals(), demo=True)
    r = analyze(build_mock_providers(), TARIFAS, AnalysisInput(pdf=b"", ticker="ACME"), sources=fuentes)
    assert r.market is None and any("Indicadores técnicos" in w for w in r.warnings)
    assert "Gráfico generado" in pasos(r)  # el gráfico sí se genera y la visión lo lee
    assert r.chart is not None


def test_sin_pdf_ni_ticker_sigue_siendo_error_claro() -> None:
    with pytest.raises(PipelineError, match="vacío"):
        analyze(build_mock_providers(), TARIFAS, AnalysisInput(pdf=b""))


def test_sin_fuentes_explicitas_la_demo_usa_las_simuladas() -> None:
    r = analyze(build_mock_providers(), TARIFAS, AnalysisInput(pdf=b"", ticker="ACME"))
    assert r.market is not None and r.market.series.source == "mock"


def test_chat_y_medios_funcionan_sin_pdf() -> None:
    providers = build_mock_providers()
    r = analyze(providers, TARIFAS, AnalysisInput(pdf=b"", ticker="ACME"), sources=build_sources(demo=True))
    assert answer_followup(providers, TARIFAS, r, [], "¿y el riesgo?").answer.answer
    medios = generate_media(providers, TARIFAS, r)
    assert medios.image is not None and medios.audio is not None


def test_la_clave_de_cache_distingue_ticker_y_rango() -> None:
    base = AnalysisInput(pdf=b"", ticker="ACME")
    claves = {
        cache_key(i, demo=True, max_pdf_chars=1)
        for i in (base, replace(base, ticker="BTC"), replace(base, market_range="1y"), replace(base, ticker=" acme "))
    }
    assert len(claves) == 3  # «acme» == «ACME»


# --- Prompts y grounding de mercado / SEC -----------------------------------------------------


def serie_demo():
    return MockPrices().fetch_prices("ACME")


def test_format_market_y_fundamentals() -> None:
    tech = compute_technicals(serie_demo())
    texto = format_market(tech, MockDerivatives().fetch_derivatives("BTC"))
    assert "ACME" in texto and "RSI14" in texto and "funding anualizado" in texto
    sec = format_fundamentals(MockFundamentals().fetch_fundamentals("ACME"))
    assert "Ingresos" in sec and "FY2025" in sec and "M USD" in sec
    (m,) = build_analysis_messages("p", [], market=texto, sec=sec)
    assert "<mercado>" in m.content and "<sec>" in m.content


def informe(*cifras: tuple[str, str, str]) -> AnalysisReport:
    return AnalysisReport(
        summary="r", spoken_summary="r",
        key_figures=[
            KeyFigure(name=n, value=v, citations=[Citation(origin=o, location="")]) for n, v, o in cifras
        ],
    )


def test_grounding_contra_mercado_con_tolerancia_del_1_por_ciento() -> None:
    tech = compute_technicals(serie_demo())
    cierre = f"{tech.last_close:.2f}"
    casi = f"{tech.last_close * 1.005:.2f}"
    lejos = f"{tech.last_close * 1.05:.2f}"
    rentab = f"{tech.period_return * 100:.1f} %"
    informe_ = informe(
        ("Cierre", cierre, "mercado"), ("Cierre aprox", casi, "mercado"), ("Cierre lejos", lejos, "mercado"),
        ("Rentabilidad", rentab, "mercado"), ("RSI", f"{tech.rsi14:.1f}", "mercado"),
        ("Vol", "12.345.678 %", "mercado"),
    )
    r = check_figures(informe_, None, technicals=tech)
    estados = [c.status for c in r]
    assert estados == ["verificada", "verificada", "no_encontrada", "verificada", "verificada", "no_encontrada"]
    assert r[0].matched.startswith("Último cierre") and r[3].matched.startswith("Rentabilidad")


def test_grounding_contra_derivados() -> None:
    d = MockDerivatives().fetch_derivatives("BTC")
    r = check_figures(
        informe(("Funding", f"{d.funding_annualized * 100:.2f} %", "mercado"), ("Mark", f"{d.mark_px:.2f}", "mercado")),
        None, derivatives=d,
    )
    assert [c.status for c in r] == ["verificada", "verificada"]


def test_grounding_contra_sec_con_escalas() -> None:
    fund = MockFundamentals().fetch_fundamentals("ACME")
    ingresos = next(h for h in fund.facts if h.label_es == "Ingresos" and h.fy == 2025).value
    mm = f"{ingresos / 1e6:,.0f}".replace(",", ".")
    r = check_figures(
        informe(
            ("A", f"{mm} millones de USD", "sec"), ("B", f"${ingresos / 1e9:.1f} billion", "sec"),
            ("C", "$99.9 billion", "sec"), ("D", "5 %", "sec"),
        ),
        None, fundamentals=fund,
    )
    assert [c.status for c in r] == ["verificada", "verificada", "no_encontrada", "no_encontrada"]
    assert "Ingresos FY2025" in r[0].matched and r[0].page is None


def test_sin_fuente_comprobable_las_citas_mercado_y_sec_no_se_inventan() -> None:
    r = check_figures(informe(("X", "123,4", "mercado"), ("Y", "55", "sec")), None)
    assert [c.status for c in r] == ["no_encontrada", "no_encontrada"]  # citan una fuente que no se aportó


def test_cifra_con_documento_y_sec_se_verifica_con_cualquiera() -> None:
    doc = IngestedDocument(chunks=(Chunk(1, "Ventas de 1.234 millones."),), n_pages=1)
    fund = MockFundamentals().fetch_fundamentals("ACME")
    ingresos = next(h for h in fund.facts if h.label_es == "Ingresos").value
    cifra = KeyFigure(
        name="v", value=f"{ingresos / 1e6:,.0f} M".replace(",", "."),
        citations=[Citation(origin="documento", location="p.1"), Citation(origin="sec", location="")],
    )
    (r,) = check_figures(AnalysisReport(summary="r", spoken_summary="r", key_figures=[cifra]), doc, fundamentals=fund)
    assert r.status == "verificada" and r.page is None
