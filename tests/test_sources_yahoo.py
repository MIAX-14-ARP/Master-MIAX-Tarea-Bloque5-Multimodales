"""Conector de Yahoo Finance con la respuesta real grabada (ITX.MC, 6 meses)."""
import copy

import httpx2 as httpx
import pytest

from _mercado import cargar, cliente
from finlens.sources.base import PriceSource, SourceError
from finlens.sources.yahoo import YahooPrices


def test_parsea_la_respuesta_real() -> None:
    peticiones: list[httpx.Request] = []

    def manejador(req: httpx.Request) -> httpx.Response:
        peticiones.append(req)
        return httpx.Response(200, json=cargar("yahoo_itx_6mo.json"))

    serie = YahooPrices(client=cliente(manejador)).fetch_prices("itx.mc", "6mo")
    assert serie.symbol == "ITX.MC" and serie.currency == "EUR" and serie.source == "yahoo"
    assert len(serie.candles) == 130
    assert serie.meta["exchangeName"] == "MCE"
    c = serie.candles[0]
    assert c.t.tzinfo is not None and c.h >= c.l and c.v > 0
    assert all(a.t < b.t for a, b in zip(serie.candles, serie.candles[1:], strict=False))
    req = peticiones[0]
    assert req.url.path.endswith("/v8/finance/chart/ITX.MC")
    assert req.url.params["range"] == "6mo" and req.url.params["interval"] == "1d"
    assert req.headers["User-Agent"] == "Mozilla/5.0"


def test_cumple_el_protocolo() -> None:
    assert isinstance(YahooPrices(client=cliente(lambda r: httpx.Response(200))), PriceSource)


def test_descarta_velas_con_nulos() -> None:
    datos = copy.deepcopy(cargar("yahoo_itx_6mo.json"))
    q = datos["chart"]["result"][0]["indicators"]["quote"][0]
    q["close"][3] = None
    q["open"][7] = None
    serie = YahooPrices(client=cliente(lambda r: httpx.Response(200, json=datos))).fetch_prices("ITX.MC")
    assert len(serie.candles) == 128


def test_volumen_nulo_cuenta_como_cero() -> None:
    datos = copy.deepcopy(cargar("yahoo_itx_6mo.json"))
    datos["chart"]["result"][0]["indicators"]["quote"][0]["volume"][0] = None
    serie = YahooPrices(client=cliente(lambda r: httpx.Response(200, json=datos))).fetch_prices("ITX.MC")
    assert serie.candles[0].v == 0.0


def test_simbolo_invalido_da_mensaje_claro() -> None:
    cl = cliente(lambda r: httpx.Response(404, json=cargar("yahoo_error.json")))
    with pytest.raises(SourceError, match="no conoce el símbolo «NOEXISTE123»"):
        YahooPrices(client=cl).fetch_prices("noexiste123")


def test_error_en_cuerpo_con_http_200() -> None:
    cl = cliente(lambda r: httpx.Response(200, json=cargar("yahoo_error.json")))
    with pytest.raises(SourceError, match="no conoce el símbolo"):
        YahooPrices(client=cl).fetch_prices("XXX")


@pytest.mark.parametrize(("estado", "texto"), [(429, "limitando"), (500, "HTTP 500")])
def test_errores_http(estado: int, texto: str) -> None:
    cl = cliente(lambda r: httpx.Response(estado, text="no es json"))
    with pytest.raises(SourceError, match=texto):
        YahooPrices(client=cl).fetch_prices("AAPL")


def test_respuesta_no_json() -> None:
    cl = cliente(lambda r: httpx.Response(200, text="<html>"))
    with pytest.raises(SourceError, match="no válida"):
        YahooPrices(client=cl).fetch_prices("AAPL")


def test_sin_velas_validas() -> None:
    datos = copy.deepcopy(cargar("yahoo_itx_6mo.json"))
    q = datos["chart"]["result"][0]["indicators"]["quote"][0]
    q["close"] = [None] * len(q["close"])
    with pytest.raises(SourceError, match="velas válidas"):
        YahooPrices(client=cliente(lambda r: httpx.Response(200, json=datos))).fetch_prices("ITX.MC")


def test_estructura_inesperada() -> None:
    cl = cliente(lambda r: httpx.Response(200, json={"chart": {"result": [{}], "error": None}}))
    with pytest.raises(SourceError, match="no devolvió datos"):
        YahooPrices(client=cl).fetch_prices("AAPL")


def test_fallo_de_red() -> None:
    def roto(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red", request=req)

    with pytest.raises(SourceError, match="No se pudo conectar con Yahoo"):
        YahooPrices(client=cliente(roto)).fetch_prices("AAPL")


def test_rango_y_ticker_vacio_invalidos() -> None:
    fuente = YahooPrices(client=cliente(lambda r: httpx.Response(200)))
    with pytest.raises(SourceError, match="Rango"):
        fuente.fetch_prices("AAPL", "10y")
    with pytest.raises(SourceError, match="ticker"):
        fuente.fetch_prices("  ")
