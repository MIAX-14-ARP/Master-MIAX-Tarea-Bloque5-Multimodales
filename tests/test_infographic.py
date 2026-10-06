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


def test_los_dolares_no_se_interpretan_como_mathtext() -> None:
    cifras = [
        KeyFigure(name="Beneficio", value="$10.7bn", citations=CITA),
        KeyFigure(name="Inversión", value="$2bn · 12% / 5%", citations=CITA),
    ]
    informe = AnalysisReport(summary="Resultados en $ y %. Otra.", key_figures=cifras, spoken_summary="x")
    checks = tuple(FigureCheck(c.name, c.value, "verificada", 3) for c in cifras)
    png = compose_infographic(informe, checks, ChartReading(trend="alcista", description="Sube de $5 a $9"))
    assert abrir(png).width == ANCHO


def test_cards_to_draw_excluye_no_verificadas_y_empareja_por_indice() -> None:
    from finlens.domain.infographic import cards_to_draw

    cifras = [
        KeyFigure(name="Ventas", value="39.864 M", period="FY25", citations=CITA),
        KeyFigure(name="Ventas", value="99.999 M", citations=CITA),  # mismo nombre, no verificada
        KeyFigure(name="Margen", value="58,3 %", citations=CITA),
        KeyFigure(name="Audio", value="5 %", citations=CITA),
    ]
    informe = AnalysisReport(summary="r", key_figures=cifras, spoken_summary="x")
    checks = (
        FigureCheck("Ventas", "39.864 M", "verificada", 5),
        FigureCheck("Ventas", "99.999 M", "no_encontrada", 5),
        FigureCheck("Margen", "58,3 %", "verificada", 5),
        FigureCheck("Audio", "5 %", "sin_fuente_documental", None),
    )
    tarjetas = cards_to_draw(informe, checks)
    assert [(c.name, c.value, c.page) for c in tarjetas] == [("Ventas", "39.864 M", 5), ("Margen", "58,3 %", 5)]
    assert tarjetas[0].period == "FY25"
    assert len(cards_to_draw(informe, checks, limit=1)) == 1 and cards_to_draw(informe, ()) == []


def test_los_textos_fijos_estan_en_el_bloque_estilo() -> None:
    from pathlib import Path

    from finlens.domain import infographic

    fuente = Path(infographic.__file__).read_text(encoding="utf-8")
    estilo = fuente.split("# --- ESTILO")[1].split("# --- FIN ESTILO")[0]
    for texto in (infographic.TITULO, infographic.LEYENDA, infographic.ENCABEZADO_CIFRAS,
                  infographic.ENCABEZADO_TENDENCIA, infographic.TEXTO_SIN_CIFRAS):
        assert texto in estilo
        assert fuente.count(f'"{texto}"') == 1


def test_composicion_concurrente_es_segura() -> None:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as pool:
        salidas = list(pool.map(lambda _: compose_infographic(INFORME, CHECKS, GRAFICO), range(4)))
    assert len(set(salidas)) == 1
