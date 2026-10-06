"""Registro de fuentes (cripto vs acción) y fuentes simuladas deterministas."""
import json
from typing import Any

import httpx2 as httpx
import pytest

from _mercado import cargar, cliente
from finlens.domain.technicals import compute_technicals
from finlens.sources.base import DerivativesSource, FundamentalsSource, PriceSource, SourceError
from finlens.sources.hyperliquid import HyperliquidSource
from finlens.sources.mock import MockDerivatives, MockFundamentals, MockPrices
from finlens.sources.registry import MarketSources, build_sources, resolve_market


def hl() -> HyperliquidSource:
    return HyperliquidSource(client=cliente(lambda r: httpx.Response(200, json=cargar("hl_meta_ctxs.json"))))


def test_resolve_market() -> None:
    fuente = hl()
    assert resolve_market("BTC", fuente) == "cripto"
    assert resolve_market(" eth ", fuente) == "cripto"
    assert resolve_market("AAPL", fuente) == "accion"
    assert resolve_market("ITX.MC", fuente) == "accion"


def test_resolve_market_cachea_el_universo() -> None:
    llamadas: list[Any] = []

    def manejador(req: httpx.Request) -> httpx.Response:
        llamadas.append(json.loads(req.content))
        return httpx.Response(200, json=cargar("hl_meta_ctxs.json"))

    fuente = HyperliquidSource(client=cliente(manejador))
    for t in ("BTC", "AAPL", "ETH"):
        resolve_market(t, fuente)
    assert len(llamadas) == 1


def test_resolve_market_ticker_vacio_y_fallo_de_red() -> None:
    with pytest.raises(SourceError, match="ticker"):
        resolve_market("  ", hl())

    def roto(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x", request=req)

    # sin red se degrada a la regla por defecto en lugar de romper la clasificación
    assert resolve_market("HYPE", HyperliquidSource(client=cliente(roto))) == "accion"
    assert resolve_market("HYPE-PERP", HyperliquidSource(client=cliente(roto))) == "cripto"
    assert resolve_market("BTC", HyperliquidSource(client=cliente(roto))) == "cripto"  # cripto principal: sin red


def test_mock_cumple_protocolos() -> None:
    assert isinstance(MockPrices(), PriceSource)
    assert isinstance(MockDerivatives(), DerivativesSource)
    assert isinstance(MockFundamentals(), FundamentalsSource)


def test_mock_es_determinista_y_depende_del_simbolo() -> None:
    a1, a2, b = MockPrices().fetch_prices("ITX.MC"), MockPrices().fetch_prices("itx.mc"), MockPrices().fetch_prices("AAPL")
    assert a1 == a2
    assert [c.c for c in a1.candles] != [c.c for c in b.candles]
    assert a1.source == "mock" and a1.meta["simulado"] is True


def test_mock_velas_coherentes_y_tecnicos_calculables() -> None:
    s = MockPrices().fetch_prices("DEMO", "6mo")
    assert len(s.candles) >= 50
    assert all(c.l <= min(c.o, c.c) and c.h >= max(c.o, c.c) and c.v > 0 for c in s.candles)
    assert all(a.t < b.t for a, b in zip(s.candles, s.candles[1:], strict=False))
    assert compute_technicals(s).n_candles == len(s.candles)


def test_mock_rango_invalido() -> None:
    with pytest.raises(SourceError, match="Rango"):
        MockPrices().fetch_prices("X", "5y")


def test_mock_derivados_y_fundamentales() -> None:
    d = MockDerivatives().fetch_derivatives("BTC")
    assert d == MockDerivatives().fetch_derivatives("BTC")
    assert d.funding_annualized == pytest.approx(d.funding_hourly * 24 * 365)
    f = MockFundamentals().fetch_fundamentals("AAPL")
    assert f is not None and f.facts and f == MockFundamentals().fetch_fundamentals("AAPL")
    assert all(x.form == "10-K" and x.unit == "USD" for x in f.facts)


def test_build_sources_demo_no_usa_red() -> None:
    src = build_sources(demo=True)
    assert src.kind("BTC") == "cripto" and src.kind("ITX.MC") == "accion"
    assert src.prices("BTC").source == "mock"
    assert src.derivatives_for("BTC") is not None and src.derivatives_for("AAPL") is None
    assert src.fundamentals_for("AAPL") is not None and src.fundamentals_for("BTC") is None


def test_marketsources_enruta_segun_el_tipo() -> None:
    usados: list[str] = []

    class Falsa:
        def __init__(self, nombre: str) -> None:
            self.nombre = nombre

        def fetch_prices(self, symbol: str, rango: str = "6mo"):  # type: ignore[no-untyped-def]
            usados.append(self.nombre)
            return MockPrices().fetch_prices(symbol, rango)

    fuente_hl = hl()
    src = MarketSources(
        yahoo=Falsa("yahoo"), hyperliquid=Falsa("hl"), derivatives=MockDerivatives(), sec=MockFundamentals()
    )
    src.hyperliquid = Falsa("hl")
    # kind() usa el universo real de Hyperliquid: se inyecta el cliente grabado
    objeto = MarketSources(yahoo=Falsa("yahoo"), hyperliquid=fuente_hl, derivatives=fuente_hl, sec=MockFundamentals())
    assert objeto.kind("BTC") == "cripto" and objeto.kind("AAPL") == "accion"
    objeto.yahoo.fetch_prices("AAPL")
    assert usados == ["yahoo"]


def test_build_sources_real_construye_conectores_sin_red() -> None:
    src = build_sources(sec_user_agent="FinLens academic project a@b.es")
    assert not src.demo
    assert isinstance(src.hyperliquid, HyperliquidSource)
