"""Genera las capturas del README en docs/img/ recorriendo la app con un navegador real.

Herramienta opcional de documentación (no forma parte de la app ni de requirements.txt):

    pip install playwright            # usa el Edge o Chrome ya instalados, no descarga navegadores
    streamlit run app.py              # en otra terminal (modo demo o con claves)
    python scripts/capturas.py [--url http://localhost:8501] [--navegador msedge|chrome]

Las capturas reflejan el modo en el que esté la app. En modo demo las respuestas son simuladas:
para el README final conviene repetirlas con claves reales.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

SALIDA = Path(__file__).resolve().parents[1] / "docs" / "img"


def foto(page: Page, nombre: str) -> None:
    ruta = SALIDA / nombre
    page.screenshot(path=str(ruta))
    print(f"  guardada {ruta.relative_to(SALIDA.parents[1])}")


def abrir_pestana(page: Page, nombre: str) -> None:
    page.get_by_role("tab", name=nombre).click()
    page.wait_for_timeout(600)
    page.get_by_role("tablist").scroll_into_view_if_needed()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8501")
    ap.add_argument("--navegador", default="msedge", help="canal de Playwright: msedge o chrome")
    args = ap.parse_args()
    SALIDA.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        navegador = pw.chromium.launch(channel=args.navegador, headless=True)
        page = navegador.new_page(viewport={"width": 1280, "height": 1500})
        page.goto(args.url)
        page.get_by_role("button", name="Analizar").wait_for(timeout=30_000)
        page.wait_for_timeout(800)
        page.screenshot(path=str(SALIDA / "home.png"), clip={"x": 0, "y": 0, "width": 1280, "height": 830})
        print("  guardada docs/img/home.png")

        page.get_by_role("button", name="Analizar").click()
        page.get_by_role("tab", name="Traza de modelos").wait_for(timeout=60_000)
        page.wait_for_selector("audio", state="attached", timeout=60_000)  # medios ya generados
        page.wait_for_timeout(1000)

        abrir_pestana(page, "Informe")
        foto(page, "informe.png")
        abrir_pestana(page, "Entradas leídas")
        foto(page, "entradas.png")
        abrir_pestana(page, "Audio e infografía")
        foto(page, "medios.png")
        abrir_pestana(page, "Traza de modelos")
        foto(page, "traza.png")
        navegador.close()


if __name__ == "__main__":
    main()
