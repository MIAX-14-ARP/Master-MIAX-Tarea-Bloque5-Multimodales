"""Utilidades compartidas por los tests de datos de mercado (sin red)."""
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2 as httpx

from finlens.sources.base import Candle, PriceSeries

FIXTURES = Path(__file__).parent / "fixtures"


def cargar(nombre: str) -> Any:
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


def cliente(manejador: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    """Cliente httpx cuyo «servidor» es `manejador`: ninguna petición sale a la red."""
    return httpx.Client(transport=httpx.MockTransport(manejador))


def serie_de_cierres(
    cierres: list[float], simbolo: str = "TEST", fuente: str = "yahoo", margen: float = 0.004
) -> PriceSeries:
    """Serie sintética diaria: apertura = cierre previo, mecha ±`margen`, volumen constante."""
    inicio = datetime(2026, 1, 1, tzinfo=UTC)
    velas = []
    previo = cierres[0]
    for i, c in enumerate(cierres):
        velas.append(
            Candle(
                t=inicio + timedelta(days=i), o=previo, h=max(previo, c) * (1 + margen),
                l=min(previo, c) * (1 - margen), c=c, v=1000.0,
            )
        )
        previo = c
    return PriceSeries(symbol=simbolo, currency="EUR", source=fuente, candles=tuple(velas))
