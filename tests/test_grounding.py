"""Tests de la verificación determinista de cifras."""
import pytest

from finlens.domain.grounding import check_figures, extract_numbers, number_candidates
from finlens.domain.ingest import Chunk, IngestedDocument
from finlens.domain.schemas import AnalysisReport, Citation, KeyFigure

DOC = IngestedDocument(
    chunks=(
        Chunk(1, "Carta del presidente. Ejercicio 2025."),
        Chunk(2, "Los ingresos alcanzaron 12.300 millones de euros, un 6 por ciento más. Beneficio 1.450 M€."),
        Chunk(3, "El margen operativo se situó en el 18,4 % frente al 17,1 %. Deuda neta 3 200 millones."),
        Chunk(3, "Revenue grew to 1,234.5 million; EBITDA margin 12.3%; net loss (45,6)."),
        Chunk(4, "Perspectivas: crecimiento del 4 al 5 por ciento. Importe de 1.234 euros."),
    ),
    n_pages=4,
)


def informe(*cifras: KeyFigure) -> AnalysisReport:
    return AnalysisReport(summary="r", key_figures=list(cifras), spoken_summary="r")


def cifra(valor: str, *citas: tuple[str, str], nombre: str = "Cifra") -> KeyFigure:
    return KeyFigure(name=nombre, value=valor, citations=[Citation(origin=o, location=loc) for o, loc in citas])


def estado(valor: str, *citas: tuple[str, str]) -> str:
    (res,) = check_figures(informe(cifra(valor, *citas)), DOC)
    return res.status


@pytest.mark.parametrize(
    ("token", "esperado"),
    [
        ("18,4", {"18.4"}),
        ("18.4", {"18.4"}),
        ("18.40", {"18.4"}),
        ("1.234,5", {"1234.5"}),
        ("1,234.5", {"1234.5"}),
        ("12.300.000", {"12300000"}),
        ("12,300,000", {"12300000"}),
        ("1.234", {"1.234", "1234"}),  # ambiguo: ambas lecturas
        ("1,234", {"1.234", "1234"}),
        ("12.300", {"12300"}),  # acaba en 0: solo miles
        ("1,450", {"1450"}),
        ("0,123", {"0.123"}),
        ("0.123", {"0.123"}),
        ("12,34", {"12.34"}),
        ("1234", {"1234"}),
        ("3 200", {"3200"}),
        ("1 234,5", {"1234.5"}),
        ("1 234", {"1234"}),
    ],
)
def test_normaliza_formatos_espanol_e_ingles(token: str, esperado: set[str]) -> None:
    assert number_candidates(token) == esperado


def test_extrae_numeros_ignorando_simbolos_y_unidades() -> None:
    assert extract_numbers("18,4 %, 12.300 M€ y 1,5 millones") >= {"18.4", "12300", "1.5"}
    assert extract_numbers("sin cifras") == set()


def test_no_confunde_numeros_dentro_de_otros() -> None:
    assert "18.4" not in extract_numbers("margen del 118,4 %")
    assert "4" not in extract_numbers("año 2024")
    assert "2025" in extract_numbers("año 2025")


def test_numeros_con_espacios_cuentan_por_partes_en_el_texto() -> None:
    assert {"12", "300", "12300"} <= extract_numbers("Total 12 300", split_spaces=True)
    assert "300" not in extract_numbers("Total 12 300")


@pytest.mark.parametrize(
    "valor",
    ["18,4 %", "18,4%", "18.4 %", "18,40 %", "+18,4 pp", "-18,4 %", "18,4 por ciento"],
)
def test_verifica_el_margen_en_distintos_formatos(valor: str) -> None:
    assert estado(valor, ("documento", "p.3")) == "verificada"


@pytest.mark.parametrize(
    ("valor", "pagina"),
    [
        ("12.300 M EUR", "p.2"),
        ("12,300 millones", "p.2"),  # formato inglés del mismo número
        ("12300 M€", "p.2"),
        ("1.450 M€", "p.2"),
        ("1,450 M€", "p.2"),
        ("3.200 millones", "p.3"),  # el texto trae «3 200» con espacio
        ("1,234.5 M", "p.3"),
        ("1.234,5 M", "p.3"),
        ("12,3 %", "p.3"),
        ("45,6", "p.3"),
        ("1.234 EUR", "p.4"),
        ("4 al 5 %", "p.4"),
    ],
)
def test_verifica_formatos_equivalentes_en_la_pagina_citada(valor: str, pagina: str) -> None:
    assert estado(valor, ("documento", pagina)) == "verificada"


def test_cifra_inventada_o_alterada_no_se_encuentra() -> None:
    assert estado("19,4 %", ("documento", "p.3")) == "no_encontrada"
    assert estado("12.301 M EUR", ("documento", "p.2")) == "no_encontrada"
    assert estado("18,44 %", ("documento", "p.3")) == "no_encontrada"
    assert estado("118,4 %", ("documento", "p.3")) == "no_encontrada"


def test_la_cifra_debe_estar_en_la_pagina_citada_no_en_otra() -> None:
    assert estado("12.300 M EUR", ("documento", "p.3")) == "no_encontrada"
    assert estado("12.300 M EUR", ("documento", "p.99")) == "no_encontrada"  # página inexistente


def test_con_varias_paginas_citadas_basta_con_una() -> None:
    (res,) = check_figures(informe(cifra("12.300 M", ("documento", "p.3"), ("documento", "p.2"))), DOC)
    assert (res.status, res.page) == ("verificada", 2)


def test_todos_los_numeros_del_valor_deben_aparecer() -> None:
    assert estado("18,4 % (17,1 % antes)", ("documento", "p.3")) == "verificada"
    assert estado("18,4 % (16,0 % antes)", ("documento", "p.3")) == "no_encontrada"


def test_sin_cita_documental_no_hay_fuente() -> None:
    assert estado("18,4 %", ("grafico", "")) == "sin_fuente_documental"
    assert estado("18,4 %", ("audio", "")) == "sin_fuente_documental"
    assert estado("18,4 %", ("documento", "")) == "sin_fuente_documental"  # sin página no se busca


def test_si_cita_documento_y_audio_se_comprueba_el_documento() -> None:
    assert estado("18,4 %", ("audio", ""), ("documento", "p.3")) == "verificada"


def test_valor_sin_numeros_no_es_comprobable() -> None:
    assert estado("estable", ("documento", "p.3")) == "sin_fuente_documental"


def test_la_pagina_se_lee_de_distintas_grafias() -> None:
    for loc in ("p.3", "p. 3", "P.3", "pág. 3", "página 3"):
        assert estado("18,4 %", ("documento", loc)) == "verificada", loc


def test_devuelve_un_resultado_por_cifra_con_su_pagina() -> None:
    informe_ = informe(
        cifra("18,4 %", ("documento", "p.3"), nombre="Margen"),
        cifra("99 %", ("documento", "p.3"), nombre="Falsa"),
        cifra("5 %", ("grafico", ""), nombre="Gráfico"),
    )
    r = check_figures(informe_, DOC)
    assert [(c.figure_name, c.status, c.page) for c in r] == [
        ("Margen", "verificada", 3), ("Falsa", "no_encontrada", 3), ("Gráfico", "sin_fuente_documental", None),
    ]
    assert r[0].value == "18,4 %"


def test_informe_sin_cifras_devuelve_tupla_vacia() -> None:
    assert check_figures(informe(), DOC) == ()
