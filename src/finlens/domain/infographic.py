"""Composición determinista de la infografía: las cifras las escribe Python, no un modelo de imagen.

Los modelos de difusión escriben mal los números, así que la ilustración generada por IA (sin texto)
solo sirve de cabecera atenuada; el título, las tarjetas de cifras verificadas, la tendencia del
gráfico y el pie se dibujan con matplotlib (backend Agg) y Pillow. Si no hay ilustración se compone
igualmente con una cabecera lisa.
"""
from __future__ import annotations

import contextlib
import io
import threading
import re
import textwrap
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.patches import FancyBboxPatch, Polygon, Rectangle
from PIL import Image, ImageEnhance

from finlens.domain.grounding import FigureCheck
from finlens.domain.schemas import AnalysisReport, ChartReading

# --- ESTILO ----------------------------------------------------------------------------------
# Todo lo visual vive aquí: colores, fuentes y tamaños (en píxeles salvo los puntos de fuente).
# Paleta «terminal de research editorial», la misma que la UI (src/finlens/ui/theme.py):
# tinta cálida, hueso, un único acento latón; verde/rojo de mercado solo con significado.
COLOR_FONDO = "#12110E"
COLOR_TARJETA = "#1A1915"
COLOR_BORDE = "#3A372E"
COLOR_TEXTO = "#EDE6D6"
COLOR_TEXTO_SUAVE = "#BDB4A2"
COLOR_ACENTO = "#C8A24A"
COLOR_VERDE = "#6CC38A"
COLOR_ROJO = "#E8716A"

# Serif incluida en matplotlib (sin dependencias ni descargas): eco de la Fraunces de la UI.
FUENTE = "DejaVu Serif"
PT_TITULO = 30
PT_SUBTITULO = 14
PT_VALOR = 34
PT_ETIQUETA = 13
PT_PIE = 11

ANCHO, ALTO_MIN = 1200, 900  # el alto crece con el contenido
DPI = 100
MARGEN = 60
ALTO_CABECERA = 420
OPACIDAD_ILUSTRACION = 0.4  # 1 = ilustración intacta; menos = más atenuada hacia el fondo
TARJETA_ALTO = 190
TARJETA_HUECO = 24
COLUMNAS = 2
MAX_TARJETAS = 6
ALTO_TENDENCIA = 190
ALTO_PIE = 130

# Textos fijos (el diseñador puede cambiar mayúsculas, idioma o redacción).
TITULO = "FinLens · Resumen del análisis"
LEYENDA = "Generado con IA · Solo informativo"
ENCABEZADO_CIFRAS = "CIFRAS CLAVE VERIFICADAS EN EL DOCUMENTO"
ENCABEZADO_TENDENCIA = "TENDENCIA DEL GRÁFICO"
TEXTO_SIN_CIFRAS = "No hay cifras del documento que se hayan podido verificar."
ETIQUETA_FUENTES = "Fuentes"
SIN_FUENTES = "sin cifras verificadas en el documento"
# --- FIN ESTILO ------------------------------------------------------------------------------

_LOCK = threading.Lock()  # matplotlib (caché de fuentes, estado interno) no es seguro entre hilos


@dataclass(frozen=True)
class Card:
    """Tarjeta de cifra a dibujar: el valor es el literal del informe, sin reinterpretar."""

    name: str
    value: str
    period: str
    page: int | None


def cards_to_draw(
    report: AnalysisReport, checks: Sequence[FigureCheck], limit: int = MAX_TARJETAS
) -> list[Card]:
    """Cifras verificadas (excluye no_encontrada y sin fuente) emparejadas por índice con su check.

    Se empareja por posición y no por nombre: con nombres repetidos saldría una cifra no verificada.
    """
    if not checks:
        return []
    tarjetas = [
        Card(cifra.name, cifra.value, cifra.period, check.page)
        for cifra, check in zip(report.key_figures, checks, strict=True)
        if check.status == "verificada"
    ]
    return tarjetas[:limit]


def _ancho_en_caracteres(ancho_px: float, pt: float) -> int:
    """Caracteres aproximados que caben en `ancho_px` con una fuente de `pt` puntos."""
    return max(8, int(ancho_px / (pt * DPI / 72 * 0.6)))


def _ajustar_pt(texto: str, ancho_px: float, pt_max: float) -> float:
    """Reduce el tamaño de fuente hasta que `texto` quepa en `ancho_px`."""
    return min(pt_max, ancho_px / (max(len(texto), 1) * DPI / 72 * 0.65))


def _primera_frase(texto: str, limite: int = 220) -> str:
    frase = re.split(r"(?<=[.!?])\s", texto.strip(), maxsplit=1)[0]
    return textwrap.shorten(frase, width=limite, placeholder="…")


def _preparar_ilustracion(datos: bytes) -> Image.Image:
    """Recorta la ilustración a la cabecera y la atenúa hacia el color de fondo."""
    img = Image.open(io.BytesIO(datos)).convert("RGB")
    escala = max(ANCHO / img.width, ALTO_CABECERA / img.height)
    img = img.resize((max(1, round(img.width * escala)), max(1, round(img.height * escala))))
    izq, arriba = (img.width - ANCHO) // 2, (img.height - ALTO_CABECERA) // 2
    img = img.crop((izq, arriba, izq + ANCHO, arriba + ALTO_CABECERA))
    img = ImageEnhance.Color(img).enhance(0.8)
    fondo = Image.new("RGB", img.size, COLOR_FONDO)
    return Image.blend(fondo, img, OPACIDAD_ILUSTRACION)


def _flecha(ax: Any, tendencia: str, x: float, y: float, tam: float) -> str:
    """Dibuja el indicador de tendencia (triángulo/línea) y devuelve su color."""
    if tendencia == "alcista":
        color, pts = COLOR_VERDE, [(x, y + tam), (x + tam, y + tam), (x + tam / 2, y)]
    elif tendencia == "bajista":
        color, pts = COLOR_ROJO, [(x, y), (x + tam, y), (x + tam / 2, y + tam)]
    else:
        color = COLOR_TEXTO_SUAVE
        ax.add_patch(Rectangle((x, y + tam * 0.4), tam, tam * 0.2, color=color, lw=0))
        return color
    ax.add_patch(Polygon(pts, closed=True, color=color, lw=0))
    return color


def _paginas_fuente(checks: Sequence[FigureCheck]) -> str:
    paginas = sorted({c.page for c in checks if c.status == "verificada" and c.page})
    return ", ".join(f"p.{p}" for p in paginas) if paginas else SIN_FUENTES


def _compose(
    report: AnalysisReport,
    checks: Sequence[FigureCheck],
    chart: ChartReading | None = None,
    illustration: bytes | None = None,
) -> bytes:
    """Devuelve el PNG de la infografía. Las cifras son las del informe, sin reinterpretar.

    Solo se muestran como tarjetas las cifras `verificada` por `grounding.check_figures`.
    Una ilustración ilegible se ignora (se compone con cabecera lisa).
    """
    tarjetas = cards_to_draw(report, checks)
    filas = max(1, -(-len(tarjetas) // COLUMNAS))
    y_tarjetas = ALTO_CABECERA + 90
    y_fin = y_tarjetas + filas * (TARJETA_ALTO + TARJETA_HUECO) + 20
    alto = max(ALTO_MIN, y_fin + (ALTO_TENDENCIA if chart is not None else 0) + ALTO_PIE)

    fig = Figure(figsize=(ANCHO / DPI, alto / DPI), dpi=DPI, facecolor=COLOR_FONDO)
    FigureCanvasAgg(fig)
    ax = fig.add_axes((0, 0, 1, 1))
    ax.set_xlim(0, ANCHO)
    ax.set_ylim(alto, 0)
    ax.axis("off")
    # parse_math=False: un «$» en «$10.7bn ... $2bn» no debe interpretarse como mathtext.
    base: dict[str, Any] = {"family": FUENTE, "parse_math": False}

    # Cabecera: ilustración atenuada (si hay) y degradado hacia el fondo.
    ax.add_patch(Rectangle((0, 0), ANCHO, ALTO_CABECERA, color=COLOR_TARJETA, lw=0, zorder=0))
    if illustration:
        with contextlib.suppress(Exception):  # ilustración corrupta: se degrada a cabecera lisa
            ax.imshow(
                _preparar_ilustracion(illustration), extent=(0, ANCHO, ALTO_CABECERA, 0),
                aspect="auto", zorder=1,
            )
    ax.set_xlim(0, ANCHO)
    ax.set_ylim(alto, 0)
    ax.add_patch(Rectangle((0, ALTO_CABECERA - 6), ANCHO, 6, color=COLOR_ACENTO, lw=0))
    ax.text(MARGEN, 150, TITULO, color=COLOR_TEXTO, fontsize=PT_TITULO, fontweight="bold",
            va="center", **base)
    resumen = textwrap.wrap(_primera_frase(report.summary), _ancho_en_caracteres(ANCHO - 2 * MARGEN, PT_SUBTITULO))
    ax.text(MARGEN, 230, "\n".join(resumen[:4]), color=COLOR_TEXTO, fontsize=PT_SUBTITULO,
            va="top", linespacing=1.5, **base)

    # Tarjetas de cifras verificadas.
    y = ALTO_CABECERA + 50
    ax.text(MARGEN, y, "CIFRAS CLAVE VERIFICADAS EN EL DOCUMENTO", color=COLOR_ACENTO,
            fontsize=PT_ETIQUETA, fontweight="bold", va="center", **base)
    y += 40
    ancho_t = (ANCHO - 2 * MARGEN - (COLUMNAS - 1) * TARJETA_HUECO) / COLUMNAS
    for i, cifra in enumerate(tarjetas):
        x = MARGEN + (i % COLUMNAS) * (ancho_t + TARJETA_HUECO)
        yt = y + (i // COLUMNAS) * (TARJETA_ALTO + TARJETA_HUECO)
        ax.add_patch(FancyBboxPatch((x, yt), ancho_t, TARJETA_ALTO, boxstyle="round,pad=0,rounding_size=14",
                                    facecolor=COLOR_TARJETA, edgecolor=COLOR_BORDE, lw=1.5))
        ax.add_patch(Rectangle((x, yt + 18), 5, TARJETA_ALTO - 36, color=COLOR_ACENTO, lw=0))
        interior = ancho_t - 56
        etiqueta = textwrap.shorten(cifra.name, width=_ancho_en_caracteres(interior, PT_ETIQUETA), placeholder="…")
        ax.text(x + 30, yt + 38, etiqueta, color=COLOR_TEXTO_SUAVE, fontsize=PT_ETIQUETA, va="center", **base)
        ax.text(x + 30, yt + 100, cifra.value, color=COLOR_TEXTO,
                fontsize=_ajustar_pt(cifra.value, interior, PT_VALOR), fontweight="bold", va="center", **base)
        pagina = cifra.page
        detalle = " · ".join(p for p in (cifra.period, f"p.{pagina}" if pagina else "") if p)
        ax.text(x + 30, yt + 156, detalle, color=COLOR_TEXTO_SUAVE, fontsize=PT_ETIQUETA - 1, va="center", **base)
    if not tarjetas:
        ax.text(MARGEN, y + 30, "No hay cifras del documento que se hayan podido verificar.",
                color=COLOR_TEXTO_SUAVE, fontsize=PT_SUBTITULO, va="center", **base)
    y = y_fin

    # Tendencia del gráfico.
    if chart is not None:
        ax.text(MARGEN, y, "TENDENCIA DEL GRÁFICO", color=COLOR_ACENTO, fontsize=PT_ETIQUETA,
                fontweight="bold", va="center", **base)
        y += 34
        color = _flecha(ax, chart.trend, MARGEN, y, 34)
        ax.text(MARGEN + 56, y + 17, chart.trend.capitalize(), color=color, fontsize=PT_SUBTITULO + 4,
                fontweight="bold", va="center", **base)
        descripcion = textwrap.wrap(chart.description, _ancho_en_caracteres(ANCHO - 2 * MARGEN, PT_ETIQUETA))
        ax.text(MARGEN, y + 62, "\n".join(descripcion[:3]), color=COLOR_TEXTO_SUAVE, fontsize=PT_ETIQUETA,
                va="top", linespacing=1.5, **base)

    # Pie.
    ax.add_patch(Rectangle((MARGEN, alto - 110), ANCHO - 2 * MARGEN, 1.5, color=COLOR_BORDE, lw=0))
    ax.text(MARGEN, alto - 75, f"{LEYENDA} · {ETIQUETA_FUENTES}: {_paginas_fuente(checks)}", color=COLOR_TEXTO_SUAVE,
            fontsize=PT_PIE, va="center", **base)

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=DPI, facecolor=COLOR_FONDO)
    return buffer.getvalue()


def compose_infographic(
    report: AnalysisReport,
    checks: Sequence[FigureCheck],
    chart: ChartReading | None = None,
    illustration: bytes | None = None,
) -> bytes:
    """Devuelve el PNG de la infografía. Las cifras son las del informe, sin reinterpretar.

    Solo se muestran como tarjetas las cifras `verificada` por `grounding.check_figures`
    (ver `cards_to_draw`). Una ilustración ilegible se ignora (cabecera lisa).
    """
    with _LOCK:
        return _compose(report, checks, chart, illustration)
