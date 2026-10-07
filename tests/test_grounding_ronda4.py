"""Grounding ronda 4: mercado por etiqueta, escalas SEC, notación por página, tablas en millones, citas rotas."""
from dataclasses import replace
from pathlib import Path

import pytest

from finlens.domain.grounding import check_figures
from finlens.domain.ingest import Chunk, IngestedDocument, ingest_pdf
from finlens.domain.schemas import AnalysisReport, Citation, KeyFigure
from finlens.domain.technicals import compute_technicals
from finlens.sources.base import FundamentalFact, Fundamentals
from finlens.sources.mock import MockDerivatives, MockPrices

INDITEX = Path(__file__).resolve().parents[1] / "samples" / "01_inditex" / "informe.pdf"


def estado(nombre: str, valor: str, origen: str, loc: str = "", **fuentes):
    informe = AnalysisReport(
        summary="r", spoken_summary="r",
        key_figures=[KeyFigure(name=nombre, value=valor, citations=[Citation(origin=origen, location=loc)])],
    )
    doc = fuentes.pop("doc", None)
    return check_figures(informe, doc, **fuentes)[0]


# --- Mercado por etiqueta -------------------------------------------------------------------

TECH = replace(
    compute_technicals(MockPrices().fetch_prices("ITX")),
    last_close=53.82, rsi14=61.7, sma50=58.0, sma20=55.0,
)


@pytest.mark.parametrize(
    ("nombre", "valor", "esperado"),
    [
        ("RSI", "54", "no_encontrada"),  # 54 ≈ 53,82 (cierre) pero no es el RSI
        ("RSI", "61,7", "verificada"),
        ("RSI (14)", "61,7", "verificada"),
        ("RSI", "RSI (14): 61,7", "verificada"),  # el 14 del nombre del indicador no cuenta
        ("SMA50", "61,9", "no_encontrada"),  # 61,9 ≈ RSI pero no la SMA50
        ("SMA 50", "58,0", "verificada"),
        ("Media móvil de 20 sesiones", "55", "verificada"),
        ("Último cierre", "53,82", "verificada"),
        ("Cierre", "61,7", "no_encontrada"),  # el RSI no es un cierre
        ("Cotización", "53,8", "verificada"),
    ],
)
def test_mercado_se_compara_solo_con_el_indicador_citado(nombre: str, valor: str, esperado: str) -> None:
    assert estado(nombre, valor, "mercado", technicals=TECH).status == esperado


def test_indicador_no_reconocido_compara_con_todo() -> None:
    assert estado("Dato curioso", "61,7", "mercado", technicals=TECH).status == "verificada"
    assert estado("Dato curioso", "99,9", "mercado", technicals=TECH).status == "no_encontrada"


def test_open_interest_en_unidades_y_en_nocional() -> None:
    d = MockDerivatives().fetch_derivatives("BTC")
    assert estado("Open interest", f"{d.open_interest:.0f}", "mercado", derivatives=d).status == "verificada"
    nocional = d.open_interest * d.mark_px
    r = estado("Open interest (USD)", f"{nocional / 1e6:.4f} M", "mercado", derivatives=d)
    assert r.status == "verificada" and "nocional" in r.matched
    assert estado("Volumen 24 h", f"{d.open_interest:.0f}", "mercado", derivatives=d).status == "no_encontrada"


# --- SEC: escalas -----------------------------------------------------------------------------

APPLE = Fundamentals(
    "Apple Inc.", 320193,
    (FundamentalFact("Revenues", "Ingresos", 416.161e9, "USD", 2025, "2025-09-27", "10-K", "x"),),
)


@pytest.mark.parametrize(
    "valor", ["$416.2 billion", "416,2 mil millones USD", "$416 bn", "416.161 millones de USD", "$416.161 billion"],
)
def test_sec_con_palabra_de_escala_y_redondeo(valor: str) -> None:
    assert estado("Ingresos", valor, "sec", fundamentals=APPLE).status == "verificada"


@pytest.mark.parametrize("valor", ["416 USD", "$417 bn", "$416.9 billion", "416", "5 %"])
def test_sec_sin_escala_o_con_otro_valor_no_se_encuentra(valor: str) -> None:
    assert estado("Ingresos", valor, "sec", fundamentals=APPLE).status == "no_encontrada"


def doc(texto: str) -> IngestedDocument:
    return IngestedDocument(chunks=(Chunk(1, texto),), n_pages=1)


def test_redondeo_con_k_cero_en_documento() -> None:
    d = doc("Net sales were €3,456.7 million in the year.")
    assert estado("v", "€3.5 billion", "documento", "p.1", doc=d).status == "verificada"
    assert estado("v", "€3.6 billion", "documento", "p.1", doc=d).status == "no_encontrada"


# --- Notación por página -----------------------------------------------------------------------


def test_notacion_de_la_pagina_descarta_la_lectura_incompatible() -> None:
    ingles = doc("Online sales reached €10.712 million, up 4.8% in the year.")
    assert estado("v", "10,7 mil millones €", "documento", "p.1", doc=ingles).status == "no_encontrada"
    assert estado("v", "10.712 million", "documento", "p.1", doc=ingles).status == "verificada"
    espanol = doc("Las ventas online alcanzaron 10.712 millones de euros, un 4,8% más.")
    assert estado("v", "10.712 millones", "documento", "p.1", doc=espanol).status == "verificada"


# --- Tabla en millones, citas rotas, años ------------------------------------------------------


@pytest.mark.skipif(not INDITEX.exists(), reason="falta samples/01_inditex")
@pytest.mark.parametrize("valor", ["39.864.000.000", "39.8 bn", "€39.9 billion", "39.864 millones"])
def test_tabla_en_millones_se_lee_como_escala_implicita(valor: str) -> None:
    d = ingest_pdf(INDITEX.read_bytes())
    assert estado("Ventas", valor, "documento", "p.5", doc=d).status == "verificada"


@pytest.mark.skipif(not INDITEX.exists(), reason="falta samples/01_inditex")
def test_escala_implicita_no_inventa_cifras() -> None:
    d = ingest_pdf(INDITEX.read_bytes())
    assert estado("Ventas", "41.000.000.000", "documento", "p.5", doc=d).status == "no_encontrada"
    assert estado("Ventas", "39.0 bn", "documento", "p.5", doc=d).status == "no_encontrada"


def test_la_escala_implicita_solo_aplica_si_la_pagina_la_declara() -> None:
    sin = doc("Net sales 39,864 38,632")
    con = doc("Amounts in millions of euros. Net sales 39,864 38,632")
    assert estado("v", "39.864.000.000", "documento", "p.1", doc=sin).status == "no_encontrada"
    assert estado("v", "39.864.000.000", "documento", "p.1", doc=con).status == "verificada"


@pytest.mark.parametrize("loc", ["p.-1", "p.abc", "pagina", "p. "])
def test_cita_a_pagina_rota_es_no_encontrada(loc: str) -> None:
    r = estado("v", "39.864", "documento", loc, doc=doc("Net sales 39,864"))
    assert r.status == ("sin_fuente_documental" if not loc.strip(" .p") and loc == "p. " else "no_encontrada") or (
        r.status == "no_encontrada"
    )
    assert estado("v", "39.864", "documento", "", doc=doc("39,864")).status == "sin_fuente_documental"


@pytest.mark.parametrize("valor", ["2025", "1999", "3", "7", "2100"])
def test_solo_un_anio_o_un_entero_pequeno_no_se_verifica(valor: str) -> None:
    d = doc("En 2025, 1999 y 2100 hubo 3 filiales y 7 sedes.")
    assert estado("v", valor, "documento", "p.1", doc=d).status == "sin_fuente_documental"


@pytest.mark.parametrize("valor", ["12", "2025 M", "3 %", "1.950", "10"])
def test_enteros_con_unidad_o_mayores_si_se_verifican(valor: str) -> None:
    d = doc("Hubo 12 filiales, 2025 millones, un 3 % más, 1.950 empleados y 10 sedes.")
    assert estado("v", valor, "documento", "p.1", doc=d).status == "verificada"
