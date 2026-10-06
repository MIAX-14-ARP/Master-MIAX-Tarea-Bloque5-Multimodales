"""Fuentes simuladas y deterministas para la demo y los tests (sin red)."""
from __future__ import annotations

import zlib
from datetime import UTC, datetime, timedelta

import numpy as np

from finlens.sources.base import (
    RANGE_DAYS,
    Candle,
    DerivativesSnapshot,
    FundamentalFact,
    Fundamentals,
    PriceSeries,
    validar_rango,
)

CRIPTO_SIMULADAS = frozenset({"BTC", "ETH", "SOL"})  # en demo se tratan como cripto (sin SEC)
FIN_SIMULADO = datetime(2026, 6, 30, tzinfo=UTC)  # fecha fija: la serie no depende del reloj
_CIFRAS_MUSD = (  # (tag, etiqueta, valor del último ejercicio en M USD)
    ("RevenueFromContractWithCustomerExcludingAssessedTax", "Ingresos", 12_500.0),
    ("NetIncomeLoss", "Beneficio neto", 1_800.0),
    ("Assets", "Activos totales", 20_400.0),
)


def _semilla(texto: str) -> int:
    return zlib.crc32(texto.upper().encode())  # estable entre procesos (hash() no lo es)


class MockPrices:
    """Serie sintética reproducible (paseo aleatorio con semilla derivada del símbolo)."""

    def __init__(self, source: str = "mock") -> None:
        self._source = source

    def fetch_prices(self, symbol: str, rango: str = "6mo") -> PriceSeries:
        validar_rango(rango)
        simbolo = symbol.strip().upper() or "DEMO"
        n = max(20, round(RANGE_DAYS[rango] * 5 / 7))
        rng = np.random.default_rng(_semilla(simbolo))
        base = 20 + (_semilla(simbolo) % 180)
        cierres = base * np.exp(np.cumsum(rng.normal(0.0006, 0.015, n)))
        velas = []
        previo = float(base)
        for i, cierre in enumerate(cierres):
            c = float(cierre)
            o = previo
            h = max(o, c) * (1 + float(rng.uniform(0.001, 0.012)))
            low = min(o, c) * (1 - float(rng.uniform(0.001, 0.012)))
            v = float(rng.uniform(0.6, 1.4) * 1_000_000)
            velas.append(Candle(t=FIN_SIMULADO - timedelta(days=n - 1 - i), o=o, h=h, l=low, c=c, v=v))
            previo = c
        return PriceSeries(
            symbol=simbolo, currency="USD", source=self._source, candles=tuple(velas), meta={"simulado": True}
        )


class MockDerivatives:
    def fetch_derivatives(self, symbol: str) -> DerivativesSnapshot:
        rng = np.random.default_rng(_semilla(symbol))
        funding = float(rng.uniform(-0.00005, 0.00015))
        px = float(20 + (_semilla(symbol) % 180))
        return DerivativesSnapshot(
            funding_hourly=funding,
            funding_annualized=funding * 24 * 365,
            open_interest=float(rng.uniform(1_000, 50_000)),
            mark_px=px,
            oracle_px=px * 0.9995,
            day_notional_volume=float(rng.uniform(1e8, 2e9)),
            prev_day_px=px * 0.99,
        )


class MockFundamentals:
    def fetch_fundamentals(self, ticker: str) -> Fundamentals | None:
        simbolo = ticker.strip().upper()
        if simbolo in CRIPTO_SIMULADAS:
            return None  # las criptomonedas no reportan a la SEC
        escala = 1 + (_semilla(simbolo) % 5) / 10
        hechos = []
        for tag, etiqueta, musd in _CIFRAS_MUSD:
            for k, fy in enumerate((2025, 2024, 2023)):
                hechos.append(
                    FundamentalFact(
                        tag=tag,
                        label_es=etiqueta,
                        value=musd * 1e6 * escala * (0.92**k),
                        unit="USD",
                        fy=fy,
                        end=f"{fy}-12-31",
                        form="10-K",
                        accn=f"0000000000-{fy % 100}-000001",
                    )
                )
        return Fundamentals(company=f"{simbolo} (simulado)", cik=0, facts=tuple(hechos))
