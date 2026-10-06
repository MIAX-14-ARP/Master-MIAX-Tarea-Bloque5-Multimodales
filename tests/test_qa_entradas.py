"""QA de entradas: normalización de tickers, marcas de cripto, rangos y clasificación acción/cripto."""
import httpx2 as httpx
import pytest

from _mercado import cargar, cliente
from finlens.sources.base import RANGE_DAYS, SourceError, validar_rango
from finlens.sources.hyperliquid import HyperliquidSource
from finlens.sources.mock import CRIPTO_SIMULADAS, MockDerivatives, MockFundamentals, MockPrices
from finlens.sources.registry import (
    CRIPTOS_PRINCIPALES,
    MarketSources,
    build_sources,
    normalizar_ticker,
    resolve_market,
    simbolo_visible,
)
from finlens.sources.sec_edgar import SecEdgar


class SecFalsa(SecEdgar):
    """SEC sin red: solo conoce los tickers indicados."""

    def __init__(self, tickers: set[str], falla: bool = False) -> None:
        self._tickers = tickers
        self._falla = falla

    def cik_for(self, ticker: str) -> tuple[int, str] | None:
        if self._falla:
            raise SourceError("SEC caída")
        return (1, ticker) if ticker in self._tickers else None


def hl() -> HyperliquidSource:
    return HyperliquidSource(client=cliente(lambda r: httpx.Response(200, json=cargar("hl_meta_ctxs.json"))))


def hl_roto() -> HyperliquidSource:
    def roto(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("x", request=req)

    return HyperliquidSource(client=cliente(roto))


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("cripto:btc", ("BTC", True)),
        ("CRIPTO: eth", ("ETH", True)),
        (" btc-perp ", ("BTC", True)),
        ("ETH-USDT", ("ETH", True)),
        ("sol-usd", ("SOL", True)),
        ("itx.mc", ("ITX.MC", False)),
        ("^gspc", ("^GSPC", False)),
        ("  aapl ", ("AAPL", False)),
        ("-USD", ("-USD", False)),  # el sufijo solo no es un símbolo
    ],
)
def test_normalizar_ticker(entrada: str, esperado: tuple[str, bool]) -> None:
    assert normalizar_ticker(entrada) == esperado


@pytest.mark.parametrize("vacio", ["", "   ", "cripto:", "CRIPTO:  "])
def test_ticker_vacio_se_rechaza(vacio: str) -> None:
    with pytest.raises(SourceError, match="ticker"):
        resolve_market(vacio, hl())


def test_marca_explicita_es_cripto_sin_consultar_red() -> None:
    for t in ("cripto:MET", "MET-PERP", "AAPL-USD"):
        assert resolve_market(t, hl_roto(), SecFalsa({"MET", "AAPL"})) == "cripto"


def test_punto_o_circunflejo_es_accion_sin_consultar_red() -> None:
    assert resolve_market("BTC.MC", hl()) == "accion"
    assert resolve_market("^BTC", hl()) == "accion"


def test_ticker_de_la_sec_gana_a_hyperliquid() -> None:
    # ETH y BTC están en el universo de la fixture; MET-like: si la SEC lo conoce y no es cripto principal, es acción.
    universo = hl().universe()
    otro = next(t for t in sorted(universo) if t not in CRIPTOS_PRINCIPALES)
    assert resolve_market(otro, hl(), SecFalsa({otro})) == "accion"
    assert resolve_market(otro, hl(), SecFalsa(set())) == "cripto"


@pytest.mark.parametrize("ticker", sorted(CRIPTOS_PRINCIPALES))
def test_cripto_principal_gana_al_etf_de_la_sec(ticker: str) -> None:
    # BTC, ETH y XRP son también ETFs en la SEC (Grayscale, Bitwise): el usuario quiere la cripto.
    assert resolve_market(ticker, hl_roto(), SecFalsa({ticker})) == "cripto"
    assert resolve_market(ticker.lower(), hl_roto(), SecFalsa({ticker})) == "cripto"


def test_fallos_de_red_degradan_a_la_siguiente_regla() -> None:
    otro = next(t for t in sorted(hl().universe()) if t not in CRIPTOS_PRINCIPALES)
    assert resolve_market(otro, hl(), SecFalsa(set(), falla=True)) == "cripto"
    assert resolve_market(otro, hl_roto(), SecFalsa(set(), falla=True)) == "accion"


@pytest.mark.parametrize("rango", list(RANGE_DAYS))
def test_rangos_validos(rango: str) -> None:
    assert validar_rango(rango) == rango


@pytest.mark.parametrize("rango", ["", "5y", "6M", "6 mo", "max"])
def test_rangos_invalidos(rango: str) -> None:
    with pytest.raises(SourceError, match="no soportado"):
        validar_rango(rango)
    with pytest.raises(SourceError):
        MockPrices().fetch_prices("AAPL", rango)


def test_demo_clasifica_sin_red() -> None:
    fuentes = build_sources(demo=True)
    for t in CRIPTO_SIMULADAS:
        assert fuentes.kind(t.lower()) == "cripto"
        assert fuentes.fundamentals_for(t) is None
        assert fuentes.derivatives_for(t) is not None
    assert fuentes.kind("btc-usd") == "cripto"
    assert fuentes.kind("cripto:XYZ") == "cripto"
    for t in ("AAPL", "MET", "DASH", "ITX.MC"):
        assert fuentes.kind(t) == "accion"
        assert fuentes.derivatives_for(t) is None
    assert fuentes.fundamentals_for("AAPL") is not None


def test_demo_precios_de_cripto_marcada_usan_el_simbolo_limpio() -> None:
    fuentes = build_sources(demo=True)
    assert fuentes.prices("btc-perp").candles == fuentes.prices("BTC").candles


def test_mock_fundamentales_none_para_cripto_simulada() -> None:
    assert MockFundamentals().fetch_fundamentals(" btc ") is None
    assert MockFundamentals().fetch_fundamentals("AAPL") is not None


# --- Selector de mercado de la UI (prefijos accion:/cripto:) ---


def test_marca_accion_fuerza_accion_sin_consultar_red() -> None:
    # BTC es cripto principal, pero con «accion:» el usuario pide el ETF de la SEC.
    assert resolve_market("accion:BTC", hl_roto(), SecFalsa(set(), falla=True)) == "accion"
    assert resolve_market("ACCION: aapl", hl_roto()) == "accion"


@pytest.mark.parametrize("vacio", ["accion:", "ACCION:  "])
def test_marca_accion_sin_ticker_se_rechaza(vacio: str) -> None:
    with pytest.raises(SourceError, match="ticker"):
        resolve_market(vacio, hl())


def test_marca_cripto_valida_contra_hyperliquid() -> None:
    fuentes = MarketSources(yahoo=MockPrices(), hyperliquid=hl(), derivatives=MockDerivatives(), sec=MockFundamentals())
    with pytest.raises(SourceError, match="no cotiza en Hyperliquid"):
        fuentes.prices("cripto:AAPL")


def test_demo_respeta_las_marcas() -> None:
    fuentes = build_sources(demo=True)
    assert fuentes.kind("accion:BTC") == "accion"
    assert fuentes.prices("accion:btc").symbol == "BTC"
    assert fuentes.fundamentals_for("accion:aapl") == fuentes.fundamentals_for("AAPL") is not None
    assert fuentes.kind("cripto:AAPL") == "cripto"


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [("accion:aapl", "AAPL"), ("cripto:btc", "BTC"), ("ETH-USD", "ETH"), (" itx.mc ", "ITX.MC")],
)
def test_simbolo_visible(entrada: str, esperado: str) -> None:
    assert simbolo_visible(entrada) == esperado
