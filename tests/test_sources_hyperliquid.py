"""Conector de Hyperliquid con respuestas reales grabadas (BTC 1d, metaAndAssetCtxs recortado)."""
import json
from collections.abc import Callable
from typing import Any

import httpx2 as httpx
import pytest

from _mercado import cargar, cliente
from finlens.sources.base import DerivativesSource, PriceSource, SourceError
from finlens.sources.hyperliquid import HyperliquidSource


def servidor(registro: list[dict[str, Any]]) -> Callable[[httpx.Request], httpx.Response]:
    def manejador(req: httpx.Request) -> httpx.Response:
        cuerpo = json.loads(req.content)
        registro.append(cuerpo)
        if cuerpo["type"] == "metaAndAssetCtxs":
            return httpx.Response(200, json=cargar("hl_meta_ctxs.json"))
        if cuerpo["type"] == "candleSnapshot":
            return httpx.Response(200, json=cargar("hl_candles_btc_1d.json"))
        return httpx.Response(400, text="tipo desconocido")

    return manejador


def test_velas_btc_convierte_strings_a_float() -> None:
    registro: list[dict[str, Any]] = []
    fuente = HyperliquidSource(client=cliente(servidor(registro)))
    serie = fuente.fetch_prices("btc", "6mo")
    assert serie.symbol == "BTC" and serie.currency == "USD" and serie.source == "hyperliquid"
    assert len(serie.candles) == 121
    c = serie.candles[0]
    assert isinstance(c.o, float) and c.h >= c.l and c.v > 0
    assert c.t.tzinfo is not None
    peticion = next(r for r in registro if r["type"] == "candleSnapshot")["req"]
    assert peticion["coin"] == "BTC" and peticion["interval"] == "1d"
    assert 0 < peticion["endTime"] - peticion["startTime"] <= 183 * 86_400_000 + 1


def test_cumple_protocolos() -> None:
    fuente = HyperliquidSource(client=cliente(servidor([])))
    assert isinstance(fuente, PriceSource) and isinstance(fuente, DerivativesSource)


def test_derivados_se_alinean_por_posicion() -> None:
    d = HyperliquidSource(client=cliente(servidor([]))).fetch_derivatives("ETH")
    datos = cargar("hl_meta_ctxs.json")
    ctx = datos[1][1]  # ETH es el segundo del universo recortado
    assert datos[0]["universe"][1]["name"] == "ETH"
    assert d.funding_hourly == float(ctx["funding"])
    assert d.funding_annualized == pytest.approx(float(ctx["funding"]) * 24 * 365)
    assert d.open_interest == float(ctx["openInterest"])
    assert d.mark_px == float(ctx["markPx"]) and d.oracle_px == float(ctx["oraclePx"])
    assert d.day_notional_volume == float(ctx["dayNtlVlm"]) and d.prev_day_px == float(ctx["prevDayPx"])


def test_universo_cacheado_y_sin_distinguir_mayusculas() -> None:
    registro: list[dict[str, Any]] = []
    fuente = HyperliquidSource(client=cliente(servidor(registro)))
    assert {"BTC", "ETH"} <= fuente.universe()
    fuente.universe()
    fuente.fetch_prices("eth")
    assert sum(1 for r in registro if r["type"] == "metaAndAssetCtxs") == 1


def test_derivados_siempre_frescos() -> None:
    registro: list[dict[str, Any]] = []
    fuente = HyperliquidSource(client=cliente(servidor(registro)))
    fuente.fetch_derivatives("BTC")
    fuente.fetch_derivatives("BTC")
    assert sum(1 for r in registro if r["type"] == "metaAndAssetCtxs") == 3  # 1 universo + 2 refrescos


def test_activo_inexistente() -> None:
    with pytest.raises(SourceError, match="no cotiza en Hyperliquid"):
        HyperliquidSource(client=cliente(servidor([]))).fetch_prices("AAPL")
    with pytest.raises(SourceError, match="no cotiza"):
        HyperliquidSource(client=cliente(servidor([]))).fetch_derivatives("AAPL")


def test_sin_velas() -> None:
    def manejador(req: httpx.Request) -> httpx.Response:
        if json.loads(req.content)["type"] == "candleSnapshot":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=cargar("hl_meta_ctxs.json"))

    with pytest.raises(SourceError, match="no devolvió velas"):
        HyperliquidSource(client=cliente(manejador)).fetch_prices("BTC")


def test_velas_malformadas() -> None:
    def manejador(req: httpx.Request) -> httpx.Response:
        if json.loads(req.content)["type"] == "candleSnapshot":
            return httpx.Response(200, json=[{"t": 1}])
        return httpx.Response(200, json=cargar("hl_meta_ctxs.json"))

    with pytest.raises(SourceError, match="formato inesperado"):
        HyperliquidSource(client=cliente(manejador)).fetch_prices("BTC")


def test_universo_malformado() -> None:
    cl = cliente(lambda r: httpx.Response(200, json={"raro": 1}))
    with pytest.raises(SourceError, match="formato inesperado"):
        HyperliquidSource(client=cl).universe()


def test_contexto_malformado() -> None:
    datos = cargar("hl_meta_ctxs.json")
    del datos[1][0]["funding"]
    cl = cliente(lambda r: httpx.Response(200, json=datos))
    with pytest.raises(SourceError, match="derivados con formato inesperado"):
        HyperliquidSource(client=cl).fetch_derivatives("BTC")


@pytest.mark.parametrize(("estado", "texto"), [(429, "limitando"), (500, "HTTP 500")])
def test_errores_http(estado: int, texto: str) -> None:
    cl = cliente(lambda r: httpx.Response(estado, text="x"))
    with pytest.raises(SourceError, match=texto):
        HyperliquidSource(client=cl).universe()


def test_respuesta_no_json_y_fallo_de_red() -> None:
    with pytest.raises(SourceError, match="no válida"):
        HyperliquidSource(client=cliente(lambda r: httpx.Response(200, text="x"))).universe()

    def roto(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red", request=req)

    with pytest.raises(SourceError, match="No se pudo conectar con Hyperliquid"):
        HyperliquidSource(client=cliente(roto)).universe()
