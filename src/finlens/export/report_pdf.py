"""Nota de análisis en PDF (A4) con toda la salida de un análisis. Sin red y sin estado global mutable.

Los textos que genera el LLM son arbitrarios: antes de pintarlos se limpian (caracteres de control,
glifos que la fuente no tiene) para que nunca rompan el documento.
"""
from __future__ import annotations

import io
import re
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib
from fontTools.ttLib import TTFont
from fpdf import FPDF
from fpdf.enums import Align, TableCellFillMode
from fpdf.fonts import FontFace
from PIL import Image

from finlens.domain.guardrails import DISCLAIMER
from finlens.domain.schemas import Citation, Finding
from finlens.orchestration.pipeline import AnalysisResult, MediaResult
from finlens.orchestration.trace import TraceStep, total_cost

# --- MAQUETACIÓN -----------------------------------------------------------------------------
MARGEN_MM = 18
ANCHO_UTIL_MM = 210 - 2 * MARGEN_MM
MAX_TRANSCRIPCION = 1500
MAX_ALTO_IMAGEN_MM = 150
ESPACIO_MIN_TITULO_MM = 35  # si queda menos hueco, el título de sección salta de página
ESPACIO_MIN_TABLA_MM = 45
MAX_CELDA = 320  # una celda de tabla no puede ocupar más de una página
TAM_CUERPO = 9.5
TAM_TABLA = 8.5
AZUL = (31, 58, 95)
GRIS = (90, 90, 90)
GRIS_CLARO = (238, 240, 243)
VERDE = (30, 123, 79)
ROJO = (179, 38, 30)
AMBAR = (150, 100, 0)
# ---------------------------------------------------------------------------------------------

Color = tuple[int, int, int]
Fila = Sequence[str]

_SUSTITUCIONES = {
    "\u2713": "OK", "\u2714": "OK", "\u2705": "OK", "\u2717": "X", "\u2718": "X", "\u274c": "X",
    "\u26a0": "(!)", "\u00a0": " ", "\u200b": "", "\u2028": "\n", "\u2029": "\n",
    "\u201c": "\u00ab", "\u201d": "\u00bb", "\t": "    ",
}
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_SALTOS = re.compile(r"\n{3,}")
_TRAMO_LARGO = re.compile(r"(\S{40})(?=\S)")  # trozos sin espacios muy largos: se parten para que ajusten


def _dir_fuentes() -> Path:
    return Path(matplotlib.get_data_path()) / "fonts" / "ttf"


def _num(valor: float, decimales: int = 2) -> str:
    """Número con formato español (1.234,56)."""
    return f"{valor:,.{decimales}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _pct(fraccion: float | None, decimales: int = 1) -> str:
    return "n/d" if fraccion is None else f"{_num(fraccion * 100, decimales)} %"


def _citas(citas: Iterable[Citation]) -> str:
    return "; ".join(c.label for c in citas)


class _Pdf(FPDF):
    """FPDF con cabecera y pie de la nota, y utilidades de texto seguras."""

    def __init__(self, fecha: datetime) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.fecha = fecha
        self.set_margins(MARGEN_MM, MARGEN_MM + 4, MARGEN_MM)
        self.set_auto_page_break(auto=True, margin=26)
        self.set_title("FinLens · Nota de análisis")
        self.set_author("FinLens")
        self.set_creator("FinLens")
        self.set_creation_date(fecha)
        d = _dir_fuentes()
        self.add_font("sans", "", str(d / "DejaVuSans.ttf"))
        self.add_font("sans", "B", str(d / "DejaVuSans-Bold.ttf"))
        self.add_font("sans", "I", str(d / "DejaVuSans-Oblique.ttf"))
        self.add_font("serif", "", str(d / "DejaVuSerif.ttf"))
        self.add_font("serif", "B", str(d / "DejaVuSerif-Bold.ttf"))
        self._glifos = set(TTFont(str(d / "DejaVuSans.ttf")).getBestCmap())
        self.alias_nb_pages("{nb}")

    # --- texto seguro ---
    def limpio(self, texto: object) -> str:
        t = _CONTROL.sub("", str(texto if texto is not None else ""))
        for k, v in _SUSTITUCIONES.items():
            t = t.replace(k, v)
        t = "".join(c if (c == "\n" or ord(c) in self._glifos) else "" for c in t)
        return _TRAMO_LARGO.sub(r"\1 ", _SALTOS.sub("\n\n", t))

    # --- cabecera / pie ---
    def header(self) -> None:
        self.set_y(9)
        self.set_font("sans", "B", 8)
        self.set_text_color(*AZUL)
        self.cell(ANCHO_UTIL_MM / 2, 5, "FinLens · Nota de análisis")
        self.set_font("sans", "", 8)
        self.set_text_color(*GRIS)
        self.cell(ANCHO_UTIL_MM / 2, 5, self.fecha.strftime("%d/%m/%Y %H:%M"), align="R")
        self.set_draw_color(*AZUL)
        self.set_line_width(0.3)
        self.line(MARGEN_MM, 15, 210 - MARGEN_MM, 15)
        self.set_y(MARGEN_MM + 4)

    def footer(self) -> None:
        self.set_y(-22)
        self.set_draw_color(200, 200, 200)
        self.set_line_width(0.2)
        self.line(MARGEN_MM, self.get_y(), 210 - MARGEN_MM, self.get_y())
        self.ln(1)
        self.set_font("sans", "", 6.5)
        self.set_text_color(*GRIS)
        self.multi_cell(ANCHO_UTIL_MM, 3.2, self.limpio(DISCLAIMER), new_x="LMARGIN", new_y="NEXT")
        self.set_font("sans", "", 7.5)
        self.cell(ANCHO_UTIL_MM, 4, f"Página {self.page_no()} de {{nb}}", align="R")

    # --- bloques ---
    def seccion(self, titulo: str) -> None:
        if self.page_break_trigger - self.get_y() < ESPACIO_MIN_TITULO_MM:
            self.add_page()
        self.ln(3)
        self.set_font("serif", "B", 12.5)
        self.set_text_color(*AZUL)
        self.cell(0, 7, self.limpio(titulo), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*AZUL)
        self.set_line_width(0.4)
        self.line(MARGEN_MM, self.get_y(), 210 - MARGEN_MM, self.get_y())
        self.ln(2.5)
        self.set_text_color(0, 0, 0)

    def subtitulo(self, texto: str, color: Color = AZUL) -> None:
        self.set_font("sans", "B", 9.5)
        self.set_text_color(*color)
        self.multi_cell(0, 5, self.limpio(texto), new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)

    def parrafo(self, texto: str, *, tam: float = TAM_CUERPO, estilo: str = "", color: Color = (0, 0, 0),
                sangria: float = 0) -> None:
        self.set_font("sans", estilo, tam)
        self.set_text_color(*color)
        self.set_x(MARGEN_MM + sangria)
        self.multi_cell(ANCHO_UTIL_MM - sangria, tam * 0.52, self.limpio(texto), new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def vineta(self, texto: str, citas: str = "", color: Color = (0, 0, 0)) -> None:
        self.set_font("sans", "", TAM_CUERPO)
        self.set_text_color(*color)
        self.set_x(MARGEN_MM + 3)
        self.multi_cell(ANCHO_UTIL_MM - 3, 4.9, self.limpio(f"•  {texto}"), new_x="LMARGIN", new_y="NEXT")
        if citas:
            self.set_font("sans", "I", 7.5)
            self.set_text_color(*GRIS)
            self.set_x(MARGEN_MM + 7)
            self.multi_cell(ANCHO_UTIL_MM - 7, 3.8, self.limpio(f"Fuente: {citas}"), new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(1.2)

    def tabla(self, cabecera: Fila, filas: Sequence[Fila], anchos: Sequence[float],
              colorear: Callable[[int, int], Color | None] | None = None) -> None:
        """Tabla con cabecera azul y filas cebradas; `colorear(fila, col)` da el color de texto."""
        if len(filas) <= 14 and self.page_break_trigger - self.get_y() < ESPACIO_MIN_TABLA_MM:
            self.add_page()  # una tabla corta no debe quedar partida tras su primera fila
        self.set_font("sans", "", TAM_TABLA)
        escala = ANCHO_UTIL_MM / sum(anchos)
        with self.table(
            col_widths=tuple(a * escala for a in anchos),
            headings_style=FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=AZUL),
            cell_fill_color=GRIS_CLARO,
            cell_fill_mode=TableCellFillMode.ROWS,
            line_height=4.4,
            padding=1.2,
            text_align=Align.L,
            borders_layout="HORIZONTAL_LINES",
        ) as t:
            fila = t.row()
            for c in cabecera:
                fila.cell(self.limpio(c))
            for i, datos in enumerate(filas):
                fila = t.row()
                for j, c in enumerate(datos):
                    color = colorear(i, j) if colorear else None
                    if color:
                        fila.cell(self.limpio(_recortar(c, MAX_CELDA)), style=FontFace(emphasis="BOLD", color=color))
                    else:
                        fila.cell(self.limpio(_recortar(c, MAX_CELDA)))
        self.ln(2)

    def imagen(self, datos: bytes | None, titulo: str = "") -> bool:
        """Inserta una imagen; devuelve False (y no pinta nada) si los bytes no son una imagen válida."""
        png = _normalizar_imagen(datos)
        if png is None:
            return False
        contenido, w, h = png
        ancho = float(ANCHO_UTIL_MM)
        alto: float = ancho * h / w
        if alto > MAX_ALTO_IMAGEN_MM:
            ancho, alto = ancho * MAX_ALTO_IMAGEN_MM / alto, MAX_ALTO_IMAGEN_MM
        if self.page_break_trigger - self.get_y() < alto + 8:
            self.add_page()
        if titulo:
            self.set_font("sans", "I", 7.5)
            self.set_text_color(*GRIS)
            self.cell(0, 4, self.limpio(titulo), new_x="LMARGIN", new_y="NEXT")
            self.set_text_color(0, 0, 0)
        x = MARGEN_MM + (ANCHO_UTIL_MM - ancho) / 2
        self.image(io.BytesIO(contenido), x=x, y=self.get_y(), w=ancho, h=alto)
        self.set_y(self.get_y() + alto + 3)
        return True


def _normalizar_imagen(datos: bytes | None) -> tuple[bytes, int, int] | None:
    """PNG RGB re-codificado (cualquier formato legible) con su tamaño; None si no es una imagen."""
    if not datos:
        return None
    try:
        with Image.open(io.BytesIO(datos)) as im:
            im.load()
            rgb = im.convert("RGB")
            salida = io.BytesIO()
            rgb.save(salida, format="PNG")
            return salida.getvalue(), rgb.width, rgb.height
    except Exception:  # noqa: BLE001 - cualquier fallo de Pillow significa «imagen no utilizable»
        return None


def _recortar(texto: str, maximo: int) -> str:
    texto = texto.strip()
    return texto if len(texto) <= maximo else texto[:maximo].rstrip() + "…"


def _pasos(r: AnalysisResult, media: MediaResult | None) -> list[TraceStep]:
    return list(r.trace) + (list(media.trace) if media else [])


# --- SECCIONES -------------------------------------------------------------------------------
def _portada(pdf: _Pdf, r: AnalysisResult, media: MediaResult | None) -> None:
    pdf.set_font("serif", "B", 20)
    pdf.set_text_color(*AZUL)
    pdf.multi_cell(0, 9, "Nota de análisis", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("sans", "", 9)
    pdf.set_text_color(*GRIS)
    pdf.cell(0, 5, pdf.limpio(f"Generada el {pdf.fecha.strftime('%d/%m/%Y a las %H:%M')}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.subtitulo("Pregunta")
    pdf.parrafo(_recortar(r.question, 2000) or "(sin pregunta)", tam=10.5, estilo="I")

    materiales: list[str] = []
    if r.document.n_pages:
        materiales.append(f"Informe PDF: {r.document.n_pages} páginas")
    if r.chart is not None:
        materiales.append("Gráfico de velas aportado")
    if r.transcript is not None:
        materiales.append("Audio transcrito")
    m = r.market
    if m is not None:
        materiales.append(f"Ticker {m.series.symbol} ({m.kind or 'mercado'}) · fuente {m.series.source}")
    pasos = _pasos(r, media)
    vistos: dict[str, str] = {}
    for p in pasos:
        vistos.setdefault(p.step, p.model)
    segundos = r.total_seconds + (media.total_seconds if media else 0.0)
    pdf.tabla(("Dato", "Detalle"), [
        ("Materiales", "\n".join(materiales) or "—"),
        ("Modelos", "\n".join(f"{paso} → {modelo}" for paso, modelo in vistos.items()) or "—"),
        ("Coste total", f"{total_cost(pasos):.4f} USD (estimado)"),
        ("Tiempo", f"{_num(segundos, 1)} s"),
    ], (1.1, 5))


def _estado(fc: Any) -> tuple[str, Color, str]:
    """(texto del estado, color, texto de `matched`) de una verificación de cifra."""
    origen = getattr(fc, "source", None)
    donde = f" ({origen})" if origen else ""
    if fc.status == "verificada":
        pag = f" p.{fc.page}" if fc.page else ""
        return f"VERIFICADA{pag}{donde}", VERDE, fc.matched or ""
    if fc.status == "no_encontrada":
        return f"NO ENCONTRADA{donde}", ROJO, ""
    return "SIN FUENTE DOCUMENTAL", AMBAR, ""


def _cifras(pdf: _Pdf, r: AnalysisResult) -> None:
    cifras = r.report.key_figures
    if not cifras:
        return
    pdf.seccion("Cifras clave")
    por_clave = {(c.figure_name, c.value): c for c in r.figure_checks}
    por_nombre = {c.figure_name: c for c in r.figure_checks}
    filas: list[Fila] = []
    colores: list[Color] = []
    for k in cifras:
        fc = por_clave.get((k.name, k.value)) or por_nombre.get(k.name)
        if fc is None:
            estado, color, matched = "SIN VERIFICAR", GRIS, ""
        else:
            estado, color, matched = _estado(fc)
        if matched:
            estado += f"\n«{_recortar(matched, 60)}»"
        filas.append((k.name, k.value, k.period or "—", _citas(k.citations) or "—", estado))
        colores.append(color)
    pdf.tabla(("Cifra", "Valor", "Periodo", "Fuente(s)", "Verificación"), filas, (2.4, 1.7, 1.3, 2.2, 2.6),
              lambda i, j: colores[i] if j == 4 else None)


def _lectura_grafico(pdf: _Pdf, r: AnalysisResult) -> None:
    m = r.market
    lecturas = [("Lectura del gráfico aportado", r.chart),
                ("Lectura del gráfico generado con los datos", r.chart_generated)]
    cr = r.report.chart_reading
    if not any(lec for _, lec in lecturas) and cr is None and not (m and m.chart_png):
        return
    pdf.seccion("Lectura del gráfico")
    if cr is not None:
        pdf.vineta(cr.statement, _citas(cr.citations))
    for titulo, lec in lecturas:
        if lec is None:
            continue
        pdf.subtitulo(f"{titulo} — tendencia {lec.trend}")
        pdf.parrafo(lec.description)
        for o in lec.observations:
            pdf.vineta(o)
    if m is not None and m.chart_png:
        pdf.imagen(m.chart_png, titulo=f"Gráfico generado · {m.series.symbol} ({m.series.source})")
    if m is not None and m.chart_check is not None:
        cc = m.chart_check
        pdf.subtitulo(f"Contraste «La IA vio» ↔ «Los datos dicen» — acuerdo {_pct(cc.agreement_score, 0)} "
                      f"({cc.n_verifiable} afirmaciones verificables)")
        if cc.items:
            etiqueta = {"confirmada": "CONFIRMADA", "discrepa": "DISCREPA", "no_verificable": "NO VERIFICABLE"}
            color = {"confirmada": VERDE, "discrepa": ROJO, "no_verificable": GRIS}
            filas = [(i.claim, etiqueta.get(i.verdict, i.verdict), i.detail) for i in cc.items]
            pdf.tabla(("La IA vio", "Veredicto", "Los datos dicen"), filas, (3.6, 1.5, 3.2),
                      lambda i, j: color.get(cc.items[i].verdict) if j == 1 else None)


def _indicadores(pdf: _Pdf, r: AnalysisResult) -> None:
    m = r.market
    if m is None:
        return
    t = m.technicals
    cur = m.series.currency

    def niveles(xs: Iterable[float]) -> str:
        return ", ".join(_num(x) for x in xs) or "—"

    def opc(v: float | None) -> str:
        return "n/d" if v is None else _num(v)

    pdf.seccion(f"Datos de mercado · {t.symbol}")
    pdf.parrafo(f"Fuente: {t.source} · {t.n_candles} velas del {t.start:%d/%m/%Y} al {t.end:%d/%m/%Y}.",
                color=GRIS, tam=8.5)
    pdf.subtitulo("Indicadores técnicos")
    pdf.tabla(("Indicador", "Valor"), [
        ("Último cierre", f"{_num(t.last_close)} {cur}"),
        ("Variación del periodo", _pct(t.period_return)),
        ("Rango", f"{_num(t.range_low)} ({t.range_low_date:%d/%m/%Y}) – "
                  f"{_num(t.range_high)} ({t.range_high_date:%d/%m/%Y})"),
        ("SMA 20 / SMA 50 / EMA 20", f"{opc(t.sma20)} / {opc(t.sma50)} / {opc(t.ema20)}"),
        ("RSI 14", opc(t.rsi14)),
        ("Volatilidad anualizada", _pct(t.volatility_annual)),
        ("Máximo drawdown", _pct(t.max_drawdown)),
        ("Tendencia", f"{t.trend} (pendiente {_pct(t.trend_slope)})"),
        ("Soportes", niveles(t.supports)),
        ("Resistencias", niveles(t.resistances)),
    ], (2, 5))
    d = m.derivatives
    if d is not None:
        pdf.subtitulo("Derivados perpetuos (Hyperliquid)")
        pdf.tabla(("Métrica", "Valor"), [
            ("Funding horario / anualizado", f"{_pct(d.funding_hourly, 4)} / {_pct(d.funding_annualized, 1)}"),
            ("Open interest", f"{_num(d.open_interest)} uds · nocional ≈ {_num(d.open_interest * d.mark_px, 0)} USD"),
            ("Precio mark / oracle", f"{_num(d.mark_px)} / {_num(d.oracle_px)}"),
            ("Volumen nocional 24 h", f"{_num(d.day_notional_volume, 0)} USD"),
            ("Cierre del día previo", _num(d.prev_day_px)),
        ], (2, 5))
    f = m.fundamentals
    if f is not None:
        pdf.subtitulo(f"Fundamentales SEC EDGAR · {f.company} (CIK {f.cik})")
        pdf.tabla(("Concepto", "Valor", "Ejercicio", "Cierre", "Formulario"), [
            (x.label_es, f"{_num(x.value, 0 if abs(x.value) >= 1000 else 2)} {x.unit}", str(x.fy), x.end, x.form)
            for x in f.facts
        ], (3, 2.4, 1, 1.5, 1.1))


def _lista(pdf: _Pdf, titulo: str, items: Sequence[Finding], color: Color = (0, 0, 0)) -> None:
    if not items:
        return
    pdf.subtitulo(titulo, color if color != (0, 0, 0) else AZUL)
    for f in items:
        pdf.vineta(f.statement, _citas(f.citations), color)


def _hallazgos(pdf: _Pdf, r: AnalysisResult) -> None:
    rep = r.report
    contradicciones = list(getattr(rep, "contradictions", None) or [])
    if not (rep.management_statements or rep.correlations or contradicciones or rep.limitations):
        return
    pdf.seccion("Hallazgos")
    _lista(pdf, "Declaraciones de la dirección", rep.management_statements)
    _lista(pdf, "Correlaciones entre modalidades", rep.correlations)
    _lista(pdf, "Contradicciones detectadas", contradicciones, ROJO)
    if rep.limitations:
        pdf.subtitulo("Limitaciones")
        for lim in rep.limitations:
            pdf.vineta(lim)


def _anexo(pdf: _Pdf, r: AnalysisResult, media: MediaResult | None) -> None:
    pdf.seccion("Anexo · Traza de modelos")
    pasos = _pasos(r, media)
    pdf.tabla(("Paso", "Modelo", "s", "USD", "OK"), [
        (p.step, p.model, _num(p.seconds, 1), f"{p.cost_usd:.4f}", "sí" if p.ok else "NO") for p in pasos
    ], (3.6, 2.6, 0.8, 1, 0.7), lambda i, j: ROJO if j == 4 and not pasos[i].ok else None)
    pdf.parrafo(f"Total: {total_cost(pasos):.4f} USD (estimado) · "
                f"{_num(sum(p.seconds for p in pasos), 1)} s de cómputo.", tam=8.5, color=GRIS)
    avisos = list(r.warnings) + (list(media.warnings) if media else [])
    if avisos:
        pdf.subtitulo("Avisos del análisis")
        for a in avisos:
            pdf.vineta(a)
    pdf.subtitulo("Aviso legal")
    pdf.parrafo(DISCLAIMER)
    pdf.parrafo(
        "Las cifras señaladas como VERIFICADAS se han contrastado de forma determinista con el texto del documento "
        "o con los datos de mercado; NO ENCONTRADA indica que no se ha podido localizar. Este documento no "
        "sustituye el criterio de un profesional.", tam=8, color=GRIS)


# --- API -------------------------------------------------------------------------------------
def build_report_pdf(
    result: AnalysisResult,
    media: MediaResult | None = None,
    chat: Sequence[tuple[str, str]] = (),
    *,
    generated_at: datetime | None = None,
) -> bytes:
    """PDF A4 con toda la salida del análisis (`chat` = pares (rol, texto)). No accede a la red."""
    pdf = _Pdf(generated_at or datetime.now().astimezone())
    pdf.add_page()
    _portada(pdf, result, media)
    pdf.seccion("Resumen")
    pdf.parrafo(result.report.summary, tam=10)
    _cifras(pdf, result)
    _lectura_grafico(pdf, result)
    _indicadores(pdf, result)
    _hallazgos(pdf, result)
    if result.transcript:
        pdf.seccion("Transcripción del audio")
        pdf.parrafo(_recortar(result.transcript, MAX_TRANSCRIPCION), estilo="I", color=(50, 50, 50))
    if media is not None and (media.image is not None or media.audio is not None):
        pdf.seccion("Infografía y audio")
        if media.image is not None and not pdf.imagen(media.image.image, titulo=f"Infografía · {media.image.model}"):
            pdf.parrafo("(La infografía generada no se pudo incrustar.)", color=GRIS, tam=8.5)
        if media.audio is not None:
            pdf.parrafo(f"Se generó además un resumen en audio ({media.audio.model}); "
                        "no se puede incrustar en el PDF.", color=GRIS, tam=8.5)
    turnos = [(rol, texto) for rol, texto in chat if str(texto).strip()]
    if turnos:
        pdf.seccion("Chat de seguimiento")
        for rol, texto in turnos:
            usuario = str(rol).lower() in {"user", "usuario", "human"}
            pdf.subtitulo("Pregunta" if usuario else "Respuesta")
            pdf.parrafo(texto, sangria=3, estilo="I" if usuario else "")
    _anexo(pdf, result, media)
    return bytes(pdf.output())
