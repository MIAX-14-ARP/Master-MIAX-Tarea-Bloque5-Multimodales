"""Exportación del análisis a PDF (demo del pipeline, sin red)."""
import io
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from pypdf import PdfReader

from finlens.domain.cost import Tariffs
from finlens.domain.guardrails import DISCLAIMER
from finlens.domain.schemas import AnalysisReport, Citation, Finding, KeyFigure
from finlens.export import build_report_pdf
from finlens.orchestration.pipeline import (
    AnalysisInput,
    AnalysisResult,
    MediaResult,
    analyze,
    generate_media,
)
from finlens.providers.base import ImageResult
from finlens.providers.registry import build_mock_providers
from finlens.sources.registry import build_sources

TARIFAS = Tariffs(3.0, 15.0, 0.006, 15.0, 0.04)
MUESTRA = Path(__file__).resolve().parents[1] / "samples" / "00_demo_ficticio"
FECHA = datetime(2026, 10, 7, 12, 0)


def texto(pdf: bytes) -> str:
    return " ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages)


def plano(pdf: bytes) -> str:
    """Texto del PDF sin saltos de línea ni espacios repetidos (el ajuste de línea los reparte)."""
    return " ".join(texto(pdf).split())


@pytest.fixture(scope="module")
def completo() -> tuple[AnalysisResult, MediaResult]:
    p = build_mock_providers()
    r = analyze(
        p, TARIFAS,
        AnalysisInput(
            pdf=(MUESTRA / "informe.pdf").read_bytes(), question=(MUESTRA / "pregunta.txt").read_text(encoding="utf-8"),
            chart=(MUESTRA / "grafico.png").read_bytes(), audio=(MUESTRA / "audio.wav").read_bytes(), ticker="ACME",
        ),
        sources=build_sources(demo=True),
    )
    return r, generate_media(p, TARIFAS, r)


def con_informe(r: AnalysisResult, **cambios: object) -> AnalysisResult:
    informe = r.report.model_copy(update=cambios)
    return replace(r, guard=replace(r.guard, report=informe))


def test_pdf_completo_contiene_resumen_cifra_verificada_y_aviso(completo) -> None:
    r, m = completo
    pdf = build_report_pdf(r, m, [("user", "¿Y la guía?"), ("assistant", "Se mantiene.")], generated_at=FECHA)
    assert pdf.startswith(b"%PDF")
    t = plano(pdf)
    assert r.report.summary in t
    assert r.report.key_figures[0].value in t
    assert "VERIFICADA" in t
    assert " ".join(DISCLAIMER.split()) in t
    for esperado in ("Cifras clave", "Lectura del gráfico", "La IA vio", "Fundamentales SEC", "Transcripción",
                     "Chat de seguimiento", "Traza de modelos", "Infografía", "07/10/2026"):
        assert esperado in t, esperado
    assert len(PdfReader(io.BytesIO(pdf)).pages) >= 3


def test_sin_medios_ni_chat_omite_esas_secciones(completo) -> None:
    r, _ = completo
    t = plano(build_report_pdf(r))
    assert "Infografía" not in t and "Chat de seguimiento" not in t and "Resumen" in t


def test_sin_mercado_omite_datos_de_mercado(completo) -> None:
    r, _ = completo
    t = plano(build_report_pdf(replace(r, market=None, chart_generated=None)))
    assert "Datos de mercado ·" not in t and "Fundamentales SEC EDGAR ·" not in t and "Cifras clave" in t


def test_solo_mercado_sin_pdf_ni_audio() -> None:
    r = analyze(build_mock_providers(), TARIFAS, AnalysisInput(pdf=b"", ticker="BTC"), sources=build_sources(demo=True))
    pdf = build_report_pdf(r)
    t = plano(pdf)
    assert pdf.startswith(b"%PDF") and "Derivados perpetuos" in t and "Transcripción" not in t


def test_contradicciones_y_fechas_por_defecto(completo) -> None:
    r, _ = completo
    c = Finding(statement="El gráfico sube pero el audio habla de caída", citations=[Citation(origin="audio")])
    t = plano(build_report_pdf(con_informe(r, contradictions=[c])))
    assert "Contradicciones detectadas" in t and "habla de caída" in t


def test_transcripcion_se_recorta(completo) -> None:
    r, _ = completo
    t = plano(build_report_pdf(replace(r, transcript="palabra " * 600)))
    assert "…" in t
    assert t.count("palabra") < 400


def test_imagenes_invalidas_se_omiten(completo) -> None:
    r, m = completo
    roto = replace(m, image=ImageResult(image=b"no soy un png", mime="image/png", model="x"))
    mercado = replace(r.market, chart_png=b"basura")
    pdf = build_report_pdf(replace(r, market=mercado), roto)
    assert pdf.startswith(b"%PDF") and "no se pudo incrustar" in plano(pdf)


RARO = "Emoji 🚀📈 <script>alert(1)</script> ✓ ↔ €  \x00\x07 ‮ tab\tfin"


@pytest.mark.parametrize("basura", [RARO, "x" * 10_000, "palabra " * 1500, "A" * 500 + "\n" * 50 + "B", ""])
def test_textos_arbitrarios_no_rompen_el_pdf(completo, basura: str) -> None:
    r, m = completo
    cita = [Citation(origin="documento", location=basura)]
    informe = dict(
        summary=basura or "resumen",
        key_figures=[KeyFigure(name=basura or "n", value=basura or "v", period=basura, citations=cita)],
        management_statements=[Finding(statement=basura or "s", citations=cita)],
        limitations=[basura],
    )
    pdf = build_report_pdf(con_informe(r, **informe), m, [("user", basura), ("assistant", basura)])
    assert pdf.startswith(b"%PDF")
    assert len(PdfReader(io.BytesIO(pdf)).pages) >= 1


def test_el_ejemplo_raro_conserva_el_texto_legible(completo) -> None:
    r, m = completo
    t = plano(build_report_pdf(con_informe(r, summary=RARO), m))
    assert "<script>alert(1)</script>" in t and "OK" in t and "€" in t and "🚀" not in t


def test_es_determinista_con_fecha_fija(completo) -> None:
    r, m = completo
    a = texto(build_report_pdf(r, m, generated_at=FECHA))
    assert a == texto(build_report_pdf(r, m, generated_at=FECHA))


def test_hilos_concurrentes(completo) -> None:
    from concurrent.futures import ThreadPoolExecutor

    r, m = completo
    with ThreadPoolExecutor(4) as ex:
        salidas = list(ex.map(lambda _: build_report_pdf(r, m), range(4)))
    assert all(s.startswith(b"%PDF") for s in salidas)


def test_informe_vacio_minimo(completo) -> None:
    r, _ = completo
    vacio = AnalysisReport(summary="Solo resumen", spoken_summary="x")
    pdf = build_report_pdf(replace(con_informe(r, **vacio.model_dump()), figure_checks=(), market=None))
    assert "Solo resumen" in plano(pdf)
