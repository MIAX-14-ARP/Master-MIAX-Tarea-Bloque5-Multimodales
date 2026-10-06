"""Tests de la composición de la infografía (matplotlib + Pillow, sin red)."""
import io

from PIL import Image

from finlens.domain.grounding import FigureCheck
from finlens.domain.infographic import ANCHO, compose_infographic
from finlens.domain.schemas import AnalysisReport, ChartReading, Citation, KeyFigure
from finlens.providers.media import solid_png

CITA = [Citation(origin="documento", location="p.3")]
INFORME = AnalysisReport(
    summary="El margen mejoró. Segunda frase que no debe aparecer.",
    key_figures=[
        KeyFigure(name="Margen", value="18,4 %", period="FY2025", citations=CITA),
        KeyFigure(name="Inventada", value="99 %", citations=CITA),
    ],
    spoken_summary="x",
)
CHECKS = (
    FigureCheck("Margen", "18,4 %", "verificada", 3),
    FigureCheck("Inventada", "99 %", "no_encontrada", 3),
)
GRAFICO = ChartReading(trend="alcista", description="Máximos crecientes.")


def abrir(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png))


def test_devuelve_un_png_valido_del_ancho_configurado() -> None:
    png = compose_infographic(INFORME, CHECKS, GRAFICO)
    img = abrir(png)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and img.format == "PNG" and img.width == ANCHO


def test_con_ilustracion_cambia_la_cabecera() -> None:
    sin = abrir(compose_infographic(INFORME, CHECKS, GRAFICO)).convert("RGB")
    con = abrir(compose_infographic(INFORME, CHECKS, GRAFICO, solid_png(640, 480, (200, 40, 40)))).convert("RGB")
    assert sin.size == con.size
    assert sin.getpixel((ANCHO - 20, 20)) != con.getpixel((ANCHO - 20, 20))


def test_una_ilustracion_corrupta_degrada_a_cabecera_lisa() -> None:
    sin = compose_infographic(INFORME, CHECKS, GRAFICO)
    corrupta = compose_infographic(INFORME, CHECKS, GRAFICO, b"no es una imagen")
    assert abrir(corrupta).size == abrir(sin).size


def test_funciona_sin_cifras_verificadas_ni_grafico() -> None:
    img = abrir(compose_infographic(INFORME, (), None))
    assert img.width == ANCHO and img.height > 0


def test_el_alto_crece_con_el_numero_de_tarjetas() -> None:
    cifras = [KeyFigure(name=f"C{i}", value=f"{i} %", citations=CITA) for i in range(1, 7)]
    informe = AnalysisReport(summary="r", key_figures=cifras, spoken_summary="x")
    checks = tuple(FigureCheck(c.name, c.value, "verificada", 3) for c in cifras)
    grande = abrir(compose_infographic(informe, checks, GRAFICO)).height
    assert grande > abrir(compose_infographic(INFORME, CHECKS, GRAFICO)).height


def test_es_determinista() -> None:
    assert compose_infographic(INFORME, CHECKS, GRAFICO) == compose_infographic(INFORME, CHECKS, GRAFICO)
