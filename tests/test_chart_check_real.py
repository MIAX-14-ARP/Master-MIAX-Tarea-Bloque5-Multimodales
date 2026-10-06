"""Falsos positivos observados en el E2E real (Gemini leyendo el gráfico de BTC/AAPL), con frases literales."""
import json
from datetime import date

import httpx2 as httpx
import pytest

from _mercado import cargar, cliente
from finlens.domain.chart_check import _niveles_citados, check_chart_reading
from finlens.domain.schemas import ChartReading
from finlens.domain.technicals import TechnicalSummary, compute_technicals
from finlens.sources.hyperliquid import HyperliquidSource


@pytest.fixture(scope="module")
def btc() -> TechnicalSummary:
    def manejador(req: httpx.Request) -> httpx.Response:
        tipo = json.loads(req.content)["type"]
        return httpx.Response(200, json=cargar("hl_candles_btc_1d.json" if tipo == "candleSnapshot" else "hl_meta_ctxs.json"))

    return compute_technicals(HyperliquidSource(client=cliente(manejador)).fetch_prices("BTC"))


def lectura(*obs: str, descripcion: str = "Gráfico diario.", trend: str = "alcista") -> ChartReading:
    return ChartReading(trend=trend, description=descripcion, observations=list(obs))  # type: ignore[arg-type]


FECHAS = "Gráfico diario de velas de AAPL que abarca del 6 de abril de 2026 al 6 de octubre de 2026."


def test_los_anios_en_fechas_no_son_precios() -> None:
    assert _niveles_citados(FECHAS) == []
    for texto in ("desde abril de 2026 hasta octubre 2026", "en el año 2025", "6 abr 2026", "2026-04-06", "06/04/2026",
                  "del 6 de abril de 2026"):
        assert _niveles_citados(texto) == [], texto


def test_un_numero_de_cuatro_cifras_sin_contexto_de_fecha_sigue_siendo_precio() -> None:
    assert [t for t, _ in _niveles_citados("Soporte en 2000")] == ["2000"]
    assert [t for t, _ in _niveles_citados("cierra a 2694,30")] == ["2694,30"]


def test_frase_de_fechas_solo_genera_la_tendencia(btc: TechnicalSummary) -> None:
    c = check_chart_reading(lectura(descripcion=FECHAS), btc)
    assert [i.verdict for i in c.items] == ["confirmada"]


VOLUMEN = ("Volumen: se observan dos picos notorios de volumen, el primero (sobre 120K) a mediados de mayo "
           "y el segundo (100K) en agosto, con un nivel de 90K en septiembre.")


def test_el_volumen_no_genera_afirmaciones_de_precio(btc: TechnicalSummary) -> None:
    c = check_chart_reading(lectura(VOLUMEN), btc)
    assert [i.verdict for i in c.items] == ["confirmada"]


def test_frase_mixta_conserva_el_precio_y_descarta_el_volumen_en_k(btc: TechnicalSummary) -> None:
    c = check_chart_reading(lectura("Máximo del periodo en 87.471 con un volumen de 120K."), btc)
    assert [i.verdict for i in c.items] == ["confirmada", "confirmada"]
    assert "87.471" in c.items[1].claim


@pytest.mark.parametrize(
    "frase",
    [
        "Soporte relevante establecido en el rango de 58.000 - 60.000",
        "Zona de soporte intermedia 63.000 - 65.000",
        "Soporte en 62.380",
        "Resistencia máxima en 87.500",
        "Soporte dinámico en 82.000",
    ],
)
def test_soportes_historicos_reales_se_confirman(btc: TechnicalSummary, frase: str) -> None:
    c = check_chart_reading(lectura(frase), btc)
    assert c.items[1].verdict == "confirmada", c.items[1].detail
    assert len(c.items) == 2  # la zona «58.000 - 60.000» es UNA afirmación, no dos


def test_detalle_de_discrepancia_nombra_el_pivote_mas_cercano_real(btc: TechnicalSummary) -> None:
    c = check_chart_reading(lectura("Soporte clave en 70.000"), btc)
    item = c.items[1]
    assert item.verdict == "discrepa"
    assert "67,100.50" in item.detail  # el pivote real más cercano a 70.000
    assert "%" in item.detail


def test_zona_inventada_discrepa_y_nombra_el_nivel_mas_cercano(btc: TechnicalSummary) -> None:
    item = check_chart_reading(lectura("Soporte en la zona 40.000 - 42.000"), btc).items[1]
    assert item.verdict == "discrepa" and "57,768.00" in item.detail


def test_lectura_correcta_supera_el_85_por_ciento(btc: TechnicalSummary) -> None:
    c = check_chart_reading(
        lectura(
            "Soporte relevante establecido en el rango de 58.000 - 60.000",
            "Zona de soporte intermedia 63.000 - 65.000",
            "Resistencia en 87.471",
            VOLUMEN,
            "Cierre reciente cerca de 85.500, máximo del periodo en 87.471 y mínimo en 57.768",
            descripcion="Gráfico diario de velas de BTC que abarca del 8 de junio de 2026 al 6 de octubre de 2026. "
            "La SMA 20 cruza por encima de la SMA 50 y el precio sube un 48% desde mínimos.",
        ),
        btc,
    )
    assert c.agreement_score >= 0.85, [(i.verdict, i.claim) for i in c.items]
    assert all(i.verdict != "discrepa" for i in c.items)


def test_lectura_con_niveles_inventados_sigue_detectandolos(btc: TechnicalSummary) -> None:
    c = check_chart_reading(
        lectura(
            "Soporte clave en 40.000",
            "Resistencia en 120.000",
            "El precio llegó a tocar 150.000 en agosto",
            "Mínimo del periodo cerca de 20.000",
            descripcion=FECHAS,
        ),
        btc,
    )
    veredictos = [i.verdict for i in c.items]
    assert veredictos.count("discrepa") == 4
    assert c.agreement_score <= 0.25


def test_resumen_tecnico_expone_todos_los_pivotes(btc: TechnicalSummary) -> None:
    assert len(btc.pivots) > len(btc.supports) + len(btc.resistances)
    assert list(btc.pivots) == sorted(btc.pivots)
    assert set(btc.supports) <= set(btc.pivots) and set(btc.resistances) <= set(btc.pivots)
    assert btc.range_low == pytest.approx(57768.0) and btc.end == date(2026, 10, 6)
