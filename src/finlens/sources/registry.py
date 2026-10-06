"""Selección de fuente según el ticker y fábrica de conectores (real o simulado)."""
from __future__ import annotations

from dataclasses import dataclass

from finlens.sources.base import (
    DerivativesSnapshot,
    DerivativesSource,
    Fundamentals,
    FundamentalsSource,
    MarketKind,
    PriceSeries,
    PriceSource,
    SourceError,
)
from finlens.sources.hyperliquid import HyperliquidSource
from finlens.sources.mock import CRIPTO_SIMULADAS, MockDerivatives, MockFundamentals, MockPrices
from finlens.sources.sec_edgar import SecEdgar
from finlens.sources.yahoo import YahooPrices

PREFIJO_CRIPTO = "CRIPTO:"
PREFIJO_ACCION = "ACCION:"  # la UI lo antepone al elegir «Acción»: Yahoo + SEC, sin mirar Hyperliquid
SUFIJOS_CRIPTO = ("-PERP", "-USDT", "-USD")
# Criptos cuyo ticker sin marca es también un ETF en la SEC (BTC = Grayscale Bitcoin Mini Trust, ETH = Grayscale
# Ethereum Staking Mini, XRP = Bitwise XRP ETF): quien escribe «BTC» quiere la cripto, no el fondo.
# No incluye LTC, LINK, SUI o TRX: ahí el ticker es una empresa real (usar `LTC-PERP` o `cripto:LTC`).
CRIPTOS_PRINCIPALES = frozenset({"BTC", "ETH", "XRP", "SOL", "DOGE"})


def normalizar_ticker(ticker: str) -> tuple[str, bool]:
    """(símbolo limpio, ¿marcado explícitamente como cripto?).

    Marcas: prefijo `cripto:` o sufijo `-PERP`, `-USD`, `-USDT`; se quitan para consultar Hyperliquid
    (`BTC-USD` → `BTC`). Sin marca, el símbolo solo se pasa a mayúsculas y se recorta.
    """
    simbolo = ticker.strip().upper()
    explicito = False
    if simbolo.startswith(PREFIJO_CRIPTO):
        simbolo, explicito = simbolo[len(PREFIJO_CRIPTO) :].strip(), True
    for sufijo in SUFIJOS_CRIPTO:
        if simbolo.endswith(sufijo) and len(simbolo) > len(sufijo):
            simbolo, explicito = simbolo[: -len(sufijo)], True
            break
    return simbolo, explicito


def quitar_marca_accion(ticker: str) -> tuple[str, bool]:
    """(ticker sin el prefijo `accion:`, ¿lo llevaba?). El resto del ticker se deja tal cual."""
    limpio = ticker.strip()
    if limpio.upper().startswith(PREFIJO_ACCION):
        return limpio[len(PREFIJO_ACCION) :].strip(), True
    return limpio, False


def simbolo_visible(ticker: str) -> str:
    """Ticker para mostrar, sin las marcas de mercado (`accion:AAPL` → `AAPL`, `cripto:btc` → `BTC`)."""
    resto, es_accion = quitar_marca_accion(ticker)
    return resto.upper() if es_accion else normalizar_ticker(resto)[0]


def resolve_market(
    ticker: str,
    hyperliquid: HyperliquidSource | None = None,
    sec: SecEdgar | None = None,
) -> MarketKind:
    """Clasifica el ticker en «cripto» o «accion». Orden de reglas:

    0. prefijo `accion:` (elegido en la UI) → acción;
    1. marca explícita de cripto (`cripto:X`, `X-PERP`, `X-USD`, `X-USDT`) → cripto;
    2. símbolo con «.» o «^» (ITX.MC, ^GSPC) → acción, sin consultar Hyperliquid;
    3. cripto principal (BTC, ETH, XRP, SOL, DOGE) → cripto, aunque un ETF use ese ticker en la SEC;
    4. ticker en el mapa de la SEC → acción (MET, IP, DASH... existen también como perpetuos);
    5. símbolo en el universo de Hyperliquid → cripto;
    6. cualquier otro caso → acción.

    Los fallos de red de la SEC o de Hyperliquid no rompen la clasificación: se degrada a la siguiente regla.
    """
    resto, es_accion = quitar_marca_accion(ticker)
    if es_accion:
        if not resto:
            raise SourceError("Indica un ticker.")
        return "accion"
    simbolo, explicito = normalizar_ticker(ticker)
    if not simbolo:
        raise SourceError("Indica un ticker.")
    if explicito:
        return "cripto"
    if "." in simbolo or "^" in simbolo:
        return "accion"
    if simbolo in CRIPTOS_PRINCIPALES:
        return "cripto"
    if sec is not None:
        try:
            if sec.cik_for(simbolo) is not None:
                return "accion"
        except SourceError:
            pass
    try:
        if simbolo in (hyperliquid or HyperliquidSource()).universe():
            return "cripto"
    except SourceError:
        pass
    return "accion"


@dataclass
class MarketSources:
    """Conjunto de conectores que usa el pipeline. Con `demo=True` todo es simulado y sin red."""

    yahoo: PriceSource
    hyperliquid: PriceSource
    derivatives: DerivativesSource
    sec: FundamentalsSource
    demo: bool = False

    def kind(self, ticker: str) -> MarketKind:
        if self.demo:
            if quitar_marca_accion(ticker)[1]:
                return "accion"
            simbolo, explicito = normalizar_ticker(ticker)
            return "cripto" if explicito or simbolo in CRIPTO_SIMULADAS else "accion"
        hl = self.hyperliquid if isinstance(self.hyperliquid, HyperliquidSource) else None
        sec = self.sec if isinstance(self.sec, SecEdgar) else None
        return resolve_market(ticker, hl, sec)

    def prices(self, ticker: str, rango: str = "6mo") -> PriceSeries:
        if self.kind(ticker) == "cripto":
            return self.hyperliquid.fetch_prices(normalizar_ticker(ticker)[0], rango)
        return self.yahoo.fetch_prices(quitar_marca_accion(ticker)[0], rango)

    def derivatives_for(self, ticker: str) -> DerivativesSnapshot | None:
        """Derivados solo para cripto; None para acciones."""
        if self.kind(ticker) != "cripto":
            return None
        return self.derivatives.fetch_derivatives(normalizar_ticker(ticker)[0])

    def fundamentals_for(self, ticker: str) -> Fundamentals | None:
        """Fundamentales SEC solo para acciones; None si es cripto o no reporta a la SEC."""
        if self.kind(ticker) == "cripto":
            return None
        return self.sec.fetch_fundamentals(quitar_marca_accion(ticker)[0])


def build_sources(*, demo: bool = False, sec_user_agent: str = "") -> MarketSources:
    """Fábrica de conectores. `demo=True`: series simuladas deterministas, sin red."""
    if demo:
        return MarketSources(
            yahoo=MockPrices("mock"),
            hyperliquid=MockPrices("mock"),
            derivatives=MockDerivatives(),
            sec=MockFundamentals(),
            demo=True,
        )
    hl = HyperliquidSource()
    return MarketSources(
        yahoo=YahooPrices(),
        hyperliquid=hl,
        derivatives=hl,
        sec=SecEdgar(user_agent=sec_user_agent) if sec_user_agent else SecEdgar(),
    )
