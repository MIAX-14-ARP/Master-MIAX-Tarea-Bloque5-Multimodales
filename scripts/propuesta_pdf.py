"""Genera docs/propuesta_mvpFinlens.pdf: propuesta de MVP (punto 4.1 del enunciado) con gráficos y cifras.

Herramienta de documentación (no forma parte de la app ni de requirements.txt):

    pip install playwright               # usa el Edge o Chrome ya instalados
    python scripts/propuesta_pdf.py --password <contraseña de la demo> [--navegador msedge|chrome]

Las cifras de coste y latencia se leen de docs/medidas.md (salida de scripts/medir.py), de modo que el PDF
se actualiza al repetir la medición. Los precios de los planes y el objetivo de latencia son hipótesis
del equipo y están en las constantes de este fichero.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parents[1]
MEDIDAS = RAIZ / "docs" / "medidas.md"
DESTINO = RAIZ / "docs" / "propuesta_mvpFinlens.pdf"

# --- Datos del proyecto y del despliegue -------------------------------------------------------
URL_DEMO = "https://108-128-114-211.sslip.io"
PASSWORD_DEMO = os.environ.get("FINLENS_DEMO_PASSWORD", "")  # no se guarda en el código: ver --password
REPO = "https://github.com/piettro/Master-MIAX-Tarea-Bloque5-Multimodales"
EQUIPO = "Piettro Rodrigues, Alonso y Raúl Rodríguez"

# --- Hipótesis de negocio (editables) ----------------------------------------------------------
COSTE_ANALISIS_EUR = 0.055  # ≈ 0,060 USD con 1 USD ≈ 0,92 €
OBJETIVO_NOTA_S, OBJETIVO_TODO_S = 30.0, 60.0
INFRA_USD_MES = 12  # EC2 t3.micro + IPv4 + 12 GB gp3 (docs/DESPLIEGUE.md)
PLANES = [  # nombre, precio €/mes (o €/análisis en API), análisis incluidos, descripción
    ("Free", 0.0, 5, "Probar: solo nota, marca de agua"),
    ("Pro", 49.0, 150, "Analista individual: audio, infografía, chat, mercado"),
    ("Team", 390.0, 1000, "Gestoras y EAFI (5 usuarios), espacio compartido"),
    ("API", 0.25, 1, "Brokers (B2B2C): pago por análisis"),
]

ORO, AZUL, GRIS, VERDE, ROJO = "#b8862b", "#14233c", "#8b93a1", "#2e8b57", "#c0392b"


# --- Lectura de docs/medidas.md ----------------------------------------------------------------
def es(valor: float, decimales: int = 1) -> str:
    """Formato español: coma decimal y punto de millar."""
    texto = f"{valor:,.{decimales}f}"
    return texto.replace(",", "§").replace(".", ",").replace("§", ".")


def filas_tabla(seccion: str) -> list[list[str]]:
    """Filas de datos de las tablas Markdown de una sección (sin separadores ni cabeceras vacías)."""
    filas = []
    for linea in seccion.splitlines():
        linea = linea.strip()
        if not linea.startswith("|"):
            continue
        celdas = [c.strip() for c in linea.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in celdas):
            continue
        filas.append(celdas)
    return filas


def leer_medidas(ruta: Path) -> dict:
    t = ruta.read_text(encoding="utf-8")
    secciones = re.split(r"^## ", t, flags=re.MULTILINE)
    coste = next((s for s in secciones if s.startswith("Coste medio")), "")
    latencia = next((s for s in secciones if s.startswith("Latencia")), "")
    filas_coste, total = [], 0.0
    for nombre, uso, valor, *_ in (f + [""] * 3 for f in filas_tabla(coste)):
        if nombre == "Componente":
            continue
        if "Total" in nombre:
            total = float(valor.strip("*"))
        else:
            filas_coste.append((nombre, uso, float(valor)))
    pasos = [
        (f[0], f[1], float(f[2]), float(f[3]), int(f[4]))
        for f in filas_tabla(latencia) if f[0] != "Paso" and len(f) >= 5
    ]
    nota = re.search(r"Informe en pantalla\*\*.*?media ([\d.]+) s, máx\. ([\d.]+) s", latencia)
    todo = re.search(r"Todo, incluidos audio e infografía\*\*: media ([\d.]+) s, máx\. ([\d.]+) s", latencia)
    ejecuciones = re.search(r"Ejecuciones medidas: \*\*(\d+)\*\*", t)
    real = re.search(r"\*\*(\d+)\s?% real\*\*", t)
    if not (filas_coste and total and pasos and nota and todo and ejecuciones):
        raise SystemExit("docs/medidas.md no tiene el formato esperado (¿se regeneró con otra versión de medir.py?)")
    return {
        "n": int(ejecuciones.group(1)), "costes": filas_coste, "total": total, "pasos": pasos,
        "nota": (float(nota.group(1)), float(nota.group(2))), "todo": (float(todo.group(1)), float(todo.group(2))),
        "real": int(real.group(1)) if real else None,
    }


def formatear_uso(uso: str) -> str:
    """Convierte «8,849 / 3,092» o «0.7 min» al formato español."""
    def num(m: re.Match) -> str:
        v = float(m.group(0).replace(",", ""))
        return es(v, 0 if v >= 100 or v == int(v) else 1)
    return re.sub(r"[\d,]+(?:\.\d+)?", num, uso)


# --- Gráficos SVG --------------------------------------------------------------------------------
def barras(items: list[tuple[str, float, str, str]], ancho: int = 700, etiqueta: int = 230, alto_barra: int = 22,
           hueco: int = 9, maximo: float | None = None) -> str:
    """Barras horizontales: (etiqueta, valor, color, texto del valor)."""
    maximo = maximo or max(v for _, v, _, _ in items)
    util = ancho - etiqueta - 165
    alto = len(items) * (alto_barra + hueco) + hueco
    partes = [f'<svg viewBox="0 0 {ancho} {alto}" width="100%" xmlns="http://www.w3.org/2000/svg" class="grafico">']
    for i, (nombre, valor, color, texto) in enumerate(items):
        y = hueco + i * (alto_barra + hueco)
        w = max(2.0, util * valor / maximo)
        partes.append(f'<text x="{etiqueta - 10}" y="{y + alto_barra * 0.7}" text-anchor="end" class="eje">{nombre}</text>')
        partes.append(f'<rect x="{etiqueta}" y="{y}" width="{w:.1f}" height="{alto_barra}" rx="3" fill="{color}"/>')
        partes.append(f'<text x="{etiqueta + w + 8:.1f}" y="{y + alto_barra * 0.7}" class="valor">{texto}</text>')
    partes.append("</svg>")
    return "".join(partes)


def objetivo_vs_medido(nota: float, todo: float) -> str:
    """Dos barras con el valor medido y una marca en el objetivo, en una escala común de 0 a 70 s."""
    ancho, x0, util, escala = 700, 190, 420, 70.0
    filas = [("Nota en pantalla", nota, OBJETIVO_NOTA_S), ("Análisis completo", todo, OBJETIVO_TODO_S)]
    partes = [f'<svg viewBox="0 0 {ancho} 118" width="100%" xmlns="http://www.w3.org/2000/svg" class="grafico">']
    for i, (nombre, medido, objetivo) in enumerate(filas):
        y = 14 + i * 50
        partes.append(f'<text x="{x0 - 10}" y="{y + 17}" text-anchor="end" class="eje">{nombre}</text>')
        partes.append(f'<rect x="{x0}" y="{y}" width="{util}" height="24" rx="3" fill="#eef0f4"/>')
        partes.append(f'<rect x="{x0}" y="{y}" width="{util * medido / escala:.1f}" height="24" rx="3" fill="{ORO}"/>')
        xo = x0 + util * objetivo / escala
        partes.append(f'<line x1="{xo:.1f}" y1="{y - 6}" x2="{xo:.1f}" y2="{y + 30}" stroke="{ROJO}" stroke-width="2" stroke-dasharray="4 3"/>')
        partes.append(f'<text x="{x0 + util + 14}" y="{y + 17}" class="valor">{es(medido)} s</text>')
        partes.append(f'<text x="{xo:.1f}" y="{y + 43}" text-anchor="middle" class="nota-eje" fill="{ROJO}">objetivo {es(objetivo, 0)} s</text>')
    partes.append("</svg>")
    return "".join(partes)


def margenes(filas: list[tuple[str, float, float, float]]) -> str:
    """Barras apiladas al 100 %: (plan, coste IA %, margen %, texto)."""
    ancho, x0, util = 700, 120, 440
    partes = [f'<svg viewBox="0 0 {ancho} {len(filas) * 44 + 8}" width="100%" xmlns="http://www.w3.org/2000/svg" class="grafico">']
    for i, (plan, coste, margen, texto) in enumerate(filas):
        y = 8 + i * 44
        wc, wm = util * coste / 100, util * margen / 100
        partes.append(f'<text x="{x0 - 10}" y="{y + 20}" text-anchor="end" class="eje"><tspan font-weight="700">{plan}</tspan></text>')
        partes.append(f'<rect x="{x0}" y="{y}" width="{wc:.1f}" height="28" fill="{GRIS}"/>')
        partes.append(f'<rect x="{x0 + wc:.1f}" y="{y}" width="{wm:.1f}" height="28" fill="{VERDE}"/>')
        if wc > 40:
            partes.append(f'<text x="{x0 + wc / 2:.1f}" y="{y + 19}" text-anchor="middle" class="sobre">{es(coste, 0)} %</text>')
        partes.append(f'<text x="{x0 + wc + wm / 2:.1f}" y="{y + 19}" text-anchor="middle" class="sobre">margen {es(margen, 0)} %</text>')
        partes.append(f'<text x="{x0 + util + 12}" y="{y + 19}" class="valor">{texto}</text>')
    partes.append("</svg>")
    return "".join(partes)


def flujo() -> str:
    """Diagrama de datos: entradas → percepción → razonamiento → control → salidas."""
    columnas = [
        ("ENTRADAS", ["PDF del informe", "Gráfico de velas", "Audio / voz", "Pregunta", "Ticker"]),
        ("PERCEPCIÓN", ["Embeddings|bge-m3", "Visión|gemini-3.8-flash", "Voz a texto|whisper-large-v3-turbo", "Datos de mercado|Yahoo · SEC · Hyperliquid"]),
        ("RAZONAMIENTO", ["LLM analista|claude-sonnet-5.5"]),
        ("CONTROL (PYTHON)", ["Guardrails de compliance", "Verificación de cifras", "Contraste visión ↔ datos"]),
        ("SALIDAS", ["Nota citada|y verificada", "Audio +|infografía", "Chat · PDF|traza de coste"]),
    ]
    ancho_col, hueco, alto_caja, sep = 128, 24, 34, 8
    ancho = len(columnas) * ancho_col + (len(columnas) - 1) * hueco
    alto_max = max(len(c[1]) for c in columnas) * (alto_caja + sep) + 30
    partes = [f'<svg viewBox="0 0 {ancho} {alto_max}" width="100%" xmlns="http://www.w3.org/2000/svg" class="grafico">',
              f'<defs><marker id="f" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="{ORO}"/></marker></defs>']
    for c, (titulo, cajas) in enumerate(columnas):
        x = c * (ancho_col + hueco)
        total = len(cajas) * (alto_caja + sep) - sep
        y0 = 24 + (alto_max - 24 - total) / 2
        partes.append(f'<text x="{x + ancho_col / 2}" y="14" text-anchor="middle" class="col">{titulo}</text>')
        for i, texto in enumerate(cajas):
            y = y0 + i * (alto_caja + sep)
            fondo = "#fdf6e7" if c in (0, 4) else "#eef2f8"
            borde = ORO if c == 3 else AZUL
            lineas = texto.split("|")
            partes.append(f'<rect x="{x}" y="{y:.1f}" width="{ancho_col}" height="{alto_caja}" rx="5" fill="{fondo}" stroke="{borde}" stroke-width="1.2"/>')
            for j, linea in enumerate(lineas):
                dy = alto_caja / 2 + 3.5 + (j - (len(lineas) - 1) / 2) * 11
                partes.append(f'<text x="{x + ancho_col / 2}" y="{y + dy:.1f}" text-anchor="middle" class="caja">{linea}</text>')
        if c < len(columnas) - 1:
            ya = alto_max / 2 + 6
            partes.append(f'<line x1="{x + ancho_col + 3}" y1="{ya}" x2="{x + ancho_col + hueco - 3}" y2="{ya}" stroke="{ORO}" stroke-width="2" marker-end="url(#f)"/>')
    partes.append("</svg>")
    return "".join(partes)


# --- Documento -----------------------------------------------------------------------------------
CSS = """
@page { size: A4; margin: 16mm 15mm 18mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif; color: #1c2230; font-size: 10pt; line-height: 1.38; margin: 0; }
h1 { font-size: 27pt; margin: 0; color: #14233c; letter-spacing: -.3px; }
h1 span { color: #b8862b; }
h2 { font-size: 15pt; color: #14233c; border-bottom: 2px solid #b8862b; padding-bottom: 3px; margin: 16px 0 8px; break-after: avoid; }
h3 { font-size: 11pt; color: #14233c; margin: 11px 0 4px; break-after: avoid; }
p { margin: 0 0 5px; }
ul { margin: 2px 0 8px; padding-left: 18px; } li { margin-bottom: 2px; }
.sub { color: #55607a; font-size: 12pt; margin: 3px 0 10px; }
.meta { color: #55607a; font-size: 9.4pt; }
.acceso { border: 1.5px solid #b8862b; background: #fdf6e7; border-radius: 6px; padding: 9px 14px; margin: 12px 0 4px; font-size: 10pt; break-inside: avoid; }
.acceso table { width: 100%; border-collapse: collapse; } .acceso td { border: 0; padding: 1px 0; vertical-align: top; }
.acceso td:first-child { width: 120px; font-weight: 700; color: #14233c; }
.acceso code { font-size: 10.5pt; background: #fff; border: 1px solid #e3cf9d; }
.kpis { display: flex; gap: 8px; margin: 10px 0 6px; break-inside: avoid; }
.kpi { flex: 1; border: 1px solid #d8dde7; border-radius: 6px; padding: 7px 10px; background: #f6f8fb; }
.kpi b { display: block; font-size: 17pt; color: #14233c; line-height: 1.1; } .kpi span { font-size: 8.6pt; color: #55607a; }
table { width: 100%; border-collapse: collapse; margin: 5px 0 8px; font-size: 9pt; }
tr { break-inside: avoid; }
thead { display: table-header-group; }
th { text-align: left; background: #14233c; color: #fff; padding: 5px 8px; font-weight: 600; }
td { padding: 3px 8px; border-bottom: 1px solid #e1e5ed; vertical-align: top; }
tr:nth-child(even) td { background: #f8f9fc; }
td.n, th.n { text-align: right; white-space: nowrap; }
code { font-family: Consolas, monospace; font-size: 8.6pt; background: #f0f2f6; padding: 0 4px; border-radius: 3px; }
.grafico { display: block; margin: 4px 0 6px; } figure { margin: 4px 0 6px; break-inside: avoid; }
figcaption { font-size: 8.8pt; color: #55607a; margin-top: 2px; }
svg text { font-family: "Segoe UI", Arial, sans-serif; fill: #1c2230; }
svg .eje { font-size: 11.5px; } svg .valor { font-size: 11.5px; font-weight: 700; } svg .nota-eje { font-size: 10px; }
svg .sobre { font-size: 11px; font-weight: 700; fill: #fff; } svg .col { font-size: 8.5px; font-weight: 700; fill: #b8862b; letter-spacing: .6px; }
svg .caja { font-size: 8.6px; }
.nota { font-size: 8.8pt; color: #55607a; }
.ok { color: #2e8b57; font-weight: 700; } .aviso { color: #c0392b; font-weight: 700; }
.salto { break-before: page; }
.junto { break-inside: avoid; }
"""


def construir(m: dict, password: str = "") -> str:
    total, pasos = m["total"], m["pasos"]
    nota, todo = m["nota"], m["todo"]
    por_clave = {c.split(" ")[0]: (c, u, v) for c, u, v in m["costes"]}
    etiquetas = {
        "LLM": "LLM · análisis + prompt (claude-sonnet-5.5)", "Imagen": "Imagen · flux.2-klein-4b",
        "TTS": "Texto a voz · kokoro-82m", "STT": "Voz a texto · whisper-large-v3-turbo", "Embeddings": "Embeddings · bge-m3",
    }
    orden = sorted(por_clave.items(), key=lambda kv: -kv[1][2])
    barras_coste = barras([
        (etiquetas.get(k, k), v, ORO if k in ("LLM", "Imagen") else AZUL, f"{es(v, 4)} USD · {es(100 * v / total, 1)} %")
        for k, (_, _, v) in orden
    ], maximo=orden[0][1][2])
    tabla_coste = "".join(
        f"<tr><td>{etiquetas.get(k, k)}</td><td class='n'>{formatear_uso(u)}</td><td class='n'>{es(v, 4)}</td><td class='n'>{es(100 * v / total, 1)} %</td></tr>"
        for k, (_, u, v) in orden
    )
    menores = sum(v for k, (_, _, v) in por_clave.items() if k in ("STT", "TTS", "Embeddings"))
    nombres_paso = {"Índice semántico (embeddings)": "Índice semántico (embeddings)", "Composición de infografía": "Composición de la infografía"}
    barras_lat = barras([
        (nombres_paso.get(p, p), media, GRIS if ("reglas" in mod or "pypdf" in mod) else ORO, f"{es(media, 1)} s")
        for p, mod, media, _, _ in pasos
    ], etiqueta=215, alto_barra=17, hueco=6)
    mas_lento = max(pasos, key=lambda p: p[2])

    coste_mes = lambda n: n * total  # noqa: E731
    escala = "".join(
        f"<tr><td class='n'>{es(n, 0)}</td><td class='n'>{es(coste_mes(n), 2)}</td><td class='n'>{es(coste_mes(n) + INFRA_USD_MES, 2)}</td></tr>"
        for n in (100, 1000, 10000)
    )
    filas_plan, datos_margen, peores = [], [], []
    for nombre, precio, cupo, desc in PLANES:
        if nombre == "Free":
            coste = cupo * COSTE_ANALISIS_EUR
            filas_plan.append(f"<tr><td><b>{nombre}</b></td><td>{desc}</td><td class='n'>0 €</td><td class='n'>{cupo}</td><td class='n'>{es(coste, 2)} €</td><td class='n'>captación</td></tr>")
            continue
        coste = cupo * COSTE_ANALISIS_EUR
        margen = 100 * (precio - coste) / precio
        peor = 100 * (precio - 2 * coste) / precio
        peores.append((nombre, peor))
        precio_txt = f"{es(precio, 2)} €/análisis" if nombre == "API" else f"{es(precio, 0)} €/mes"
        cupo_txt = "por uso" if nombre == "API" else es(cupo, 0)
        filas_plan.append(
            f"<tr><td><b>{nombre}</b></td><td>{desc}</td><td class='n'>{precio_txt}</td><td class='n'>{cupo_txt}</td>"
            f"<td class='n'>{es(coste, 3 if nombre == 'API' else 2)} €</td><td class='n'><b>{es(margen, 0)} %</b> (×2 coste: {es(peor, 0)} %)</td></tr>"
        )
        datos_margen.append((nombre, 100 - margen, margen, f"{precio_txt}"))
    grafico_margen = margenes(datos_margen)
    sens = ", ".join(f"{es(v, 0)} % ({n})" for n, v in peores)
    hoy = date.today()
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

    filas_modelo = [
        ("Texto → texto", "Análisis, síntesis y chat con citas", "<code>anthropic/claude-sonnet-5.5</code>"),
        ("Imagen → texto", "Lectura del gráfico de velas", "<code>google/gemini-3.8-flash</code>"),
        ("Voz → texto", "Transcripción de la conferencia y de la pregunta", "<code>openai/whisper-large-v3-turbo</code>"),
        ("Texto → voz", "Resumen hablado con aviso legal", "<code>hexgrad/kokoro-82m</code>"),
        ("Texto → imagen", "Ilustración de la infografía (las cifras las dibuja Python)", "<code>black-forest-labs/flux.2-klein-4b</code>"),
        ("Embeddings", "Búsqueda multilingüe en el PDF (pregunta en español, informe en inglés)", "<code>baai/bge-m3</code>"),
        ("Datos", "Precios, derivados on-chain y fundamentales oficiales", "Yahoo Finance · Hyperliquid · SEC EDGAR"),
    ]
    tabla_modelos = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td></tr>" for a, b, c in filas_modelo)

    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><style>{CSS}</style></head><body>

<h1>Fin<span>Lens</span> · Propuesta de MVP</h1>
<p class="sub">Research financiero multimodal con cifras verificadas</p>
<p class="meta">Taller B5-T4 · Máster en IA y computación cuantitativa aplicada a mercados financieros (Instituto BME)<br>
Equipo: {EQUIPO} · {hoy.day} de {meses[hoy.month - 1]} de {hoy.year} · Startup ficticia: el modelo de negocio es un ejercicio.</p>

<div class="acceso"><table>
<tr><td>Demo desplegada</td><td><code>{URL_DEMO}</code></td></tr>
<tr><td>Contraseña</td><td>{('<code>' + password + '</code>') if password else 'solicítala al equipo'}</td></tr>
<tr><td>Despliegue</td><td>AWS · región <code>eu-west-1</code> · EC2 t3.micro + Caddy (HTTPS) · imagen en ECR · secretos en Secrets Manager · CI/CD con GitHub Actions</td></tr>
<tr><td>Repositorio</td><td><code>{REPO}</code></td></tr>
</table></div>

<h2>Resumen</h2>
<div class="kpis">
<div class="kpi"><b>{es(total, 3)} USD</b><span>coste por análisis completo ({m['n']} ejecuciones medidas, {(str(int(m['real'])) + ' % coste real') if m['real'] else 'coste estimado'})</span></div>
<div class="kpi"><b>{es(todo[0], 1)} s</b><span>análisis completo · nota en pantalla en {es(nota[0], 1)} s</span></div>
<div class="kpi"><b>6 + 3</b><span>modelos de IA especializados + fuentes de datos</span></div>
<div class="kpi"><b>≈ 83 %</b><span>margen bruto del plan Pro sobre el coste de IA</span></div>
</div>
<ul>
<li><b>Problema:</b> el analista cruza a mano informe, gráfico, audio y mercado, y la IA genérica inventa cifras.</li>
<li><b>Solución:</b> una consulta devuelve una nota donde <b>cada cifra cita su fuente y la verifica el código</b>, no el LLM.</li>
<li><b>Viabilidad:</b> el coste y la latencia están medidos con APIs reales y cumplen el objetivo del MVP.</li>
<li><b>Compliance:</b> la herramienta informa y no asesora; hay un guardrail determinista y un aviso legal en cada salida.</li>
</ul>

<h2>1. Definición del producto</h2>
<h3>1.1 Problema</h3>
<ul>
<li>La información vive en <b>cuatro formatos sin conexión</b>: informe anual en PDF (cientos de páginas, a menudo en inglés), gráfico de cotización, audio de la conferencia de resultados y datos de mercado.</li>
<li>El cruce se hace <b>a mano</b>: horas por empresa y sin trazabilidad de cada dato.</li>
<li>Los asistentes de IA genéricos <b>inventan cifras</b>. En finanzas, un número falso es un riesgo regulatorio y reputacional.</li>
</ul>

<h3>1.2 Público objetivo</h3>
<table>
<tr><th>Segmento</th><th>Modelo</th><th>Necesidad</th><th>Prioridad</th></tr>
<tr><td>Analistas junior y <i>sell-side</i></td><td>B2B</td><td>Reducir horas de lectura y de cruce de fuentes</td><td>Núcleo</td></tr>
<tr><td>EAFI y asesores independientes</td><td>B2B</td><td>Respaldar sus informes con fuente citada</td><td>Núcleo</td></tr>
<tr><td>Gestoras boutique y relación con inversores</td><td>B2B</td><td>Notas de research trazables y rápidas</td><td>Núcleo</td></tr>
<tr><td>Plataformas de brokers</td><td>B2B2C</td><td>Embeber el análisis en su producto vía API</td><td>Extensión</td></tr>
<tr><td>Inversor minorista</td><td>B2C</td><td>—</td><td>Fuera del MVP: mayor riesgo regulatorio (asesoramiento personalizado)</td></tr>
</table>

<h3>1.3 Propuesta de valor diferencial</h3>
<ul>
<li><b>Cifras verificadas.</b> Python comprueba que cada número aparece en la página citada del PDF, en los fundamentales de la SEC o en los indicadores calculados. El LLM no se evalúa a sí mismo.</li>
<li><b>«La IA vio · los datos dicen».</b> Cada nivel o tendencia que lee el modelo de visión se contrasta con la serie real de precios. Detecta alucinaciones visuales.</li>
<li><b>Cruce entre modalidades.</b> Informe ↔ gráfico ↔ dirección ↔ mercado. La nota señala coincidencias y contradicciones.</li>
</ul>

<h3>1.4 Multimodalidad: qué aporta cada modelo</h3>
<table><tr><th>Modalidad</th><th>Función</th><th>Modelo</th></tr>{tabla_modelos}</table>
<p>El MVP admite <b>6 entradas</b> (PDF, gráfico, audio, voz, texto, ticker) y produce <b>7 salidas</b> (nota verificada, contraste visión↔datos, audio, infografía, chat, nota en PDF, traza de coste). Ningún modelo único cubre toda la cadena; el valor está en orquestarlos.</p>
<figure>{flujo()}<figcaption>Flujo de datos. Las ramas de percepción corren en paralelo; los pasos de control son deterministas.</figcaption></figure>

<h2>2. Viabilidad técnica y económica</h2>
<h3>2.1 Costes de inferencia</h3>
<p>Medido con APIs reales sobre el informe anual 2025 de Inditex (gráfico de ITX.MC y audio): <b>{m['n']} ejecuciones, 0 fallos</b>. {('El ' + str(int(m['real'])) + ' % del coste lo informa el proveedor; el resto se estima con tarifas de respaldo.') if m['real'] else ''}</p>
<figure>{barras_coste}<figcaption>Coste medio por análisis completo (USD) y peso sobre el total de {es(total, 4)} USD.</figcaption></figure>
<table><tr><th>Componente</th><th class="n">Uso medio</th><th class="n">Coste (USD)</th><th class="n">% del total</th></tr>
{tabla_coste}
<tr><td><b>Total por análisis</b></td><td></td><td class="n"><b>{es(total, 4)}</b></td><td class="n"><b>100 %</b></td></tr></table>
<ul>
<li>El <b>LLM y la imagen</b> concentran casi todo el coste. Voz, TTS y embeddings suman {es(100 * menores / total, 1)} %.</li>
<li>Omitir la infografía ahorra la imagen y su prompt. Un modelo más barato para el análisis (<code>gemini-3.8-flash</code>) baja el coste del LLM.</li>
<li>Palancas ya implementadas: recuperación híbrida (no se envía el PDF entero), límite de entrada, caché, razonamiento acotado y modelos abiertos baratos.</li>
</ul>
<table><tr><th class="n">Análisis al mes</th><th class="n">Coste de IA (USD)</th><th class="n">+ infraestructura de la demo ({INFRA_USD_MES} USD)</th></tr>{escala}</table>
<p class="nota">La infraestructura de la demo (1 instancia EC2 t3.micro, IPv4 y disco; ≈{INFRA_USD_MES} USD/mes) está dimensionada para pruebas, no para producción.</p>

<h3>2.2 Latencias para una experiencia fluida</h3>
<p>FinLens no es un chat en tiempo real: sustituye horas de trabajo manual. Proponemos como <b>objetivo del MVP</b> la nota en pantalla en <b>≤ {es(OBJETIVO_NOTA_S, 0)} s</b> y el análisis completo en <b>≤ {es(OBJETIVO_TODO_S, 0)} s</b>. La nota se muestra antes que el audio y la infografía (render progresivo).</p>
<figure>{objetivo_vs_medido(nota[0], todo[0])}<figcaption>Latencia media medida frente al objetivo (marca roja). Máximos: nota {es(nota[1], 1)} s, total {es(todo[1], 1)} s.</figcaption></figure>
<figure>{barras_lat}<figcaption>Latencia media por paso (s). Dorado: modelo de IA. Gris: paso local. Las ramas paralelas se solapan, por eso los pasos no suman el total.</figcaption></figure>
<ul>
<li>El paso más lento es «{mas_lento[0]}» ({es(mas_lento[2], 1)} s).</li>
<li>Visión, transcripción, embeddings, datos de mercado y SEC corren <b>en paralelo</b>. Después corren en paralelo audio e infografía.</li>
<li>Para bajar la latencia: modelo más rápido en el análisis, <i>streaming</i> de la respuesta y caché del índice por documento.</li>
</ul>

<h3>2.3 Marco regulatorio: compliance y privacidad</h3>
<table>
<tr><th>Marco</th><th>Riesgo</th><th>Medida en el MVP</th><th>Pendiente en producción</th></tr>
<tr><td><b>MiFID II / CNMV</b></td><td>Pasar de informar a asesorar</td><td>Guardrail determinista (ES/EN) que retira la frase de recomendación; aviso legal en cada salida, también hablado</td><td>Revisión legal del guardrail (es heurístico)</td></tr>
<tr><td><b>RGPD</b></td><td>Tratar documentos del usuario</td><td>No se almacenan documentos; la caché vive en memoria de la sesión; aviso de envío a proveedores de IA</td><td>DPA con los proveedores; residencia de datos en la UE</td></tr>
<tr><td><b>Datos bancarios (PSD2)</b></td><td>Acceso a cuentas de clientes</td><td>Fuera del MVP: no se conecta a cuentas ni pide datos bancarios</td><td>Proveedor autorizado (AISP) o socio, consentimiento explícito y revocable, minimización y cifrado</td></tr>
<tr><td><b>AI Act</b></td><td>Transparencia del contenido generado</td><td>Todo se marca como generado por IA; cada afirmación cita su fuente</td><td>Evaluación sistemática de precisión</td></tr>
<tr><td><b>Licencias de datos</b></td><td>Yahoo Finance es una API no oficial</td><td>Uso académico</td><td>Proveedor con licencia (p. ej. BME Market Data)</td></tr>
<tr><td><b>Seguridad de la demo</b></td><td>Gasto de crédito por terceros</td><td>Contraseña, secretos en Secrets Manager, OIDC entre GitHub y AWS, sin SSH, HTTPS</td><td>Autenticación real y multiusuario</td></tr>
</table>

<h3>2.4 Modelo de monetización</h3>
<div class="junto"><p>SaaS B2B por volumen de análisis. Coste variable medido: <b>{es(total, 3)} USD ≈ {es(COSTE_ANALISIS_EUR, 3)} €</b> por análisis completo (1 USD ≈ 0,92 €). Los precios son <b>hipótesis</b> de la práctica.</p>
<table><tr><th>Plan</th><th>Para quién</th><th class="n">Precio</th><th class="n">Análisis/mes</th><th class="n">Coste IA máx.</th><th class="n">Margen bruto</th></tr>{''.join(filas_plan)}</table></div>
<figure>{grafico_margen}<figcaption>Reparto del precio entre coste de IA y margen bruto, con el plan usado al máximo de su cupo.</figcaption></figure>
<ul>
<li>Margen bruto = (precio − coste de IA) / precio. <b>No incluye</b> infraestructura, soporte ni licencias de datos.</li>
<li><b>Sensibilidad:</b> si el coste de IA se duplicara, el margen bruto bajaría a {sens}. Seguiría siendo <span class="ok">positivo en todos los planes</span>.</li>
<li>El coste de IA de un plan Pro completo (150 análisis) es {es(150 * COSTE_ANALISIS_EUR, 2)} €: el {es(100 * 150 * COSTE_ANALISIS_EUR / 49, 0)} % del precio.</li>
</ul>

<h2>3. Riesgos y límites</h2>
<table>
<tr><th>Límite</th><th>Efecto</th><th>Mitigación</th></tr>
<tr><td>Guardrail heurístico</td><td>Puede dejar pasar formulaciones muy indirectas</td><td>Conservador por diseño; revisión legal antes de producción</td></tr>
<tr><td>La verificación comprueba presencia, no interpretación</td><td>Un número correcto puede interpretarse mal</td><td>Cita de página; lectura humana de la nota</td></tr>
<tr><td>Sin OCR</td><td>Un PDF escaneado no se puede analizar</td><td>Error claro al usuario; OCR en la hoja de ruta</td></tr>
<tr><td>Precisión no evaluada de forma sistemática</td><td>No hay métrica global de acierto</td><td>Conjunto de preguntas con respuesta conocida (siguiente paso)</td></tr>
<tr><td>Dependencia de APIs de terceros</td><td>Caída o cambio de precio de un proveedor</td><td>Proveedores intercambiables por capacidad; degradación elegante y modo demo</td></tr>
<tr><td>Audios de la demo sintéticos</td><td>Los de earnings calls reales tienen derechos de autor</td><td>Lectura de extractos del propio informe</td></tr>
</table>

<h2>4. Estado del MVP y siguientes pasos</h2>
<ul>
<li><b>Estado:</b> aplicación operativa y desplegada en AWS; más de 800 tests; CI en GitHub Actions (Python 3.11 y 3.12); modo demo sin claves; entradas inválidas con error controlado.</li>
<li><b>Siguientes pasos:</b> evaluación sistemática de precisión, OCR, <i>streaming</i>, proveedor de datos con licencia, multiusuario con autenticación, comparación entre empresas y alertas por ticker.</li>
</ul>
<p class="nota">Fuentes de las cifras: <code>docs/medidas.md</code> (medición con APIs reales), <code>README.md</code> y <code>docs/DESPLIEGUE.md</code>. Tarifas orientativas: verificar en las páginas oficiales de cada proveedor.</p>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--navegador", default="msedge", help="canal de Playwright: msedge o chrome")
    ap.add_argument("--password", default=PASSWORD_DEMO,
                    help="contraseña de la demo que aparece en el PDF (o variable FINLENS_DEMO_PASSWORD); vacía = «solicítala al equipo»")
    args = ap.parse_args()
    medidas = leer_medidas(MEDIDAS)
    with sync_playwright() as pw:
        navegador = pw.chromium.launch(channel=args.navegador, headless=True)
        page = navegador.new_page()
        page.set_content(construir(medidas, args.password))
        page.wait_for_timeout(300)
        pie = ('<div style="font-size:8px;color:#7a8296;width:100%;padding:0 15mm;display:flex;justify-content:space-between;">'
               '<span>FinLens · Propuesta de MVP · Taller B5-T4 · Máster MIAX</span>'
               '<span>Página <span class="pageNumber"></span> de <span class="totalPages"></span></span></div>')
        page.pdf(path=str(DESTINO), format="A4", print_background=True, display_header_footer=True,
                 header_template="<span></span>", footer_template=pie,
                 margin={"top": "16mm", "bottom": "18mm", "left": "15mm", "right": "15mm"})
        navegador.close()
    print(f"Generado {DESTINO.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
