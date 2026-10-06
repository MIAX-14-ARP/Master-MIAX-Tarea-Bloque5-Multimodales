"""QA del contraste visión ↔ datos: qué números cuentan como precio y cuáles no (falsas discrepancias)."""
import pytest

from finlens.domain.chart_check import PUNTUACION_NEUTRA, check_chart_reading
from test_chart_check import lectura, tecnicos, veredictos


def items(observacion: str) -> list[tuple[str, str]]:
    """(claim, veredicto) de una observación, sin la tendencia (indeterminada → no_verificable)."""
    c = check_chart_reading(lectura("indeterminada", "Velas diarias.", observacion), tecnicos())
    return [(i.claim, i.verdict) for i in c.items[1:]]


@pytest.mark.parametrize(
    "observacion",
    [
        "Rebotó 3 veces en la zona.",  # recuento
        "Dos intentos fallidos, 2 velas rojas.",
        "Subida del 15 % en 20 días.",  # porcentaje y periodo
        "Lleva 12 sesiones al alza.",
        "RSI 70.",  # valor de oscilador
        "RSI 14 en 55.",
        "RSI(14): 72.",
        "El RSI marca 62.",
        "MACD 12 a 0,5.",
        "Volumen: picos de 120K y 100K.",  # volumen
        "Desde 2024 la serie sube.",  # año
    ],
)
def test_no_genera_afirmaciones_de_precio(observacion: str) -> None:
    assert items(observacion) == []


@pytest.mark.parametrize(
    "observacion",
    [
        "Máximo del 6 oct. 2026 en 119.",
        "Cierre el 2026-04-06 en 100.",
        "Cierre el 06/04/2026 en 100.",
        "RSI 14 en 55 y precio en 101.",
        "RSI(14): 70; cierre en 110.",
    ],
)
def test_fechas_e_indicadores_no_ocultan_el_precio_real(observacion: str) -> None:
    resultado = items(observacion)
    assert len(resultado) == 1 and resultado[0][1] == "confirmada", resultado


@pytest.mark.parametrize(
    ("observacion", "veredicto"),
    [
        ("Soporte en 90.", "confirmada"),
        ("Soporte en 91,5.", "confirmada"),  # ±3 % del pivote 90
        ("Soporte en 70.", "discrepa"),
        ("Soporte en la zona 88 - 92.", "confirmada"),
        ("Resistencia entre 108 y 112.", "confirmada"),
        ("Resistencia entre 140 y 150.", "discrepa"),
        ("Precio en 1.000,5.", "discrepa"),  # formato español: 1000,5 fuera de rango
        ("Precio en 99,50.", "confirmada"),
        ("Precio en 1,234.", "discrepa"),
    ],
)
def test_niveles_verificables(observacion: str, veredicto: str) -> None:
    resultado = items(observacion)
    assert [v for _c, v in resultado] == [veredicto], resultado


def test_zona_se_cuenta_como_una_sola_afirmacion() -> None:
    resultado = items("Soporte en la zona 88 - 92.")
    assert len(resultado) == 1 and "88 – 92" in resultado[0][0]


def test_lectura_alucinada_puntua_bajo() -> None:
    c = check_chart_reading(
        lectura("bajista", "Cae desde 300.", "Soporte en 40.", "Resistencia en 250."), tecnicos()
    )
    assert veredictos(c) == ["discrepa"] * 4 and c.agreement_score == 0.0


def test_lectura_fiel_puntua_alto() -> None:
    c = check_chart_reading(
        lectura("alcista", "Sube de 82 a 118 en el periodo.", "Soporte en 90.", "RSI 14 en 55."), tecnicos()
    )
    assert set(veredictos(c)) == {"confirmada"} and c.agreement_score == 1.0


def test_sin_afirmaciones_verificables_es_neutra() -> None:
    c = check_chart_reading(lectura("indeterminada", "Gráfico de velas.", "RSI 70."), tecnicos())
    assert c.n_verifiable == 0 and c.agreement_score == PUNTUACION_NEUTRA
