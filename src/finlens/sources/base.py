"""Contratos de la capa de datos de mercado.

`domain/` y `orchestration/` solo dependen de este módulo; `httpx` vive únicamente en las
implementaciones de `sources/` (igual que los SDK de IA solo viven en `providers/`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

TIMEOUT_S = 20.0
MarketKind = Literal["cripto", "accion"]

# Rangos admitidos (mismo vocabulario que Yahoo Finance) y su duración aproximada en días naturales.
RANGE_DAYS = {"1mo": 31, "3mo": 92, "6mo": 183, "1y": 366, "2y": 731}
RANGO_POR_DEFECTO = "6mo"


class SourceError(Exception):
    """Fallo controlado de una fuente de datos (red, símbolo inexistente, respuesta inválida...)."""


def validar_rango(rango: str) -> str:
    """Devuelve el rango si es válido; si no, `SourceError` con los valores admitidos."""
    if rango not in RANGE_DAYS:
        raise SourceError(f"Rango «{rango}» no soportado. Usa uno de: {', '.join(RANGE_DAYS)}.")
    return rango


@dataclass(frozen=True)
class Candle:
    """Vela OHLCV. `t` es la apertura de la vela en UTC."""

    t: datetime
    o: float
    h: float
    l: float  # noqa: E741 - notación estándar OHLC
    c: float
    v: float


@dataclass(frozen=True)
class PriceSeries:
    """Serie de velas de un símbolo, con su origen y metadatos de la fuente."""

    symbol: str
    currency: str
    source: str  # "yahoo" | "hyperliquid" | "mock"
    candles: tuple[Candle, ...]
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DerivativesSnapshot:
    """Foto de derivados perpetuos (Hyperliquid) de un activo."""

    funding_hourly: float
    funding_annualized: float  # funding_hourly × 24 × 365
    open_interest: float  # en unidades del activo
    mark_px: float
    oracle_px: float
    day_notional_volume: float  # USD, 24 h
    prev_day_px: float


@dataclass(frozen=True)
class FundamentalFact:
    """Cifra anual oficial de un 10-K de la SEC."""

    tag: str  # etiqueta us-gaap
    label_es: str
    value: float
    unit: str
    fy: int
    end: str  # fin del ejercicio, ISO (YYYY-MM-DD)
    form: str
    accn: str


@dataclass(frozen=True)
class Fundamentals:
    """Fundamentales oficiales (SEC EDGAR) de una empresa."""

    company: str
    cik: int
    facts: tuple[FundamentalFact, ...]


@runtime_checkable
class PriceSource(Protocol):
    def fetch_prices(self, symbol: str, rango: str = RANGO_POR_DEFECTO) -> PriceSeries: ...


@runtime_checkable
class DerivativesSource(Protocol):
    def fetch_derivatives(self, symbol: str) -> DerivativesSnapshot: ...


@runtime_checkable
class FundamentalsSource(Protocol):
    def fetch_fundamentals(self, ticker: str) -> Fundamentals | None:
        """Fundamentales del ticker, o None si la empresa no reporta a la SEC."""
        ...
