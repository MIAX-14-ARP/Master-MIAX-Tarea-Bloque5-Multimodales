"""Tests del guardrail de compliance: detecta recomendaciones sin tocar lenguaje legítimo."""
import json

import pytest

from finlens.domain.guardrails import (
    DISCLAIMER,
    REMOVED_NOTICE,
    apply_guardrails,
    detect_recommendations,
    guard_text,
    with_disclaimer,
)
from finlens.domain.schemas import AnalysisReport
from finlens.providers.mock import RESPUESTAS_LLM

RECOMENDACIONES = [
    "Recomiendo comprar esta acción",
    "Te aconsejamos vender antes del cierre",
    "RECOMENDACIÓN DE COMPRA",
    "Es un buen momento para comprar",
    "Hay que vender cuanto antes",
    "Compra ya",
    "Compren acciones ahora",
    "Precio objetivo: 25 EUR",
    "Nuestro price target es de 30 dólares",
    "Rating: overweight",
    "Recomendación de mantener",
    "Deberías vender la posición",
    "Mi consejo es comprar",
    "Infraponderar el sector",
    "Yo compraría esta acción",
    "Diría que toca vender",
    "Es una oportunidad de compra",
    "La acción merece una compra",
    "Conviene mantener las acciones",
    "Sugiero adquirir más títulos",
    "Buy this stock now",
    "Es hora de comprar",
]

LENGUAJE_LEGITIMO = [
    "La compañía compró acciones propias por 200 millones.",
    "Las ventas crecieron un 5 % en el trimestre.",
    "La dirección mantiene su guía de resultados.",
    "La compra de la filial se cerró en marzo.",
    "El margen operativo mejoró hasta el 18,4 %.",
    "La empresa vende acciones propias en autocartera.",
    "La dirección debe vender activos para reducir deuda, según el informe.",
    "El consejo de administración acordó vender la filial.",
    "Acumuló pérdidas durante dos ejercicios.",
    "La compañía compraría la competidora si se aprueba la operación.",
    "Hay una oportunidad de venta cruzada en banca privada.",
    "La empresa quiere adquirir una tecnológica en 2026.",
]


@pytest.mark.parametrize("texto", RECOMENDACIONES)
def test_detecta_lenguaje_de_recomendacion(texto: str) -> None:
    assert detect_recommendations(texto), texto


@pytest.mark.parametrize("texto", LENGUAJE_LEGITIMO)
def test_no_marca_lenguaje_financiero_legitimo(texto: str) -> None:
    assert detect_recommendations(texto) == [], texto


def test_guard_text_sustituye_el_contenido_infractor() -> None:
    texto, violaciones = guard_text("Recomiendo comprar ya", "chat")
    assert texto == REMOVED_NOTICE and violaciones[0].field == "chat"


def test_guard_text_deja_pasar_texto_limpio() -> None:
    assert guard_text("El margen subió.") == ("El margen subió.", [])


def test_informe_limpio_pasa_intacto() -> None:
    informe = AnalysisReport.model_validate(RESPUESTAS_LLM["AnalysisReport"])
    resultado = apply_guardrails(informe)
    assert not resultado.blocked and resultado.report == informe
    assert resultado.disclaimer == DISCLAIMER


def test_informe_con_recomendaciones_se_sanea_y_se_avisa() -> None:
    datos = json.loads(json.dumps(RESPUESTAS_LLM["AnalysisReport"]))
    datos["summary"] = "Recomiendo comprar la acción."
    datos["correlations"][0]["statement"] = "Con precio objetivo de 30 EUR el valor sube."
    datos["management_statements"][0]["statement"] = "Hay que vender ya."
    datos["chart_reading"]["statement"] = "Rating: sobreponderar."
    datos["key_figures"][0]["name"] = "Precio objetivo"
    resultado = apply_guardrails(AnalysisReport.model_validate(datos))

    assert resultado.blocked
    assert resultado.report.summary == REMOVED_NOTICE
    assert resultado.report.correlations == []
    assert resultado.report.management_statements == []
    assert resultado.report.chart_reading is None
    assert [f.name for f in resultado.report.key_figures] == ["Ingresos"]
    assert "retirado contenido" in resultado.report.limitations[-1]
    assert {v.field for v in resultado.violations} >= {
        "summary", "correlations", "management_statements", "chart_reading", "key_figures",
    }


def test_apply_guardrails_no_muta_el_informe_original() -> None:
    datos = json.loads(json.dumps(RESPUESTAS_LLM["AnalysisReport"]))
    datos["summary"] = "Recomiendo comprar."
    original = AnalysisReport.model_validate(datos)
    apply_guardrails(original)
    assert original.summary == "Recomiendo comprar."


def test_with_disclaimer_añade_el_aviso() -> None:
    assert with_disclaimer("Hola").endswith(DISCLAIMER)
