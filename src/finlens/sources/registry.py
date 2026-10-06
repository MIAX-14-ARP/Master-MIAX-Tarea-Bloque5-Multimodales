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
from finlens.sources.mock import MockDerivatives, MockFundamentals, MockPrices
from finlens.sources.sec_edgar import SecEdgar
from finlens.sources.yahoo import YahooPrices


def resolve_market(ticker: str, hyperliquid: HyperliquidSource | None = None) -> MarketKind:
    """«cripto» si el símbolo cotiza en Hyperliquid (universo cacheado); si no, «accion».

    Limitación: un ticker de acción que coincida con el nombre de un perpetuo (raro) se tomaría por cripto.
    """
    simbolo = ticker.strip().upper()
    if not simbolo:
        raise SourceError("Indica un ticker.")
    fuente = hyperliquid or HyperliquidSource()
    return "cripto" if simbolo in fuente.universe() else "accion"


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
            return "cripto" if ticker.strip().upper() in {"BTC", "ETH", "SOL"} else "accion"
        assert isinstance(self.hyperliquid, HyperliquidSource)
        return resolve_market(ticker, self.hyperliquid)

    def prices(self, ticker: str, rango: str = "6mo") -> PriceSeries:
        fuente = self.hyperliquid if self.kind(ticker) == "cripto" else self.yahoo
        return fuente.fetch_prices(ticker, rango)

    def derivatives_for(self, ticker: str) -> DerivativesSnapshot | None:
        """Derivados solo para cripto; None para acciones."""
        if self.kind(ticker) != "cripto":
            return None
        return self.derivatives.fetch_derivatives(ticker)

    def fundamentals_for(self, ticker: str) -> Fundamentals | None:
        """Fundamentales SEC solo para acciones; None si es cripto o no reporta a la SEC."""
        if self.kind(ticker) == "cripto":
            return None
        return self.sec.fetch_fundamentals(ticker)


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
