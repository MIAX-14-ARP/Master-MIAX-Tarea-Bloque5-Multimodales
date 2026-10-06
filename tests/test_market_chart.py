"""Gráfico de velas generado: formato, dimensiones, robustez y que no anote indicadores."""
import ast
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx2 as httpx
import numpy as np
import pytest
from _mercado import cargar, cliente, serie_de_cierres
from PIL import Image

from finlens.domain import market_chart
from finlens.domain.infographic import COLOR_FONDO
from finlens.domain.market_chart import ALTO_PX, ANCHO_PX, render_market_chart
from finlens.sources.hyperliquid import HyperliquidSource
from finlens.sources.yahoo import YahooPrices

PNG = b"\x89PNG\r\n\x1a\n"


def imagen(datos: bytes) -> Image.Image:
    return Image.open(io.BytesIO(datos)).convert("RGB")


def serie_aleatoria(n: int = 120, semilla: int = 0, fuente: str = "yahoo"):  # type: ignore[no-untyped-def]
    rng = np.random.default_rng(semilla)
    return serie_de_cierres(list(100 * np.exp(np.cumsum(rng.normal(0.001, 0.015, n)))), fuente=fuente)


def test_devuelve_png_1400x900() -> None:
    datos = render_market_chart(serie_aleatoria())
    assert datos.startswith(PNG)
    assert imagen(datos).size == (ANCHO_PX, ALTO_PX) == (1400, 900)


def test_fondo_coherente_con_el_estilo_de_la_infografia() -> None:
    img = imagen(render_market_chart(serie_aleatoria()))
    esperado = tuple(int(COLOR_FONDO[i : i + 2], 16) for i in (1, 3, 5))
    assert img.getpixel((2, 2)) == esperado


def test_dibuja_contenido_no_es_una_imagen_vacia() -> None:
    img = imagen(render_market_chart(serie_aleatoria()))
    assert len(img.getcolors(maxcolors=1_000_000) or []) > 20


def test_es_determinista_para_la_misma_serie() -> None:
    s = serie_aleatoria()
    assert render_market_chart(s) == render_market_chart(s)


def test_series_distintas_dan_graficos_distintos() -> None:
    assert render_market_chart(serie_aleatoria(semilla=1)) != render_market_chart(serie_aleatoria(semilla=2))


@pytest.mark.parametrize("n", [2, 3, 10, 49, 51, 400])
def test_funciona_con_cualquier_longitud(n: int) -> None:
    assert imagen(render_market_chart(serie_aleatoria(n))).size == (1400, 900)


def test_serie_plana_y_volumen_cero() -> None:
    plana = serie_de_cierres([100.0] * 30, margen=0.0)
    assert render_market_chart(plana).startswith(PNG)
    sin_volumen = serie_aleatoria(40)
    sin_volumen = type(sin_volumen)(
        symbol="X", currency="", source="otra", meta={},
        candles=tuple(type(c)(c.t, c.o, c.h, c.l, c.c, 0.0) for c in sin_volumen.candles),
    )
    assert render_market_chart(sin_volumen).startswith(PNG)


def test_precios_muy_pequenos_y_muy_grandes() -> None:
    assert render_market_chart(serie_de_cierres(list(np.linspace(0.0002, 0.0003, 40)))).startswith(PNG)
    assert render_market_chart(serie_de_cierres(list(np.linspace(90_000, 110_000, 40)))).startswith(PNG)


def test_menos_de_dos_velas_lanza_valueerror() -> None:
    with pytest.raises(ValueError, match="al menos 2"):
        render_market_chart(serie_de_cierres([100.0]))


def test_con_series_reales_grabadas() -> None:
    itx = YahooPrices(client=cliente(lambda r: httpx.Response(200, json=cargar("yahoo_itx_6mo.json")))).fetch_prices("ITX.MC")

    def servidor(req: httpx.Request) -> httpx.Response:
        import json

        tipo = json.loads(req.content)["type"]
        datos = cargar("hl_candles_btc_1d.json" if tipo == "candleSnapshot" else "hl_meta_ctxs.json")
        return httpx.Response(200, json=datos)

    btc = HyperliquidSource(client=cliente(servidor)).fetch_prices("BTC")
    for serie in (itx, btc):
        assert imagen(render_market_chart(serie)).size == (1400, 900)


def test_se_puede_llamar_desde_varios_hilos() -> None:
    series = [serie_aleatoria(80, semilla=i) for i in range(6)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        resultados = list(pool.map(render_market_chart, series))
    assert all(r.startswith(PNG) for r in resultados)
    assert resultados == [render_market_chart(s) for s in series]


def test_no_usa_pyplot_ni_anota_indicadores() -> None:
    """Pyplot no es seguro entre hilos; y el gráfico no debe llevar valores de indicadores (RSI, medias)."""
    fuente = Path(market_chart.__file__).read_text(encoding="utf-8")
    importados = {n.module for n in ast.walk(ast.parse(fuente)) if isinstance(n, ast.ImportFrom) and n.module}
    assert not any("pyplot" in m for m in importados)
    assert "RSI" not in fuente and "annotate" not in fuente
