"""Exporta docs/pitch.md a docs/pitch.pdf como diapositivas 16:9 (una por página).

Herramienta de documentación (no forma parte de la app ni de requirements.txt):

    pip install playwright markdown     # usa el Edge o Chrome ya instalados
    python scripts/pitch_pdf.py [--navegador msedge|chrome]

La portada es lo anterior al primer `## ` y cada título `## ` abre una diapositiva. El script avisa si el
contenido de alguna no cabe en la página, para que lo recortes en lugar de entregar un PDF cortado.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import markdown
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parents[1]
ORIGEN = RAIZ / "docs" / "pitch.md"
DESTINO = RAIZ / "docs" / "pitch.pdf"
ANCHO_PX, ALTO_PX = 1280, 720  # 16:9; en PDF: 13,333 x 7,5 pulgadas

CSS = f"""
@page {{ size: {ANCHO_PX}px {ALTO_PX}px; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; background: #14120d; }}
body {{ font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; color: #ece7da; font-size: 19px; line-height: 1.45; }}
.slide {{ width: {ANCHO_PX}px; height: {ALTO_PX}px; padding: 54px 72px 62px; position: relative; overflow: hidden;
  page-break-after: always; break-after: page; background: #14120d; border-left: 10px solid #d6a63c; }}
.slide:last-child {{ page-break-after: auto; break-after: auto; }}
.contenido {{ height: 100%; }}
h1 {{ font-size: 54px; margin: 90px 0 16px; letter-spacing: .5px; color: #f4efe2; }}
h1 span {{ color: #d6a63c; }}
h2 {{ font-size: 36px; margin: 0 0 22px; color: #d6a63c; font-weight: 600; }}
p {{ margin: 0 0 14px; }}
strong {{ color: #f4efe2; }}
em {{ color: #c9c2ae; }}
a {{ color: #d6a63c; }}
code {{ background: #26221a; color: #e8c778; padding: 1px 7px; border-radius: 4px; font-family: Consolas, monospace; font-size: .88em; }}
blockquote {{ margin: 18px 0; padding: 4px 20px; border-left: 4px solid #6b5a2c; color: #b9b2a0; }}
blockquote p {{ margin: 6px 0; }}
ul {{ margin: 0 0 12px; padding-left: 26px; }}
li {{ margin-bottom: 9px; }}
table {{ border-collapse: collapse; width: 100%; margin: 6px 0 14px; font-size: 17px; }}
th {{ text-align: left; color: #d6a63c; border-bottom: 2px solid #6b5a2c; padding: 6px 12px; }}
td {{ padding: 5px 12px; border-bottom: 1px solid #2b2719; vertical-align: top; }}
.pie {{ position: absolute; left: 82px; right: 72px; bottom: 22px; display: flex; justify-content: space-between;
  color: #7d7766; font-size: 13px; letter-spacing: .6px; }}
"""


def a_diapositivas(texto: str) -> list[str]:
    """Portada (lo anterior al primer `## `) y una diapositiva por cada título `## `."""
    sin_lineas = re.sub(r"^\s*---\s*$", "", texto, flags=re.MULTILINE)
    bloques = re.split(r"^(?=## )", sin_lineas, flags=re.MULTILINE)
    return [b.strip() for b in bloques if b.strip()]


def a_html(bloques: list[str]) -> str:
    md = markdown.Markdown(extensions=["tables", "sane_lists"])
    total = len(bloques)
    secciones = []
    for n, bloque in enumerate(bloques, start=1):
        cuerpo = md.reset().convert(bloque)
        secciones.append(
            f'<section class="slide"><div class="contenido">{cuerpo}</div>'
            f'<div class="pie"><span>FinLens · Taller B5-T4 · Máster MIAX</span><span>{n} / {total}</span></div></section>'
        )
    return f'<!doctype html><html lang="es"><head><meta charset="utf-8"><style>{CSS}</style></head><body>{"".join(secciones)}</body></html>'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--navegador", default="msedge", help="canal de Playwright: msedge o chrome")
    args = ap.parse_args()

    bloques = a_diapositivas(ORIGEN.read_text(encoding="utf-8"))
    documento = a_html(bloques)
    with sync_playwright() as pw:
        navegador = pw.chromium.launch(channel=args.navegador, headless=True)
        page = navegador.new_page(viewport={"width": ANCHO_PX, "height": ALTO_PX})
        page.set_content(documento)
        page.wait_for_timeout(300)
        desbordadas = page.evaluate(
            """() => [...document.querySelectorAll('.slide')].map((s, i) => {
                const c = s.querySelector('.contenido');
                return [i + 1, c.scrollHeight, s.clientHeight - 62 - 54];
            }).filter(([i, usado, libre]) => usado > libre)"""
        )
        page.pdf(path=str(DESTINO), width=f"{ANCHO_PX}px", height=f"{ALTO_PX}px", print_background=True,
                 margin={"top": "0", "right": "0", "bottom": "0", "left": "0"})
        navegador.close()

    print(f"Generado {DESTINO.relative_to(RAIZ)} con {len(bloques)} diapositivas.")
    for numero, usado, libre in desbordadas:
        print(f"  AVISO: la diapositiva {numero} no cabe ({usado}px de contenido, {libre}px disponibles).")
    return 1 if desbordadas else 0


if __name__ == "__main__":
    sys.exit(main())
