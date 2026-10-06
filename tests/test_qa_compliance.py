"""QA de compliance: imperativos, inglés, caracteres invisibles y retirada de solo la frase infractora."""
import pytest

from finlens.domain.guardrails import (
    REMOVED_NOTICE,
    REPORT_NOTICE,
    apply_guardrails,
    detect_recommendations,
    guard_text,
    split_sentences,
)
from finlens.domain.schemas import AnalysisReport

IMPERATIVOS_E_INGLES = [
    "Compra Inditex.",
    "Vende Telefónica.",
    "Accumulate.",
    "Mantener la posición.",
    "Buy AAPL now.",
    "You should buy the stock.",
    "Analysts upgrade to buy.",
    "Rating: buy.",
    "We recommend selling.",
    "Yo compraría acciones.",
    "Merece la pena comprar.",
]

DESCRIPTIVAS = [
    "Compra de activos por el banco central.",
    "Compra en efectivo de la filial en 2024.",
    "The company plans to sell its unit.",
    "Sell side analysts expect growth.",
    "Buy back program announced.",
    "El BCE fija un precio objetivo de inflación del 2 %.",
    "Los ingresos crecen un 8 % interanual.",
]


@pytest.mark.parametrize("texto", IMPERATIVOS_E_INGLES)
def test_detecta_imperativos_e_ingles(texto: str) -> None:
    assert detect_recommendations(texto), texto


@pytest.mark.parametrize("texto", DESCRIPTIVAS)
def test_no_retira_lenguaje_descriptivo(texto: str) -> None:
    assert detect_recommendations(texto) == []
    assert guard_text(texto) == (texto, [])


@pytest.mark.parametrize(
    "texto",
    [
        "Re­comiendo com​prar acciones.",  # guion suave y espacio de ancho cero
        "Recomiendo comprar acciones.",  # espacio duro
        "Recomiendo comprar﻿ acciones.",
        "RECOMIENDO COMPRAR ACCIONES.",
    ],
)
def test_caracteres_invisibles_y_mayusculas_no_esquivan_el_filtro(texto: str) -> None:
    assert detect_recommendations(texto)


def test_precio_objetivo_de_un_valor_se_retira_aunque_cite_macro() -> None:
    assert detect_recommendations("El precio objetivo de la acción es 30.")
    assert detect_recommendations("Pese a la inflación, el precio objetivo de la acción sube a 30.")


def test_retira_solo_la_frase_infractora() -> None:
    texto, violaciones = guard_text("Los ingresos crecen. Recomiendo comprar. El margen baja.", "summary")
    assert texto == "Los ingresos crecen. El margen baja."
    assert [v.field for v in violaciones] == ["summary"]


def test_si_todas_las_frases_infringen_queda_el_aviso() -> None:
    texto, violaciones = guard_text("Compra ya. Vende Telefónica.")
    assert texto == REMOVED_NOTICE and len(violaciones) >= 2


def test_salto_de_linea_separa_frases() -> None:
    assert split_sentences("Ingresos al alza\nRecomiendo comprar") == ["Ingresos al alza", "Recomiendo comprar"]
    texto, _ = guard_text("Ingresos al alza\nRecomiendo comprar")
    assert texto == "Ingresos al alza"


def test_informe_conserva_hallazgos_parcialmente_limpios() -> None:
    informe = AnalysisReport(
        summary="Resultados sólidos. Es buen momento para comprar.",
        spoken_summary="Resultados sólidos.",
        management_statements=[
            {"statement": "La dirección eleva previsiones. Compren acciones.", "citations": [{"origin": "audio"}]},
            {"statement": "Recomiendo vender.", "citations": [{"origin": "audio"}]},
        ],
    )
    r = apply_guardrails(informe)
    assert r.blocked
    assert r.report.summary == "Resultados sólidos."
    assert r.report.spoken_summary == "Resultados sólidos."
    assert [m.statement for m in r.report.management_statements] == ["La dirección eleva previsiones."]
    assert r.report.limitations[-1] == REPORT_NOTICE


def test_informe_limpio_no_se_modifica() -> None:
    informe = AnalysisReport(summary="Ingresos al alza.", spoken_summary="Ingresos al alza.")
    r = apply_guardrails(informe)
    assert not r.blocked and r.report == informe
