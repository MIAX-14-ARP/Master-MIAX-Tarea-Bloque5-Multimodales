"""Contraste visión ↔ datos: tendencia, niveles de precio y soportes/resistencias."""
from datetime import date

import pytest

from finlens.domain.chart_check import (
    MARGEN_RANGO_INF,
    MARGEN_RANGO_SUP,
    PUNTUACION_NEUTRA,
    _lecturas,
    _niveles_citados,
    check_chart_reading,
)
from finlens.domain.schemas import ChartReading
from finlens.domain.technicals import TechnicalSummary


def tecnicos(**kw) -> TechnicalSummary:  # type: ignore[no-untyped-def]
    base = dict(
        symbol="X", source="yahoo", n_candles=120, start=date(2026, 1, 1), end=date(2026, 6, 1),
        last_close=100.0, period_return=0.1, range_low=80.0, range_low_date=date(2026, 2, 1),
        range_high=120.0, range_high_date=date(2026, 5, 1), sma20=99.0, sma50=95.0, ema20=99.0,
        rsi14=55.0, volatility_annual=0.25, max_drawdown=-0.1, trend="alcista", trend_slope=0.1,
        above_sma50=True, supports=(90.0, 85.0), resistances=(110.0, 118.0), periods_per_year=252,
    )
    return TechnicalSummary(**(base | kw))


def lectura(trend: str = "alcista", descripcion: str = "Gráfico de velas diarias.", *obs: str) -> ChartReading:
    return ChartReading(trend=trend, description=descripcion, observations=list(obs))  # type: ignore[arg-type]


def veredictos(c) -> list[str]:  # type: ignore[no-untyped-def]
    return [i.verdict for i in c.items]


# --- tendencia ---
def test_tendencia_coincide() -> None:
    c = check_chart_reading(lectura("alcista"), tecnicos())
    assert veredictos(c) == ["confirmada"] and c.agreement_score == 1.0
    assert c.items[0].claim == "Tendencia: alcista"


def test_tendencia_discrepa() -> None:
    c = check_chart_reading(lectura("bajista"), tecnicos(trend="alcista"))
    assert veredictos(c) == ["discrepa"] and c.agreement_score == 0.0
    assert "alcista" in c.items[0].detail


def test_lateral_contra_alcista_discrepa() -> None:
    assert veredictos(check_chart_reading(lectura("lateral"), tecnicos())) == ["discrepa"]


def test_tendencia_indeterminada_no_es_verificable_y_puntuacion_neutra() -> None:
    c = check_chart_reading(lectura("indeterminada"), tecnicos())
    assert veredictos(c) == ["no_verificable"]
    assert c.agreement_score == PUNTUACION_NEUTRA and c.n_verifiable == 0


# --- niveles de precio ---
def test_nivel_dentro_del_rango_se_confirma() -> None:
    c = check_chart_reading(lectura("alcista", "El precio ronda 105.", "Máximo del periodo en 120"), tecnicos())
    assert veredictos(c) == ["confirmada", "confirmada", "confirmada"]


def test_nivel_fuera_del_rango_discrepa() -> None:
    c = check_chart_reading(lectura("alcista", "Cotiza cerca de 250 euros."), tecnicos())
    assert veredictos(c) == ["confirmada", "discrepa"]
    assert c.agreement_score == 0.5
    assert "80.00" in c.items[1].detail and "120.00" in c.items[1].detail


def test_limites_del_rango_con_margen() -> None:
    t = tecnicos()
    dentro_inf, dentro_sup = 80 * MARGEN_RANGO_INF + 0.01, 120 * MARGEN_RANGO_SUP - 0.01
    fuera_inf, fuera_sup = 80 * MARGEN_RANGO_INF - 0.05, 120 * MARGEN_RANGO_SUP + 0.05
    for valor, esperado in ((dentro_inf, "confirmada"), (dentro_sup, "confirmada"),
                            (fuera_inf, "discrepa"), (fuera_sup, "discrepa")):
        c = check_chart_reading(lectura("alcista", f"Nivel en {valor:.2f}"), t)
        assert c.items[1].verdict == esperado, valor


def test_formatos_de_numero_espanol_ingles_y_kilos() -> None:
    t = tecnicos(range_low=57_000.0, range_high=87_000.0, last_close=85_000.0, supports=(), resistances=())
    for texto in ("máximo 87.000", "máximo 87,000", "máximo 87.000,50", "máximo 86,999.5", "cerca de 85k", "85 K USD"):
        c = check_chart_reading(lectura("alcista", texto), t)
        assert c.items[1].verdict == "confirmada", texto


def test_lectura_ambigua_se_acepta_si_alguna_interpretacion_encaja() -> None:
    assert sorted(_lecturas("63.058", False)) == [63.058, 63058.0]
    assert _lecturas("1.234.567", False) == [1234567.0]
    assert _lecturas("12,5", False) == [12.5]
    assert _lecturas("63", True) == [63000.0]
    assert _lecturas("1.234,56", False) == [1234.56]
    assert _lecturas("1,234.56", False) == [1234.56]


def test_se_ignoran_porcentajes_periodos_fechas_y_nombres_de_indicador() -> None:
    texto = ("Sube un 12,5% en 30 días; la SMA 20 cruza la SMA 50; RSI 70; media móvil 200; "
             "el 15 de mayo y 3 sesiones; 2 veces; periodo 14")
    assert _niveles_citados(texto) == []


def test_precio_junto_a_simbolo_de_moneda() -> None:
    assert [t for t, _ in _niveles_citados("cierra en 53,82€ y 54.1 USD")] == ["53,82", "54.1"]


def test_texto_sin_numeros_solo_verifica_la_tendencia() -> None:
    c = check_chart_reading(lectura("alcista", "Tendencia clara con volumen creciente.", "Velas verdes."), tecnicos())
    assert len(c.items) == 1


# --- soportes y resistencias ---
def test_soporte_cerca_de_un_pivote_se_confirma() -> None:
    c = check_chart_reading(lectura("alcista", "x", "Soporte en 91"), tecnicos())
    assert c.items[1].verdict == "confirmada" and "90.00" in c.items[1].detail


def test_resistencia_cerca_de_pivote_se_confirma_con_ingles() -> None:
    c = check_chart_reading(lectura("alcista", "x", "Strong resistance around 112"), tecnicos())
    assert c.items[1].verdict == "confirmada"


def test_soporte_lejos_de_todo_pivote_discrepa() -> None:
    c = check_chart_reading(lectura("alcista", "x", "Soporte clave en 70"), tecnicos())
    assert c.items[1].verdict == "discrepa" and "90.00" in c.items[1].detail


def test_tolerancia_del_3_por_ciento_en_el_borde() -> None:
    t = tecnicos(supports=(100.0,), resistances=())
    ok = check_chart_reading(lectura("alcista", "x", "Soporte en 102.9"), t)
    ko = check_chart_reading(lectura("alcista", "x", "Soporte en 103.1"), t)
    assert ok.items[1].verdict == "confirmada" and ko.items[1].verdict == "discrepa"


def test_soporte_sin_pivotes_no_es_verificable() -> None:
    c = check_chart_reading(lectura("alcista", "x", "Soporte en 90"), tecnicos(supports=(), resistances=()))
    assert c.items[1].verdict == "no_verificable"
    assert c.agreement_score == 1.0  # solo cuenta la tendencia confirmada


def test_un_nivel_de_soporte_fuera_del_rango_discrepa_aunque_haya_pivotes() -> None:
    c = check_chart_reading(lectura("alcista", "x", "Resistencia en 300"), tecnicos())
    assert c.items[1].verdict == "discrepa"


# --- puntuación y estructura ---
def test_puntuacion_es_confirmadas_entre_verificables() -> None:
    c = check_chart_reading(
        lectura("alcista", "Cierre en 100.", "Soporte en 90", "Resistencia en 500", "Mínimo en 10"), tecnicos()
    )
    assert veredictos(c) == ["confirmada", "confirmada", "confirmada", "discrepa", "discrepa"]
    assert c.agreement_score == pytest.approx(3 / 5)
    assert c.n_verifiable == 5


def test_no_verificables_no_cuentan_en_la_puntuacion() -> None:
    c = check_chart_reading(lectura("indeterminada", "Cierre en 100."), tecnicos())
    assert veredictos(c) == ["no_verificable", "confirmada"]
    assert c.agreement_score == 1.0 and c.n_verifiable == 1


def test_resultado_inmutable_y_con_tupla() -> None:
    c = check_chart_reading(lectura(), tecnicos())
    assert isinstance(c.items, tuple)
    with pytest.raises(AttributeError):
        c.agreement_score = 0.0  # type: ignore[misc]


def test_afirmaciones_de_descripcion_y_observaciones_se_revisan_todas() -> None:
    c = check_chart_reading(lectura("alcista", "Cierre cerca de 999.", "Otro nivel en 5"), tecnicos())
    assert veredictos(c) == ["confirmada", "discrepa", "discrepa"]


def test_ancla_de_la_claim_resume_la_frase() -> None:
    larga = "Soporte en 90 " + "palabra " * 40
    c = check_chart_reading(lectura("alcista", "x", larga), tecnicos())
    assert len(c.items[1].claim) < 160 and "«90»" in c.items[1].claim
