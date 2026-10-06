"""Conector SEC EDGAR con respuestas reales grabadas (company_tickers y companyfacts de AAPL)."""
import copy
from collections.abc import Callable
from typing import Any

import httpx2 as httpx
import pytest
from _mercado import cargar, cliente

from finlens.sources.base import FundamentalsSource, SourceError
from finlens.sources.sec_edgar import SecEdgar, parsear_companyfacts


def servidor(llamadas: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    def manejador(req: httpx.Request) -> httpx.Response:
        llamadas.append(req)
        if req.url.path.endswith("company_tickers.json"):
            return httpx.Response(200, json=cargar("sec_company_tickers.json"))
        if req.url.path.endswith("CIK0000320193.json"):
            return httpx.Response(200, json=cargar("sec_companyfacts_aapl.json"))
        return httpx.Response(404)

    return manejador


def test_fundamentales_de_aapl() -> None:
    llamadas: list[httpx.Request] = []
    ua = "FinLens academic project a@b.es"
    sec = SecEdgar(client=cliente(servidor(llamadas)), user_agent=ua)
    f = sec.fetch_fundamentals("aapl")
    assert f is not None and f.company == "Apple Inc." and f.cik == 320193
    assert all(r.headers["User-Agent"] == ua for r in llamadas)
    assert llamadas[1].url.path.endswith("CIK0000320193.json")
    ingresos = [x for x in f.facts if x.label_es == "Ingresos"]
    assert len(ingresos) == 3
    # Revenues en AAPL solo llega a 2018: debe ganar el tag con dato más reciente
    assert {x.tag for x in ingresos} == {"RevenueFromContractWithCustomerExcludingAssessedTax"}
    assert [x.end for x in ingresos] == sorted((x.end for x in ingresos), reverse=True)
    assert len({x.end for x in ingresos}) == 3  # deduplicado por fecha de cierre
    ultimo = ingresos[0]
    assert ultimo.form == "10-K" and ultimo.unit == "USD" and ultimo.value > 3e11
    assert ultimo.fy == int(ultimo.end[:4]) and ultimo.accn


def test_incluye_saldos_de_balance_sin_start() -> None:
    f = SecEdgar(client=cliente(servidor([]))).fetch_fundamentals("AAPL")
    assert f is not None
    etiquetas = {x.label_es for x in f.facts}
    esperadas = {"Activos totales", "Pasivos totales", "Patrimonio neto", "Beneficio neto",
                 "Flujo de caja operativo", "Beneficio bruto", "Resultado operativo", "Ingresos"}
    assert esperadas <= etiquetas
    assert all(sum(1 for x in f.facts if x.label_es == e) <= 3 for e in etiquetas)


def test_cumple_protocolo_y_cachea_el_mapa_de_tickers() -> None:
    llamadas: list[httpx.Request] = []
    sec = SecEdgar(client=cliente(servidor(llamadas)))
    assert isinstance(sec, FundamentalsSource)
    sec.cik_for("AAPL")
    sec.cik_for("MSFT")
    sec.cik_for("NVDA")
    assert sum(1 for r in llamadas if r.url.path.endswith("company_tickers.json")) == 1


def test_empresa_fuera_de_la_sec_devuelve_none() -> None:
    llamadas: list[httpx.Request] = []
    sec = SecEdgar(client=cliente(servidor(llamadas)))
    assert sec.fetch_fundamentals("ITX.MC") is None
    assert len(llamadas) == 1  # solo el mapa de tickers; no pide companyfacts


def test_companyfacts_404_devuelve_none() -> None:
    # MSFT está en el mapa pero el servidor de prueba no tiene sus facts: 404
    assert SecEdgar(client=cliente(servidor([]))).fetch_fundamentals("MSFT") is None


def test_ticker_con_punto_se_busca_con_guion() -> None:
    sec = SecEdgar(client=cliente(servidor([])))
    assert sec.cik_for("A.B") is None
    sec._mapa_tickers()["BRK-B"] = (1067983, "BERKSHIRE HATHAWAY INC")
    assert sec.cik_for("brk.b") == (1067983, "BERKSHIRE HATHAWAY INC")


def _facts(entradas: list[dict[str, Any]], tag: str = "NetIncomeLoss") -> dict[str, Any]:
    return {"facts": {"us-gaap": {tag: {"units": {"USD": entradas}}}}}


def _e(start: str | None, end: str, val: int, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "end": end, "val": val, "accn": "a", "fy": 2025, "fp": "FY", "form": "10-K", "filed": end,
    }
    if start:
        base["start"] = start
    return base | kw


def test_filtra_forma_fp_y_duracion() -> None:
    datos = _facts([
        _e("2024-01-01", "2024-12-31", 100),
        _e("2024-10-01", "2024-12-31", 30),  # trimestre dentro de un 10-K: fuera
        _e("2023-01-01", "2023-12-31", 90, form="10-Q"),
        _e("2022-01-01", "2022-12-31", 80, fp="Q3"),
        _e(None, "2021-12-31", 70),  # flujo sin start: fuera
        _e("2020-01-01", "2020-10-30", 60),  # 303 días > 300: dentro
        _e("2019-01-01", "2019-10-27", 50),  # 299 días: fuera
    ])
    f = parsear_companyfacts(datos, 1, "X")
    assert [(x.end, x.value) for x in f.facts] == [("2024-12-31", 100.0), ("2020-10-30", 60.0)]


def test_dedup_por_cierre_gana_el_ultimo_filing_y_maximo_3_ejercicios() -> None:
    datos = _facts([
        _e("2024-01-01", "2024-12-31", 100, filed="2025-02-01"),
        _e("2024-01-01", "2024-12-31", 101, filed="2026-02-01"),  # reexpresado
        _e("2023-01-01", "2023-12-31", 90),
        _e("2022-01-01", "2022-12-31", 80),
        _e("2021-01-01", "2021-12-31", 70),
    ])
    f = parsear_companyfacts(datos, 1, "X")
    esperado = [("2024-12-31", 101.0), ("2023-12-31", 90.0), ("2022-12-31", 80.0)]
    assert [(x.end, x.value) for x in f.facts] == esperado


def test_ingresos_elige_el_tag_con_dato_mas_reciente() -> None:
    datos = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_e("2017-01-01", "2017-12-31", 5)]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {
            "units": {"USD": [_e("2024-01-01", "2024-12-31", 9)]}
        },
        "SalesRevenueNet": {"units": {"USD": [_e("2010-01-01", "2010-12-31", 1)]}},
    }}}
    f = parsear_companyfacts(datos, 1, "X")
    assert [(x.tag, x.value) for x in f.facts] == [("RevenueFromContractWithCustomerExcludingAssessedTax", 9.0)]


def test_ingresos_con_revenues_si_es_el_mas_reciente() -> None:
    datos = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_e("2024-01-01", "2024-12-31", 7)]}},
        "SalesRevenueNet": {"units": {"USD": [_e("2012-01-01", "2012-12-31", 1)]}},
    }}}
    assert parsear_companyfacts(datos, 1, "X").facts[0].tag == "Revenues"


def test_ejercicio_fiscal_se_deriva_del_cierre_no_del_fy_del_filing() -> None:
    datos = _facts([
        _e("2024-02-01", "2025-01-31", 5, fy=2025),  # cierre en enero: ejercicio 2024
        _e("2023-02-01", "2024-01-31", 4, fy=2025),  # el filing repite fy=2025
    ])
    assert [x.fy for x in parsear_companyfacts(datos, 1, "X").facts] == [2024, 2023]


def test_sin_us_gaap_devuelve_facts_vacios() -> None:
    f = parsear_companyfacts({"facts": {"ifrs-full": {}}}, 5, "Y")
    assert f.facts == () and f.cik == 5 and f.company == "Y"


def test_entrada_con_fecha_corrupta_se_ignora() -> None:
    datos = _facts([_e("no-fecha", "2024-12-31", 1), _e("2023-01-01", "2023-12-31", 2)])
    assert [x.end for x in parsear_companyfacts(datos, 1, "X").facts] == ["2023-12-31"]


def test_parsear_no_muta_la_entrada() -> None:
    original = cargar("sec_companyfacts_aapl.json")
    copia = copy.deepcopy(original)
    parsear_companyfacts(original, 320193, "Apple")
    assert original == copia


@pytest.mark.parametrize(("estado", "texto"), [(403, "SEC_USER_AGENT"), (429, "limitando"), (500, "HTTP 500")])
def test_errores_http(estado: int, texto: str) -> None:
    cl = cliente(lambda r: httpx.Response(estado, text="x"))
    with pytest.raises(SourceError, match=texto):
        SecEdgar(client=cl).fetch_fundamentals("AAPL")


def test_respuesta_malformada_y_fallo_de_red() -> None:
    with pytest.raises(SourceError, match="formato inesperado"):
        SecEdgar(client=cliente(lambda r: httpx.Response(200, json=[1, 2]))).fetch_fundamentals("AAPL")
    with pytest.raises(SourceError, match="no válida"):
        SecEdgar(client=cliente(lambda r: httpx.Response(200, text="x"))).fetch_fundamentals("AAPL")

    def roto(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red", request=req)

    with pytest.raises(SourceError, match="No se pudo conectar con la SEC"):
        SecEdgar(client=cliente(roto)).fetch_fundamentals("AAPL")
