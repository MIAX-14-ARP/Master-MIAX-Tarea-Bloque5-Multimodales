"""SEC EDGAR (datos públicos del Gobierno de EE. UU., sin clave): fundamentales anuales oficiales (XBRL).

La SEC exige una cabecera `User-Agent` con un contacto (configurable con `SEC_USER_AGENT`).
Solo cubre empresas que reportan a la SEC; para el resto `fetch_fundamentals` devuelve None.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import httpx2 as httpx

from finlens.sources.base import TIMEOUT_S, FundamentalFact, Fundamentals, SourceError

URL_TICKERS = "https://www.sec.gov/files/company_tickers.json"
URL_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
USER_AGENT_POR_DEFECTO = "FinLens academic project contacto@example.com"

EJERCICIOS = 3  # últimos ejercicios anuales a devolver
MIN_DIAS_PERIODO = 300  # un flujo anual dura ≈ 365 días; descarta trimestres etiquetados como FY

# Etiquetas candidatas por concepto (la primera con dato más reciente gana; en empate, el orden).
_INGRESOS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
)
CONCEPTOS: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    # (clave, etiqueta en español, tags us-gaap candidatos, es_saldo_de_balance)
    ("ingresos", "Ingresos", _INGRESOS, False),
    ("beneficio_neto", "Beneficio neto", ("NetIncomeLoss",), False),
    ("beneficio_bruto", "Beneficio bruto", ("GrossProfit",), False),
    ("resultado_operativo", "Resultado operativo", ("OperatingIncomeLoss",), False),
    ("activos", "Activos totales", ("Assets",), True),
    ("pasivos", "Pasivos totales", ("Liabilities",), True),
    ("patrimonio", "Patrimonio neto", ("StockholdersEquity",), True),
    (
        "flujo_caja_operativo",
        "Flujo de caja operativo",
        ("NetCashProvidedByUsedInOperatingActivities",),
        False,
    ),
)


class SecEdgar:
    """Fundamentales oficiales de la SEC. Cachea en memoria el mapa ticker → CIK."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        user_agent: str = USER_AGENT_POR_DEFECTO,
        timeout: float = TIMEOUT_S,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout)
        self._cabeceras = {"User-Agent": user_agent or USER_AGENT_POR_DEFECTO}
        self._tickers: dict[str, tuple[int, str]] | None = None  # TICKER -> (cik, nombre)

    def _get(self, url: str) -> Any:
        try:
            resp = self._client.get(url, headers=self._cabeceras)
        except httpx.HTTPError as exc:
            raise SourceError(f"No se pudo conectar con la SEC: {exc}") from exc
        if resp.status_code == 404:
            return None
        if resp.status_code == 429:
            raise SourceError("La SEC está limitando las peticiones (429). Inténtalo en unos minutos.")
        if resp.status_code == 403:
            raise SourceError("La SEC rechazó la petición (403): revisa SEC_USER_AGENT (debe incluir un contacto).")
        if resp.status_code >= 400:
            raise SourceError(f"La SEC respondió con error HTTP {resp.status_code}.")
        try:
            return resp.json()
        except ValueError:
            raise SourceError("La SEC devolvió una respuesta no válida.") from None

    def _mapa_tickers(self) -> dict[str, tuple[int, str]]:
        if self._tickers is None:
            datos = self._get(URL_TICKERS)
            try:
                self._tickers = {
                    str(x["ticker"]).upper(): (int(x["cik_str"]), str(x["title"])) for x in datos.values()
                }
            except (AttributeError, KeyError, TypeError, ValueError):
                raise SourceError("La SEC devolvió el mapa de tickers con formato inesperado.") from None
        return self._tickers

    def cik_for(self, ticker: str) -> tuple[int, str] | None:
        """(CIK, nombre) del ticker, o None si no reporta a la SEC."""
        mapa = self._mapa_tickers()
        simbolo = ticker.strip().upper()
        return mapa.get(simbolo) or mapa.get(simbolo.replace(".", "-"))

    def fetch_fundamentals(self, ticker: str) -> Fundamentals | None:
        encontrado = self.cik_for(ticker)
        if encontrado is None:
            return None
        cik, nombre = encontrado
        datos = self._get(URL_FACTS.format(cik=cik))
        if datos is None:
            return None
        return parsear_companyfacts(datos, cik, nombre)


def _dias(inicio: str, fin: str) -> int:
    return (date.fromisoformat(fin) - date.fromisoformat(inicio)).days


def _ejercicio(fin: str) -> int:
    """Ejercicio fiscal según la fecha de cierre. El campo `fy` de la SEC es el del *filing* (los
    comparativos de años previos lo repiten), así que no sirve; los cierres en enero (retail) cuentan
    como el ejercicio anterior, que es como los llaman las propias compañías."""
    cierre = date.fromisoformat(fin)
    return cierre.year - 1 if cierre.month == 1 else cierre.year


def _entradas_anuales(entradas: list[dict[str, Any]], es_saldo: bool) -> dict[str, dict[str, Any]]:
    """10-K, ejercicio completo y periodo ≈ 1 año; deduplicado por fecha de cierre (gana la más reciente)."""
    por_cierre: dict[str, dict[str, Any]] = {}
    for e in entradas:
        if e.get("form") != "10-K" or e.get("fp") != "FY" or "end" not in e or "val" not in e:
            continue
        try:
            if "start" in e:
                if _dias(e["start"], e["end"]) <= MIN_DIAS_PERIODO:
                    continue
            elif not es_saldo:
                continue  # un flujo sin inicio de periodo no se puede validar
        except ValueError:
            continue
        previa = por_cierre.get(e["end"])
        if previa is None or e.get("filed", "") >= previa.get("filed", ""):
            por_cierre[e["end"]] = e
    return por_cierre


def parsear_companyfacts(datos: dict[str, Any], cik: int, nombre: str) -> Fundamentals:
    """Convierte la respuesta `companyfacts` en `Fundamentals` (últimos 3 ejercicios por concepto)."""
    gaap = (datos.get("facts") or {}).get("us-gaap")
    if not isinstance(gaap, dict):
        return Fundamentals(company=nombre, cik=cik, facts=())
    hechos: list[FundamentalFact] = []
    for _clave, etiqueta, tags, es_saldo in CONCEPTOS:
        elegido: tuple[str, dict[str, dict[str, Any]]] | None = None
        for tag in tags:
            usd = (gaap.get(tag) or {}).get("units", {}).get("USD")
            if not usd:
                continue
            anuales = _entradas_anuales(usd, es_saldo)
            if anuales and (elegido is None or max(anuales) > max(elegido[1])):
                elegido = (tag, anuales)
        if elegido is None:
            continue
        tag, anuales = elegido
        for fin in sorted(anuales, reverse=True)[:EJERCICIOS]:
            e = anuales[fin]
            hechos.append(
                FundamentalFact(
                    tag=tag,
                    label_es=etiqueta,
                    value=float(e["val"]),
                    unit="USD",
                    fy=_ejercicio(fin),
                    end=fin,
                    form="10-K",
                    accn=str(e.get("accn", "")),
                )
            )
    return Fundamentals(company=nombre, cik=cik, facts=tuple(hechos))
