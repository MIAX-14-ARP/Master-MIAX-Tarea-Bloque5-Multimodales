"""Indicadores técnicos deterministas (numpy, sin IA) a partir de una `PriceSeries`.

Sirven de «verdad de referencia» para contrastar lo que el modelo de visión dice ver en el gráfico
(`chart_check.py`) y como métricas verificables para el LLM (`origin="mercado"`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from finlens.sources.base import MarketKind, PriceSeries

Tendencia = Literal["alcista", "bajista", "lateral"]
Floats = NDArray[np.float64]

# --- UMBRALES (documentados y ajustables) -----------------------------------------------------
MIN_VELAS = 10  # por debajo no se calculan indicadores con sentido
PERIODOS_ANIO = {"accion": 252, "cripto": 365}  # sesiones/días por año para anualizar la volatilidad
# Tendencia: la regresión lineal del cierre normalizado (cierre / cierre medio) se proyecta al periodo
# completo. Si el cambio proyectado supera ±5 % Y el último cierre está del mismo lado de la SMA de
# referencia (SMA50; SMA20 si hay menos de 50 velas), la tendencia es alcista/bajista; si no, lateral.
UMBRAL_TENDENCIA = 0.05
VENTANA_PIVOTE = 5  # un pivote es el máximo/mínimo de ±5 velas (confirmado, no incluye las últimas 5)
TOLERANCIA_AGRUPAR = 0.015  # pivotes a menos de un 1,5 % se funden en un solo nivel (media)
MAX_NIVELES = 3  # soportes y resistencias devueltos (los más cercanos al precio)
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TechnicalSummary:
    """Resumen técnico del periodo. Los precios están en la moneda de la serie; ratios en fracción (0,05 = 5 %)."""

    symbol: str
    source: str
    n_candles: int
    start: date
    end: date
    last_close: float
    period_return: float
    range_low: float
    range_low_date: date
    range_high: float
    range_high_date: date
    sma20: float | None
    sma50: float | None
    ema20: float | None
    rsi14: float | None
    volatility_annual: float | None
    max_drawdown: float  # ≤ 0
    trend: Tendencia
    trend_slope: float  # variación proyectada de la regresión sobre el periodo (fracción del cierre medio)
    above_sma50: bool | None  # None si no hay SMA50
    supports: tuple[float, ...]
    resistances: tuple[float, ...]
    periods_per_year: int


def sma(valores: Floats, n: int) -> Floats:
    """Media móvil simple; las primeras n-1 posiciones son NaN."""
    salida = np.full(len(valores), np.nan)
    if n <= 0 or len(valores) < n:
        return salida
    acumulado = np.cumsum(np.insert(valores, 0, 0.0))
    salida[n - 1 :] = (acumulado[n:] - acumulado[:-n]) / n
    return salida


def ema(valores: Floats, n: int) -> Floats:
    """Media móvil exponencial (alpha = 2/(n+1)) sembrada con la SMA de las n primeras velas."""
    salida = np.full(len(valores), np.nan)
    if n <= 0 or len(valores) < n:
        return salida
    alfa = 2.0 / (n + 1)
    salida[n - 1] = valores[:n].mean()
    for i in range(n, len(valores)):
        salida[i] = alfa * valores[i] + (1 - alfa) * salida[i - 1]
    return salida


def rsi_wilder(cierres: Floats, n: int = 14) -> float | None:
    """RSI con suavizado de Wilder; None si hay menos de n+1 cierres."""
    if len(cierres) < n + 1:
        return None
    delta = np.diff(cierres)
    ganancias, perdidas = np.maximum(delta, 0.0), np.maximum(-delta, 0.0)
    media_g, media_p = ganancias[:n].mean(), perdidas[:n].mean()
    for g, p in zip(ganancias[n:], perdidas[n:], strict=True):
        media_g = (media_g * (n - 1) + g) / n
        media_p = (media_p * (n - 1) + p) / n
    if media_p == 0:
        return 50.0 if media_g == 0 else 100.0
    return float(100.0 - 100.0 / (1.0 + media_g / media_p))


def annualized_volatility(cierres: Floats, periodos_anio: int) -> float | None:
    """Desviación típica (ddof=1) de los rendimientos logarítmicos diarios × √periodos."""
    if len(cierres) < 3:
        return None
    rend = np.diff(np.log(cierres))
    return float(rend.std(ddof=1) * np.sqrt(periodos_anio))


def max_drawdown(cierres: Floats) -> float:
    """Mayor caída desde un máximo previo (≤ 0), en fracción."""
    maximos = np.maximum.accumulate(cierres)
    return float(np.min(cierres / maximos - 1.0))


def trend_slope(cierres: Floats) -> float:
    """Pendiente de la regresión del cierre normalizado, proyectada al periodo completo."""
    media = cierres.mean()
    x = np.arange(len(cierres), dtype=np.float64)
    pendiente = np.polyfit(x, cierres / media, 1)[0]
    return float(pendiente * (len(cierres) - 1))


def classify_trend(pendiente_periodo: float, ultimo: float, sma_ref: float | None) -> Tendencia:
    """Alcista/bajista solo si la pendiente supera el umbral y el precio acompaña a la SMA de referencia."""
    if pendiente_periodo >= UMBRAL_TENDENCIA and (sma_ref is None or ultimo >= sma_ref):
        return "alcista"
    if pendiente_periodo <= -UMBRAL_TENDENCIA and (sma_ref is None or ultimo <= sma_ref):
        return "bajista"
    return "lateral"


def pivot_levels(altos: Floats, bajos: Floats, ventana: int = VENTANA_PIVOTE) -> list[float]:
    """Precios de los pivotes locales: máximos de `altos` y mínimos de `bajos` extremos en ±ventana velas."""
    n = len(altos)
    niveles: list[float] = []
    for i in range(ventana, n - ventana):
        zona_a = altos[i - ventana : i + ventana + 1]
        zona_b = bajos[i - ventana : i + ventana + 1]
        if altos[i] >= np.max(zona_a):
            niveles.append(float(altos[i]))
        if bajos[i] <= np.min(zona_b):
            niveles.append(float(bajos[i]))
    return niveles


def cluster_levels(niveles: list[float], tolerancia: float = TOLERANCIA_AGRUPAR) -> list[float]:
    """Funde niveles cercanos (≤ tolerancia relativa respecto al anterior del grupo) en su media."""
    if not niveles:
        return []
    ordenados = sorted(niveles)
    grupos: list[list[float]] = [[ordenados[0]]]
    for nivel in ordenados[1:]:
        if nivel <= grupos[-1][-1] * (1 + tolerancia):
            grupos[-1].append(nivel)
        else:
            grupos.append([nivel])
    return [float(np.mean(g)) for g in grupos]


def support_resistance(
    altos: Floats, bajos: Floats, ultimo: float
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Soportes (niveles bajo el último cierre) y resistencias (sobre él), los `MAX_NIVELES` más cercanos."""
    niveles = cluster_levels(pivot_levels(altos, bajos))
    soportes = sorted((n for n in niveles if n < ultimo), reverse=True)[:MAX_NIVELES]
    resistencias = sorted(n for n in niveles if n >= ultimo)[:MAX_NIVELES]
    return tuple(soportes), tuple(resistencias)


def _ultimo(serie: Floats) -> float | None:
    valor = serie[-1] if len(serie) else np.nan
    return None if np.isnan(valor) else float(valor)


def compute_technicals(serie: PriceSeries, mercado: MarketKind | None = None) -> TechnicalSummary:
    """Calcula el `TechnicalSummary`. `mercado` fija la anualización; por defecto se infiere de la fuente."""
    if len(serie.candles) < MIN_VELAS:
        raise ValueError(f"Se necesitan al menos {MIN_VELAS} velas para calcular indicadores.")
    if mercado is None:
        mercado = "cripto" if serie.source == "hyperliquid" else "accion"
    ppy = PERIODOS_ANIO[mercado]
    cierres = np.array([c.c for c in serie.candles], dtype=np.float64)
    altos = np.array([c.h for c in serie.candles], dtype=np.float64)
    bajos = np.array([c.l for c in serie.candles], dtype=np.float64)
    fechas = [c.t.date() for c in serie.candles]

    ultimo = float(cierres[-1])
    sma20, sma50 = _ultimo(sma(cierres, 20)), _ultimo(sma(cierres, 50))
    pendiente = trend_slope(cierres)
    i_min, i_max = int(np.argmin(bajos)), int(np.argmax(altos))
    soportes, resistencias = support_resistance(altos, bajos, ultimo)
    return TechnicalSummary(
        symbol=serie.symbol,
        source=serie.source,
        n_candles=len(cierres),
        start=fechas[0],
        end=fechas[-1],
        last_close=ultimo,
        period_return=float(cierres[-1] / cierres[0] - 1.0),
        range_low=float(bajos[i_min]),
        range_low_date=fechas[i_min],
        range_high=float(altos[i_max]),
        range_high_date=fechas[i_max],
        sma20=sma20,
        sma50=sma50,
        ema20=_ultimo(ema(cierres, 20)),
        rsi14=rsi_wilder(cierres, 14),
        volatility_annual=annualized_volatility(cierres, ppy),
        max_drawdown=max_drawdown(cierres),
        trend=classify_trend(pendiente, ultimo, sma50 if sma50 is not None else sma20),
        trend_slope=pendiente,
        above_sma50=None if sma50 is None else ultimo >= sma50,
        supports=soportes,
        resistances=resistencias,
        periods_per_year=ppy,
    )
