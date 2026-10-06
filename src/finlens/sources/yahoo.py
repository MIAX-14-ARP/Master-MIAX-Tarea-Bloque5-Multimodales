"""Yahoo Finance (API no oficial, sin clave): precios diarios de acciones, ETF e índices.

Riesgo: no es una API oficial ni tiene SLA; puede cambiar o limitar sin aviso. En producción habría que
usar un proveedor con licencia (p.ej. BME Market Data para renta variable española).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx2 as httpx

from finlens.sources.base import TIMEOUT_S, Candle, PriceSeries, SourceError, validar_rango

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
CABECERAS = {"User-Agent": "Mozilla/5.0"}
_META_UTIL = (
    "currency", "symbol", "exchangeName", "fullExchangeName", "instrumentType", "longName", "shortName",
    "regularMarketPrice", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "timezone",
)
_LIMITE = "Yahoo Finance está limitando las peticiones (429). Inténtalo en unos minutos."


class YahooPrices:
    """Descarga velas diarias de Yahoo Finance."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = TIMEOUT_S) -> None:
        self._client = client or httpx.Client(timeout=timeout)

    def fetch_prices(self, symbol: str, rango: str = "6mo") -> PriceSeries:
        simbolo = symbol.strip().upper()
        if not simbolo:
            raise SourceError("Indica un ticker.")
        validar_rango(rango)
        try:
            resp = self._client.get(
                URL.format(symbol=simbolo), params={"range": rango, "interval": "1d"}, headers=CABECERAS
            )
        except httpx.HTTPError as exc:
            raise SourceError(f"No se pudo conectar con Yahoo Finance: {exc}") from exc
        if resp.status_code == 429:
            raise SourceError(_LIMITE)
        cuerpo = _json(resp)
        error = (cuerpo.get("chart") or {}).get("error")
        if error or resp.status_code == 404:
            raise SourceError(
                f"Yahoo Finance no conoce el símbolo «{simbolo}» "
                "(¿ticker incorrecto o sin sufijo de bolsa, p.ej. ITX.MC?)."
            )
        if resp.status_code >= 400:
            raise SourceError(f"Yahoo Finance respondió con error HTTP {resp.status_code}.")
        return _parsear(simbolo, cuerpo)


def _json(resp: httpx.Response) -> dict[str, Any]:
    try:
        cuerpo = resp.json()
    except ValueError:
        raise SourceError(f"Yahoo Finance devolvió una respuesta no válida (HTTP {resp.status_code}).") from None
    if not isinstance(cuerpo, dict):
        raise SourceError("Yahoo Finance devolvió una respuesta con formato inesperado.")
    return cuerpo


def _parsear(simbolo: str, cuerpo: dict[str, Any]) -> PriceSeries:
    try:
        resultado = cuerpo["chart"]["result"][0]
        marcas = resultado["timestamp"]
        q = resultado["indicators"]["quote"][0]
        abre, alto, bajo, cierre, volumen = q["open"], q["high"], q["low"], q["close"], q["volume"]
        meta_cruda = resultado["meta"]
    except (KeyError, IndexError, TypeError):
        raise SourceError(f"Yahoo Finance no devolvió datos de precios para «{simbolo}».") from None
    velas = []
    for i, ts in enumerate(marcas):
        if any(x is None for x in (abre[i], alto[i], bajo[i], cierre[i])):
            continue  # vela incompleta (festivo, sesión en curso): se descarta
        velas.append(
            Candle(
                t=datetime.fromtimestamp(ts, tz=UTC),
                o=float(abre[i]), h=float(alto[i]), l=float(bajo[i]), c=float(cierre[i]),
                v=float(volumen[i] or 0.0),
            )
        )
    if not velas:
        raise SourceError(f"Yahoo Finance no devolvió velas válidas para «{simbolo}».")
    return PriceSeries(
        symbol=str(meta_cruda.get("symbol", simbolo)),
        currency=str(meta_cruda.get("currency", "")),
        source="yahoo",
        candles=tuple(velas),
        meta={k: meta_cruda[k] for k in _META_UTIL if k in meta_cruda},
    )
