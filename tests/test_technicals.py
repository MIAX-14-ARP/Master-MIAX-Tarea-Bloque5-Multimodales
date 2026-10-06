"""Indicadores técnicos con series sintéticas de resultado conocido y con la serie real de ITX.MC."""
import math
from datetime import date

import numpy as np
import pytest
from _mercado import cargar, cliente, serie_de_cierres

from finlens.domain import technicals as T
from finlens.sources.yahoo import YahooPrices


def arr(*xs: float) -> np.ndarray:
    return np.array(xs, dtype=np.float64)


# --- medias ---
def test_sma_exacta_y_nan_inicial() -> None:
    r = T.sma(arr(1, 2, 3, 4, 5), 3)
    assert np.isnan(r[:2]).all()
    assert r[2:].tolist() == [2.0, 3.0, 4.0]


def test_sma_con_serie_corta_es_todo_nan() -> None:
    assert np.isnan(T.sma(arr(1, 2), 3)).all()
    assert np.isnan(T.sma(arr(1, 2, 3), 0)).all()


def test_ema_se_siembra_con_sma_y_aplica_alfa() -> None:
    r = T.ema(arr(1, 2, 3, 4), 3)
    alfa = 2 / 4
    assert r[2] == pytest.approx(2.0)
    assert r[3] == pytest.approx(alfa * 4 + (1 - alfa) * 2.0)
    assert np.isnan(r[:2]).all()


def test_ema_de_constante_es_constante() -> None:
    assert T.ema(np.full(30, 7.0), 20)[-1] == pytest.approx(7.0)


# --- RSI ---
def test_rsi_de_referencia_de_wilder() -> None:
    # Serie clásica (StockCharts / Wilder): primer RSI(14) ≈ 70,5
    cierres = arr(44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
                  45.89, 46.03, 45.61, 46.28, 46.28)
    assert T.rsi_wilder(cierres, 14) == pytest.approx(70.5, abs=0.2)


def test_rsi_extremos() -> None:
    assert T.rsi_wilder(np.arange(1.0, 40.0), 14) == 100.0
    assert T.rsi_wilder(np.arange(40.0, 1.0, -1.0), 14) == pytest.approx(0.0)
    assert T.rsi_wilder(np.full(30, 5.0), 14) == 50.0


def test_rsi_necesita_n_mas_uno_cierres() -> None:
    assert T.rsi_wilder(np.arange(14.0), 14) is None
    assert T.rsi_wilder(np.arange(15.0), 14) is not None


def test_rsi_suavizado_de_wilder_tras_el_primer_valor() -> None:
    # Subir 1, bajar 1, ... : con suavizado Wilder oscila cerca de 50 sin salirse de 0..100
    cierres = np.array([100 + (i % 2) for i in range(60)], dtype=np.float64)
    assert 40 < (T.rsi_wilder(cierres, 14) or 0) < 60


# --- volatilidad y drawdown ---
def test_volatilidad_de_crecimiento_constante_es_cero() -> None:
    cierres = 100 * 1.01 ** np.arange(60)
    assert T.annualized_volatility(cierres, 252) == pytest.approx(0.0, abs=1e-12)


def test_volatilidad_anualizada_conocida() -> None:
    # rendimientos log alternos ±1 %: std muestral ≈ 0,01 · √(n/(n-1))
    rend = np.array([0.01, -0.01] * 30)
    cierres = 100 * np.exp(np.concatenate([[0.0], np.cumsum(rend)]))
    esperado = rend.std(ddof=1) * math.sqrt(252)
    assert T.annualized_volatility(cierres, 252) == pytest.approx(esperado)
    assert T.annualized_volatility(cierres, 365) == pytest.approx(rend.std(ddof=1) * math.sqrt(365))


def test_volatilidad_con_pocos_datos() -> None:
    assert T.annualized_volatility(arr(1, 2), 252) is None


def test_max_drawdown() -> None:
    assert T.max_drawdown(arr(100, 120, 60, 90)) == pytest.approx(-0.5)
    assert T.max_drawdown(arr(1, 2, 3)) == 0.0
    assert T.max_drawdown(arr(100, 90, 95, 80, 120, 110)) == pytest.approx(-0.2)


# --- tendencia ---
def test_tendencia_alcista_bajista_lateral() -> None:
    sube = serie_de_cierres(list(np.linspace(100, 130, 120)))
    baja = serie_de_cierres(list(np.linspace(130, 100, 120)))
    plana = serie_de_cierres([100 + (1 if i % 2 else -1) for i in range(120)])
    assert T.compute_technicals(sube).trend == "alcista"
    assert T.compute_technicals(baja).trend == "bajista"
    assert T.compute_technicals(plana).trend == "lateral"


def test_pendiente_proyectada_es_la_variacion_de_la_regresion() -> None:
    lineal = 100 + np.arange(101, dtype=np.float64)  # +1 por vela, media 150
    assert T.trend_slope(lineal) == pytest.approx(100 / 150)


def test_umbral_de_tendencia_en_el_borde() -> None:
    assert T.classify_trend(T.UMBRAL_TENDENCIA, 10, 9) == "alcista"
    assert T.classify_trend(T.UMBRAL_TENDENCIA - 1e-6, 10, 9) == "lateral"
    assert T.classify_trend(-T.UMBRAL_TENDENCIA, 8, 9) == "bajista"
    assert T.classify_trend(-T.UMBRAL_TENDENCIA + 1e-6, 8, 9) == "lateral"


def test_pendiente_alcista_pero_precio_bajo_la_sma_es_lateral() -> None:
    assert T.classify_trend(0.20, 9.0, 10.0) == "lateral"
    assert T.classify_trend(-0.20, 11.0, 10.0) == "lateral"


def test_sin_sma_de_referencia_decide_solo_la_pendiente() -> None:
    assert T.classify_trend(0.20, 10.0, None) == "alcista"
    assert T.classify_trend(-0.20, 10.0, None) == "bajista"
    assert T.classify_trend(0.0, 10.0, None) == "lateral"


def test_serie_corta_usa_sma20_como_referencia() -> None:
    t = T.compute_technicals(serie_de_cierres(list(np.linspace(100, 140, 30))))
    assert t.sma50 is None and t.sma20 is not None and t.above_sma50 is None
    assert t.trend == "alcista"


# --- pivotes ---
def test_pivotes_de_un_zigzag() -> None:
    # picos en 10 y 30 (máx. 110 y 108), valles en 20 y 40 (mín. 90 y 92)
    cierres = np.full(51, 100.0)
    cierres[10], cierres[30], cierres[20], cierres[40] = 110, 108, 90, 92
    altos, bajos = cierres + 0.0, cierres + 0.0
    niveles = sorted(T.pivot_levels(altos, bajos))
    assert 110.0 in niveles and 108.0 in niveles and 90.0 in niveles and 92.0 in niveles


def test_pivotes_no_incluyen_las_ultimas_velas_sin_confirmar() -> None:
    cierres = np.array([100.0] * 30 + [150.0])  # pico en la última vela: no confirmado
    assert 150.0 not in T.pivot_levels(cierres, cierres)


def test_agrupar_niveles_cercanos() -> None:
    assert T.cluster_levels([100.0, 100.5, 101.0, 120.0]) == [pytest.approx(100.5), 120.0]
    assert T.cluster_levels([]) == []
    assert T.cluster_levels([5.0]) == [5.0]


def test_soportes_y_resistencias_se_separan_por_el_ultimo_cierre() -> None:
    cierres = np.full(60, 100.0)
    cierres[10], cierres[30], cierres[20], cierres[40] = 120, 130, 80, 70
    sop, res = T.support_resistance(cierres, cierres, 100.0)
    assert sop == (80.0, 70.0)  # los más cercanos primero
    assert res == (100.0, 120.0, 130.0)  # la meseta en 100 también es un nivel (empata con el cierre)


def test_maximo_de_niveles() -> None:
    rng = np.random.default_rng(3)
    cierres = 100 + np.cumsum(rng.normal(0, 3, 300))
    sop, res = T.support_resistance(cierres, cierres, float(cierres[-1]))
    assert len(sop) <= T.MAX_NIVELES and len(res) <= T.MAX_NIVELES


# --- compute_technicals ---
def test_resumen_completo_de_serie_conocida() -> None:
    cierres = [100.0 + i for i in range(60)]  # 100..159
    s = serie_de_cierres(cierres, margen=0.0)
    t = T.compute_technicals(s)
    assert t.n_candles == 60 and t.start == date(2026, 1, 1) and t.end == date(2026, 3, 1)
    assert t.last_close == 159.0
    assert t.period_return == pytest.approx(0.59)
    assert t.range_low == 100.0 and t.range_low_date == date(2026, 1, 1)
    assert t.range_high == 159.0 and t.range_high_date == date(2026, 3, 1)
    assert t.sma20 == pytest.approx(np.mean(cierres[-20:]))
    assert t.sma50 == pytest.approx(np.mean(cierres[-50:]))
    assert t.rsi14 == 100.0
    assert t.max_drawdown == 0.0
    assert t.above_sma50 is True and t.trend == "alcista"
    assert t.symbol == "TEST" and t.source == "yahoo"


def test_anualizacion_segun_mercado() -> None:
    rng = np.random.default_rng(1)
    cierres = list(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 100))))
    accion = T.compute_technicals(serie_de_cierres(cierres, fuente="yahoo"))
    cripto = T.compute_technicals(serie_de_cierres(cierres, fuente="hyperliquid"))
    assert accion.periods_per_year == 252 and cripto.periods_per_year == 365
    assert cripto.volatility_annual == pytest.approx(accion.volatility_annual * math.sqrt(365 / 252))  # type: ignore[operator]
    forzada = T.compute_technicals(serie_de_cierres(cierres, fuente="yahoo"), mercado="cripto")
    assert forzada.periods_per_year == 365


def test_rango_usa_maximos_y_minimos_de_las_velas() -> None:
    s = serie_de_cierres([100.0] * 15 + [110.0] + [100.0] * 15, margen=0.02)
    t = T.compute_technicals(s)
    assert t.range_high == pytest.approx(110 * 1.02)
    assert t.range_low == pytest.approx(100 * 0.98)
    assert t.range_high_date == date(2026, 1, 16)


def test_pocas_velas_lanza_valueerror() -> None:
    with pytest.raises(ValueError, match="al menos"):
        T.compute_technicals(serie_de_cierres([1.0] * (T.MIN_VELAS - 1)))


def test_es_determinista() -> None:
    s = serie_de_cierres(list(100 + np.cumsum(np.random.default_rng(5).normal(0, 1, 80))))
    assert T.compute_technicals(s) == T.compute_technicals(s)


def test_con_la_serie_real_de_itx() -> None:
    import httpx2 as httpx

    serie = YahooPrices(client=cliente(lambda r: httpx.Response(200, json=cargar("yahoo_itx_6mo.json")))).fetch_prices("ITX.MC")
    t = T.compute_technicals(serie)
    assert t.n_candles == 130 and t.symbol == "ITX.MC"
    assert t.range_low < t.last_close < t.range_high
    assert t.sma20 and t.sma50 and t.rsi14 and 0 < t.rsi14 < 100
    assert 0.05 < (t.volatility_annual or 0) < 0.8
    assert -1 < t.max_drawdown < 0
    assert t.trend in ("alcista", "bajista", "lateral")
    assert t.supports and all(s < t.last_close for s in t.supports)
    assert all(r >= t.last_close for r in t.resistances)
    assert t.range_low == pytest.approx(min(c.l for c in serie.candles))
