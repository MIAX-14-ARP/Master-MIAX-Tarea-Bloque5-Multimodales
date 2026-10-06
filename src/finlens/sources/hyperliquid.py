"""Hyperliquid (perp DEX on-chain, API pública sin clave): velas, derivados y funding de cripto."""
from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import httpx2 as httpx

from finlens.sources.base import (
    RANGE_DAYS,
    TIMEOUT_S,
    Candle,
    DerivativesSnapshot,
    PriceSeries,
    SourceError,
    validar_rango,
)

URL = "https://api.hyperliquid.xyz/info"
MS_DIA = 86_400_000
HORAS_ANIO = 24 * 365


class HyperliquidSource:
    """Velas diarias y foto de derivados de Hyperliquid. Cachea el universo de activos en memoria."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = TIMEOUT_S) -> None:
        self._client = client or httpx.Client(timeout=timeout)
        self._universo: dict[str, str] | None = None  # MAYÚSCULAS -> nombre exacto en Hyperliquid
        self._ctxs: dict[str, dict[str, Any]] = {}

    # --- infraestructura ---
    def _post(self, cuerpo: dict[str, Any]) -> Any:
        try:
            resp = self._client.post(URL, json=cuerpo)
        except httpx.HTTPError as exc:
            raise SourceError(f"No se pudo conectar con Hyperliquid: {exc}") from exc
        if resp.status_code == 429:
            raise SourceError("Hyperliquid está limitando las peticiones (429). Inténtalo en unos minutos.")
        if resp.status_code >= 400:
            raise SourceError(f"Hyperliquid respondió con error HTTP {resp.status_code}.")
        try:
            return resp.json()
        except ValueError:
            raise SourceError("Hyperliquid devolvió una respuesta no válida.") from None

    def _cargar_meta(self) -> None:
        datos = self._post({"type": "metaAndAssetCtxs"})
        try:
            meta, ctxs = datos[0], datos[1]
            nombres = [u["name"] for u in meta["universe"]]
        except (KeyError, IndexError, TypeError):
            raise SourceError("Hyperliquid devolvió un universo de activos con formato inesperado.") from None
        self._universo = {n.upper(): n for n in nombres}
        self._ctxs = dict(zip(nombres, ctxs, strict=False))

    def universe(self) -> frozenset[str]:
        """Nombres (en mayúsculas) de los activos cotizados en Hyperliquid (cacheado)."""
        if self._universo is None:
            self._cargar_meta()
        return frozenset(self._universo or {})

    def _nombre(self, symbol: str) -> str:
        if self._universo is None:
            self._cargar_meta()
        universo = self._universo or {}
        simbolo = symbol.strip().upper()
        if simbolo not in universo:
            raise SourceError(f"«{symbol}» no cotiza en Hyperliquid.")
        return universo[simbolo]

    # --- datos ---
    def fetch_prices(self, symbol: str, rango: str = "6mo") -> PriceSeries:
        nombre = self._nombre(symbol)
        validar_rango(rango)
        ahora = int(time.time() * 1000)
        datos = self._post(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": nombre,
                    "interval": "1d",
                    "startTime": ahora - RANGE_DAYS[rango] * MS_DIA,
                    "endTime": ahora,
                },
            }
        )
        if not isinstance(datos, list) or not datos:
            raise SourceError(f"Hyperliquid no devolvió velas para «{nombre}».")
        try:
            velas = tuple(
                Candle(
                    t=datetime.fromtimestamp(x["t"] / 1000, tz=UTC),
                    o=float(x["o"]), h=float(x["h"]), l=float(x["l"]), c=float(x["c"]), v=float(x["v"]),
                )
                for x in datos
            )
        except (KeyError, TypeError, ValueError):
            raise SourceError("Hyperliquid devolvió velas con formato inesperado.") from None
        return PriceSeries(
            symbol=nombre, currency="USD", source="hyperliquid", candles=velas, meta={"interval": "1d"}
        )

    def fetch_derivatives(self, symbol: str) -> DerivativesSnapshot:
        nombre = self._nombre(symbol)
        self._cargar_meta()  # los contextos (funding, OI...) cambian: siempre frescos
        ctx = self._ctxs.get(nombre)
        if ctx is None:
            raise SourceError(f"Hyperliquid no devolvió contexto de mercado para «{nombre}».")
        try:
            funding = float(ctx["funding"])
            return DerivativesSnapshot(
                funding_hourly=funding,
                funding_annualized=funding * HORAS_ANIO,
                open_interest=float(ctx["openInterest"]),
                mark_px=float(ctx["markPx"]),
                oracle_px=float(ctx["oraclePx"]),
                day_notional_volume=float(ctx["dayNtlVlm"]),
                prev_day_px=float(ctx["prevDayPx"]),
            )
        except (KeyError, TypeError, ValueError):
            raise SourceError(
                f"Hyperliquid devolvió derivados con formato inesperado para «{nombre}»."
            ) from None
