"""Tests de la agregación de mediciones."""
import pytest

from finlens.domain.cost import Tariffs
from finlens.orchestration.metrics import RunRecord, summarize, to_markdown
from finlens.orchestration.pipeline import AnalysisInput, analyze, generate_media
from finlens.orchestration.trace import TraceStep
from finlens.providers.registry import build_mock_providers
from finlens.ui.demo_samples import demo_audio_wav, demo_chart_png, demo_pdf

TARIFAS = Tariffs(2.0, 10.0, 0.006, 15.0, 0.04)


def registro(nombre: str, factor: float, falla_tts: bool = False) -> RunRecord:
    pasos = (
        TraceStep("Análisis (LLM)", "llm", 2.0 * factor, cost_usd=0.01 * factor, tokens_in=1000, tokens_out=500),
        TraceStep("Lectura del gráfico", "vision", 1.0 * factor, cost_usd=0.004, tokens_in=800, tokens_out=100),
        TraceStep("Transcripción de audio", "stt", 3.0 * factor, cost_usd=0.003, quantity=30, unit="s de audio"),
        TraceStep("Resumen en audio", "tts", 1.0, "falló" if falla_tts else "", 0.0 if falla_tts else 0.002,
                  ok=not falla_tts, quantity=0 if falla_tts else 400, unit="caracteres"),
    )
    return RunRecord(nombre, pasos, report_seconds=4.0 * factor, total_seconds=6.0 * factor)


def test_resumen_calcula_medias_y_maximos() -> None:
    resumen = summarize([registro("a", 1.0), registro("b", 3.0)])
    assert resumen.n_runs == 2
    assert resumen.mean_report_seconds == pytest.approx(8.0) and resumen.max_report_seconds == 12.0
    assert resumen.mean_total_seconds == pytest.approx(12.0)
    analisis = resumen.step("Análisis (LLM)")
    assert analisis.mean_seconds == pytest.approx(4.0) and analisis.max_seconds == 6.0
    assert analisis.mean_cost == pytest.approx(0.02) and analisis.mean_tokens_in == 1000
    assert resumen.mean_cost == pytest.approx((0.01 + 0.004 + 0.003 + 0.002 + 0.03 + 0.004 + 0.003 + 0.002) / 2)


def test_los_pasos_fallidos_se_cuentan_y_no_distorsionan_las_medias() -> None:
    resumen = summarize([registro("a", 1.0), registro("b", 1.0, falla_tts=True)])
    tts = resumen.step("Resumen en audio")
    assert (tts.runs_ok, tts.runs_failed) == (1, 1)
    assert tts.mean_quantity == 400 and tts.mean_cost == pytest.approx(0.002)


def test_sin_ejecuciones_falla_con_claridad() -> None:
    with pytest.raises(ValueError):
        summarize([])


def test_markdown_con_las_filas_del_readme_y_aviso_en_demo() -> None:
    resumen = summarize([registro("a", 1.0)])
    md = to_markdown(resumen, demo=True, models={"llm": "m"}, tariffs=TARIFAS, date="2026-10-06")
    assert "MODO DEMO" in md and "NO son válidas" in md
    assert "| LLM (tokens ent./sal.) | 1,800 / 600 |" in md  # análisis + visión
    assert "| STT | 0.5 min |" in md and "| TTS | 400.0 caracteres |" in md
    assert "| Imagen | no ejecutado | 0.0000 |" in md
    assert "| Análisis (LLM) | llm | 2.00 | 2.00 | 0 |" in md
    real = to_markdown(resumen, demo=False, models={}, tariffs=TARIFAS, date="2026-10-06")
    assert "MODO DEMO" not in real


def test_desde_resultados_reales_del_pipeline_en_demo() -> None:
    providers = build_mock_providers()
    entrada = AnalysisInput(pdf=demo_pdf(), question="¿margen?", chart=demo_chart_png(), audio=demo_audio_wav())
    analisis = analyze(providers, TARIFAS, entrada)
    medios = generate_media(providers, TARIFAS, analisis)
    resumen = summarize([RunRecord.from_results("demo", analisis, medios)])
    assert resumen.step("Transcripción de audio").mean_quantity == 45.0
    assert resumen.step("Resumen en audio").mean_quantity > 0
    assert resumen.step("Generación de infografía").mean_quantity == 1
    assert resumen.step("Análisis (LLM)").mean_tokens_in > 0
    assert resumen.mean_total_seconds >= resumen.mean_report_seconds
