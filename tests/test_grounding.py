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


# --- Equivalencia de escala, matched, páginas y casos reales (ronda 2) --------------------------

from pathlib import Path  # noqa: E402

from finlens.domain.ingest import ingest_pdf  # noqa: E402

INDITEX = Path(__file__).resolve().parents[1] / "samples" / "01_inditex" / "informe.pdf"

DOC_ES = IngestedDocument(
    chunks=(
        Chunk(1, "Ventas netas 39,864 38,632 Margen bruto 58.3% 57.8%. Plantilla de 18.400 empleados."),
        Chunk(2, "Sales grew 3.2% to reach €39.9 billion. Online sales grew at 4.8% to reach €10.7 billion."),
        Chunk(3, "Beneficio de 5.4 bn USD y $2bn en inversiones; 1.250 millones de euros."),
    ),
    n_pages=3,
)


def res(valor: str, loc: str = "p.1", doc: IngestedDocument = DOC_ES):
    (r,) = check_figures(informe(cifra(valor, ("documento", loc))), doc)
    return r


@pytest.mark.parametrize(
    ("valor", "pagina", "encontrado"),
    [
        ("39.864 millones", "p.1", "39,864"),  # tabla en millones
        ("58,3 %", "p.1", "58.3%"),
        ("4,8%", "p.2", "4.8%"),
        ("€10.7 billion", "p.2", "€10.7 billion"),
        ("10.700 millones", "p.2", "€10.7 billion"),  # billion = mil millones
        ("10,7 mil millones", "p.2", "€10.7 billion"),
        ("10.7bn", "p.2", "€10.7 billion"),
        ("39,9 mil millones de euros", "p.2", "€39.9 billion"),  # redondeo: 39.864 M ≈ 39.9 bn
        ("5.400 millones", "p.3", "5.4 bn"),
        ("1,25 mil millones", "p.3", "1.250 millones"),
    ],
)
def test_equivalencia_de_escala_y_matched(valor: str, pagina: str, encontrado: str) -> None:
    r = res(valor, pagina)
    assert r.status == "verificada" and r.matched is not None and encontrado in r.matched
    assert r.page == int(pagina[2:])


def test_el_valor_de_39_9_billion_casa_con_la_tabla_en_millones() -> None:
    assert res("€39.9 billion", "p.1").status == "verificada"  # 39.9e9 ≈ 39,864 (millones)


def test_los_dolares_se_reconocen() -> None:
    assert res("$2bn", "p.3").status == "verificada"
    assert res("2.000 millones", "p.3").status == "verificada"


def test_sin_palabra_de_escala_no_hay_equivalencia() -> None:
    doc = IngestedDocument(chunks=(Chunk(1, "Plantilla de 18.400 empleados en 2025; margen 12.3 puntos."),), n_pages=1)
    assert res("18,4 %", "p.1", doc).status == "no_encontrada"  # un porcentaje nunca cambia de escala
    assert res("18,4", "p.1", doc).status == "no_encontrada"  # sin palabra de escala en ningún lado
    assert res("12.300", "p.1", doc).status == "no_encontrada"  # 12.3 vs 12.300 sin escala
    assert res("18,4 millones", "p.1", doc).status == "verificada"  # con escala sí: 18,4 M = 18.400 miles


def test_los_porcentajes_de_la_pagina_no_se_reescalan() -> None:
    doc = IngestedDocument(chunks=(Chunk(1, "El margen fue 12.3% en el año."),), n_pages=1)
    assert res("12.300 M EUR", "p.1", doc).status == "no_encontrada"


@pytest.mark.parametrize(
    ("localizacion", "esperada"),
    [
        ("cap. 2, p.1", [1]),  # el capítulo no es una página
        ("pp. 1-2", [1, 2]),
        ("p.1 y p.3", [1, 3]),
        ("pagina 2", [2]),
        ("page 2", [2]),
        ("pág. 3", [3]),
    ],
)
def test_lectura_de_paginas_de_la_cita(localizacion: str, esperada: list[int]) -> None:
    from finlens.domain.grounding import _paginas_citadas

    assert _paginas_citadas([Citation(origin="documento", location=localizacion)]) == esperada


def test_se_verifica_contra_cualquiera_de_las_paginas_citadas() -> None:
    assert res("€10.7 billion", "pp. 1-2").page == 2
    assert res("€10.7 billion", "p.1 y p.2").status == "verificada"


@pytest.mark.skipif(not INDITEX.exists(), reason="falta samples/01_inditex")
@pytest.mark.parametrize(
    ("valor", "pagina"),
    [
        ("39.864 millones", "p.5"), ("58,3 %", "p.5"), ("58.3%", "p.5"), ("€10.7 billion", "p.15"),
        ("10.700 millones", "p.15"), ("4,8%", "p.15"), ("3.2%", "p.15"), ("€39.9 billion", "p.15"),
    ],
)
def test_casos_reales_del_informe_de_inditex(valor: str, pagina: str) -> None:
    doc = ingest_pdf(INDITEX.read_bytes())
    r = res(valor, pagina, doc)
    assert r.status == "verificada" and r.matched


@pytest.mark.skipif(not INDITEX.exists(), reason="falta samples/01_inditex")
def test_inditex_cifra_inventada_no_se_encuentra() -> None:
    doc = ingest_pdf(INDITEX.read_bytes())
    assert res("61,7 %", "p.5", doc).status == "no_encontrada"
    assert res("€99.9 billion", "p.5", doc).status == "no_encontrada"


# --- Precisión, unidades y matched con el texto real (ronda 3) ---------------------------------


@pytest.mark.skipif(not INDITEX.exists(), reason="falta samples/01_inditex")
@pytest.mark.parametrize(
    ("valor", "pagina", "esperado"),
    [
        ("around €2.3 billion", "p.20", "€2.3 billion"),
        ("-1%", "p.20", "1%"),
        ("stable gross margin (+/-50 bps)", "p.20", "50 bps"),
        ("increase of 4%", "p.21", "4%"),
    ],
)
def test_inditex_p20_p21_matched_es_el_texto_real_con_unidad(valor: str, pagina: str, esperado: str) -> None:
    doc = ingest_pdf(INDITEX.read_bytes())
    r = res(valor, pagina, doc)
    assert r.status == "verificada" and r.matched == esperado
    texto = " ".join(c.text for c in doc.chunks if c.page == int(pagina[2:]))
    assert esperado in texto


@pytest.mark.skipif(not INDITEX.exists(), reason="falta samples/01_inditex")
@pytest.mark.parametrize(
    ("valor", "pagina"),
    [
        ("around €2.4 billion", "p.20"),  # misma precisión, otro valor
        ("-2%", "p.20"),
        ("+/-30 bps", "p.20"),
        ("increase of 5%", "p.21"),
        ("increase of 4%", "p.20"),  # el 4% está en la p.21
        ("€2.3 billion", "p.21"),
    ],
)
def test_inditex_cifras_que_no_estan_en_la_pagina(valor: str, pagina: str) -> None:
    doc = ingest_pdf(INDITEX.read_bytes())
    assert res(valor, pagina, doc).status == "no_encontrada"


def test_el_numero_de_la_pagina_debe_tener_al_menos_la_precision_citada() -> None:
    doc = IngestedDocument(chunks=(Chunk(1, "Hay 2 filiales y 4 sedes en 2 países."),), n_pages=1)
    assert res("around €2.3 billion", "p.1", doc).status == "no_encontrada"  # 2.3 no casa con 2
    assert res("2.000 millones", "p.1", doc).status == "no_encontrada"  # un «2» suelto no es 2 000 M


def test_un_porcentaje_citado_exige_porcentaje_en_la_pagina() -> None:
    doc = IngestedDocument(chunks=(Chunk(1, "En 1 año hubo 4 cambios y un 7 por ciento más."),), n_pages=1)
    assert res("-1%", "p.1", doc).status == "no_encontrada"
    assert res("increase of 4%", "p.1", doc).status == "no_encontrada"
    r = res("7 %", "p.1", doc)
    assert r.status == "verificada" and r.matched == "7 por ciento"
