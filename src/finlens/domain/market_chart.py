"""Gráfico de velas + volumen + SMA20/50 generado con matplotlib a partir de una `PriceSeries`.

Usa `Figure` + `FigureCanvasAgg` (sin pyplot): es seguro entre hilos. A propósito NO anota valores de
indicadores (ni RSI, ni valores de las medias, ni soportes): así, lo que el modelo de visión «lea» en la
imagen se puede contrastar de forma honesta con los números calculados en Python (`chart_check.py`).
"""
from __future__ import annotations

import io
from datetime import datetime

import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, MaxNLocator

from finlens.domain.infographic import (
    COLOR_ACENTO,
    COLOR_BORDE,
    COLOR_FONDO,
    COLOR_ROJO,
    COLOR_TARJETA,
    COLOR_TEXTO,
    COLOR_TEXTO_SUAVE,
    COLOR_VERDE,
    FUENTE,
)
from finlens.domain.technicals import sma
from finlens.sources.base import PriceSeries

# --- ESTILO ----------------------------------------------------------------------------------
ANCHO_PX, ALTO_PX, DPI = 1400, 900, 100
COLOR_SMA20 = COLOR_ACENTO
COLOR_SMA50 = "#8FB4D9"  # azul frío: único color extra, solo para distinguir las dos medias
GROSOR_SMA = 1.8
ANCHO_VELA = 0.68  # fracción del hueco entre velas
GROSOR_MECHA = 1.2
OPACIDAD_VOLUMEN = 0.55
PT_TITULO, PT_SUBTITULO, PT_EJE, PT_LEYENDA = 20, 11, 10, 10
RATIO_ALTURAS = (4.2, 1)  # precio : volumen
MAX_MARCAS_X = 8
# --- FIN ESTILO ------------------------------------------------------------------------------

_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
_FUENTES = {"yahoo": "Yahoo Finance", "hyperliquid": "Hyperliquid", "mock": "datos simulados"}


def _fecha(t: datetime) -> str:
    return f"{t.day} {_MESES[t.month - 1]} {t.year}"


def _formato_precio(valor: float, _pos: int | None = None) -> str:
    if abs(valor) >= 1000:
        return f"{valor:,.0f}"
    return f"{valor:,.2f}" if abs(valor) >= 1 else f"{valor:.4f}"


def _formato_volumen(valor: float, _pos: int | None = None) -> str:
    for umbral, sufijo in ((1e9, "G"), (1e6, "M"), (1e3, "K")):
        if abs(valor) >= umbral:
            return f"{valor / umbral:.1f}{sufijo}".replace(".0", "")
    return f"{valor:.0f}"


def _estilo_eje(ax: Axes) -> None:
    ax.set_facecolor(COLOR_TARJETA)
    for lado in ("top", "left"):
        ax.spines[lado].set_visible(False)
    for lado in ("bottom", "right"):
        ax.spines[lado].set_color(COLOR_BORDE)
    ax.yaxis.tick_right()
    ax.tick_params(colors=COLOR_TEXTO_SUAVE, labelsize=PT_EJE, length=3, color=COLOR_BORDE)
    ax.grid(axis="y", color=COLOR_BORDE, linewidth=0.6, alpha=0.7)
    ax.set_axisbelow(True)
    for etiqueta in ax.get_xticklabels() + ax.get_yticklabels():
        etiqueta.set_fontfamily(FUENTE)


def render_market_chart(serie: PriceSeries) -> bytes:
    """PNG (1400×900) con velas, volumen y SMA20/50. Lanza ValueError si hay menos de 2 velas."""
    velas = serie.candles
    if len(velas) < 2:
        raise ValueError("Se necesitan al menos 2 velas para dibujar el gráfico.")
    n = len(velas)
    x = np.arange(n, dtype=np.float64)
    o = np.array([c.o for c in velas])
    h = np.array([c.h for c in velas])
    low = np.array([c.l for c in velas])
    cierre = np.array([c.c for c in velas])
    vol = np.array([c.v for c in velas])
    sube = cierre >= o
    colores = np.where(sube, COLOR_VERDE, COLOR_ROJO)

    fig = Figure(figsize=(ANCHO_PX / DPI, ALTO_PX / DPI), dpi=DPI, facecolor=COLOR_FONDO)
    FigureCanvasAgg(fig)
    ax_p, ax_v = fig.subplots(
        2, 1, sharex=True, gridspec_kw={"height_ratios": RATIO_ALTURAS, "hspace": 0.04}
    )
    fig.subplots_adjust(left=0.05, right=0.92, top=0.85, bottom=0.09)

    # Velas: mecha (líneas verticales) + cuerpo (barras con altura mínima para las doji).
    ax_p.vlines(x, low, h, colors=list(colores), linewidth=GROSOR_MECHA, zorder=2)
    cuerpo = np.maximum(np.abs(cierre - o), (h.max() - low.min()) * 0.0012)
    ax_p.bar(x, cuerpo, bottom=np.minimum(o, cierre), width=ANCHO_VELA, color=list(colores), zorder=3)
    for periodo, color in ((20, COLOR_SMA20), (50, COLOR_SMA50)):
        media = sma(cierre, periodo)
        if not np.all(np.isnan(media)):
            ax_p.plot(x, media, color=color, linewidth=GROSOR_SMA, label=f"SMA {periodo}", zorder=4)
    margen = (h.max() - low.min()) * 0.05
    ax_p.set_ylim(low.min() - margen, h.max() + margen)
    ax_p.set_xlim(-1, n)
    ax_p.yaxis.set_major_formatter(FuncFormatter(_formato_precio))
    leyenda = ax_p.legend(loc="upper left", frameon=False, fontsize=PT_LEYENDA, labelcolor=COLOR_TEXTO_SUAVE)
    for texto in leyenda.get_texts():
        texto.set_fontfamily(FUENTE)

    ax_v.bar(x, vol, width=ANCHO_VELA, color=list(colores), alpha=OPACIDAD_VOLUMEN, zorder=2)
    ax_v.yaxis.set_major_formatter(FuncFormatter(_formato_volumen))
    ax_v.set_ylim(0, max(vol.max(), 1.0) * 1.15)
    ax_v.yaxis.set_major_locator(MaxNLocator(nbins=3, prune="upper"))
    ax_v.set_ylabel("Volumen", color=COLOR_TEXTO_SUAVE, fontsize=PT_EJE, fontfamily=FUENTE, labelpad=8)
    ax_v.yaxis.set_label_position("right")

    pasos = max(1, round(n / MAX_MARCAS_X))
    posiciones = list(range(0, n, pasos))
    ax_v.set_xticks(posiciones)
    ax_v.set_xticklabels([f"{velas[i].t.day} {_MESES[velas[i].t.month - 1]}" for i in posiciones])
    for ax in (ax_p, ax_v):
        _estilo_eje(ax)
    ax_p.tick_params(labelbottom=False)

    fuente = _FUENTES.get(serie.source, serie.source)
    fig.text(0.05, 0.945, serie.symbol, color=COLOR_TEXTO, fontsize=PT_TITULO + 6, fontfamily=FUENTE, fontweight="bold")
    fig.text(
        0.05, 0.895,
        f"{fuente}  ·  velas diarias  ·  {_fecha(velas[0].t)} – {_fecha(velas[-1].t)}"
        + (f"  ·  {serie.currency}" if serie.currency else ""),
        color=COLOR_TEXTO_SUAVE, fontsize=PT_SUBTITULO, fontfamily=FUENTE,
    )
    fig.add_artist(
        Line2D([0.05, 0.92], [0.875, 0.875], transform=fig.transFigure, color=COLOR_ACENTO, linewidth=1.2)
    )
    fig.text(0.92, 0.025, "FinLens · Solo informativo", color=COLOR_TEXTO_SUAVE, fontsize=9,
             fontfamily=FUENTE, ha="right")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, facecolor=COLOR_FONDO)
    return buf.getvalue()

