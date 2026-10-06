"""Vistas de Streamlit de FinLens: presentan datos del contrato, sin lógica de negocio."""
from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any

import streamlit as st

from finlens.domain.cost import CURRENCY
from finlens.domain.guardrails import DISCLAIMER
from finlens.domain.schemas import Citation
from finlens.orchestration.pipeline import AnalysisResult, MediaResult
from finlens.orchestration.trace import TraceStep, total_cost
from finlens.ui import components as ui
from finlens.ui.gantt import gantt_chart

_TENDENCIA = {"alcista": ("▲ alcista", "up"), "bajista": ("▼ bajista", "down"),
              "lateral": ("◆ lateral", ""), "indeterminada": ("— indeterminada", "")}


def html(fragmento: str) -> None:
    st.markdown(fragmento, unsafe_allow_html=True)


def show_disclaimer() -> None:
    """Aviso legal y de contenido generado por IA (AI Act): colofón discreto en cada salida."""
    html(ui.colophon(DISCLAIMER))


def citations_text(citations: Sequence[Citation]) -> str:
    """Citas en texto plano (para el historial del chat)."""
    return " · ".join(c.label for c in citations)


def show_warnings(warnings: Sequence[str]) -> None:
    for aviso in warnings:
        html(ui.editor_note(aviso))


def show_report(result: AnalysisResult) -> None:
    """La nota de research: resumen, cifras selladas, gráfico, dirección, correlaciones, límites."""
    informe = result.report
    # Capitular solo si el resumen empieza por letra (no «(Simulado)…» ni comillas).
    lede = "fl-lede has-drop" if informe.summary[:1].isalpha() else "fl-lede"
    html(
        '<div class="fl-note"><div class="fl-kicker">Nota de análisis · pregunta</div>'
        f'<p class="fl-q">«{ui.esc(result.question)}»</p>'
        f'{ui.subhead("§1", "Resumen")}<p class="{lede}">{ui.esc(informe.summary)}</p></div>'
    )
    if result.guard.blocked:
        html(ui.editor_note(
            "Se retiró contenido que parecía una recomendación de inversión (guardrail de compliance).",
            titulo="Compliance",
        ))
    if informe.key_figures:
        checks = getattr(result, "figure_checks", ()) or ()
        verificadas = sum(1 for c in checks if getattr(c, "status", "") == "verificada")
        titulo = "Cifras clave" + (f" · {verificadas}/{len(checks)} verificadas en el PDF" if checks else "")
        html(ui.subhead("§2", titulo) + ui.figures_html(informe.key_figures, checks))
        if not checks:
            html('<p class="fl-note-sm">Verificación determinista de cifras no disponible en esta versión.</p>')
    if informe.chart_reading:
        contraste = market_chart_check(result)
        extra = ""
        if contraste is not None:
            items = tuple(getattr(contraste, "items", ()) or ())
            sellos = "".join(ui.verdict_stamp(getattr(i, "verdict", "")) for i in items)
            extra = (f'<div class="fl-contrast-mini">Contraste con los datos de mercado: {sellos}'
                     " <span>· detalle en la pestaña Mercado</span></div>")
        html(ui.subhead("§3", "Lectura del gráfico") + ui.findings_html([informe.chart_reading]) + extra)
    if informe.management_statements:
        html(ui.subhead("§4", "Declaraciones de la dirección") + ui.findings_html(informe.management_statements))
    if informe.correlations:
        html(ui.subhead("§5", "Correlación entre modalidades") + ui.correlations_html(informe.correlations))
    if informe.limitations:
        html(ui.subhead("§6", "Limitaciones") + ui.limitations_html(informe.limitations))
    show_disclaimer()


def show_inputs_read(result: AnalysisResult) -> None:
    """Lo que el sistema entendió de cada modalidad, en tres columnas como las ranuras."""
    html(f'<div class="fl-kicker">Pregunta analizada</div><p class="fl-q">«{ui.esc(result.question)}»</p>')
    doc, graf, aud = st.columns(3, gap="large")
    with doc:
        d = result.document
        texto = f"{len(d.chunks)} fragmentos indexados con TF-IDF" + (
            " · truncado por el límite de entrada" if d.truncated else "")
        html(ui.read_card("A · Documento", f"{d.n_pages} págs.", texto))
    with graf:
        if result.chart:
            etiqueta, tono = _TENDENCIA.get(result.chart.trend, (result.chart.trend, ""))
            obs = "".join(f"<li>{ui.esc(o)}</li>" for o in result.chart.observations)
            html(ui.read_card("B · Gráfico", etiqueta, result.chart.description, tono=tono,
                              extra=f"<ul>{obs}</ul>" if obs else ""))
        else:
            html(ui.read_card("B · Gráfico", "", extra='<p class="fl-empty">No aportado o no se pudo leer.</p>'))
    with aud:
        if result.transcript:
            html(ui.read_card("C · Audio", "", extra=f'<blockquote class="fl-quote">{ui.esc(result.transcript)}</blockquote>'))
        else:
            html(ui.read_card("C · Audio", "", extra='<p class="fl-empty">No aportado o no se pudo transcribir.</p>'))


def show_media(media: MediaResult | None, spoken_summary: str = "") -> None:
    """Audio TTS e infografía; si un paso falló se avisa y el resto se muestra igualmente."""
    if media is None:
        html(ui.editor_note("Generando audio e infografía…", titulo="En curso"))
        return
    show_warnings(media.warnings)
    izq, der = st.columns([2, 3], gap="large")
    with izq:
        html(ui.subhead("§7", "Resumen en audio"))
        if media.audio:
            st.audio(media.audio.audio, format=media.audio.mime)
            html(f'<div class="fl-media-k">modelo · {ui.esc(media.audio.model)} · {media.audio.chars} caracteres</div>')
            if spoken_summary:
                html(f'<p class="fl-script">{ui.esc(spoken_summary)}</p>')
        else:
            st.caption("No solicitado." if media.audio_skipped else "No disponible.")
    with der:
        html(ui.subhead("§8", "Infografía"))
        if media.image:
            st.image(media.image.image, width="stretch")
            html(f'<div class="fl-media-k">modelo · {ui.esc(media.image.model)}</div>')
            ilustracion = getattr(media, "illustration", None)
            if ilustracion is not None:
                with st.expander("Ilustración original del modelo (sin cifras)"):
                    st.image(ilustracion.image, width="stretch")
                    html(f'<div class="fl-media-k">modelo · {ui.esc(ilustracion.model)}</div>')
            if media.image_prompt:
                with st.expander("Prompt enviado al modelo de imagen"):
                    html(f'<p class="fl-media-k">{ui.esc(media.image_prompt)}</p>')
        else:
            st.caption("No solicitada." if media.image_skipped else "No disponible.")
    show_disclaimer()


def trace_rows(steps: Sequence[TraceStep]) -> list[dict[str, str]]:
    """Filas de la tabla de traza (paso, modelo, segundos, coste, estado, nota)."""
    return [
        {
            "Paso": s.step + (" ⇉" if s.parallel else ""),
            "Modelo": s.model,
            "Segundos": f"{s.seconds:.2f}",
            "Tokens ent./sal.": f"{s.tokens_in:,} / {s.tokens_out:,}" if s.tokens_in or s.tokens_out else "—",
            f"Coste ({CURRENCY})": f"{s.cost_usd:.5f}",
            "Estado": "ok" if s.ok else "FALLO",
            "Nota": s.note,
        }
        for s in steps
    ]


def show_trace(steps: Sequence[TraceStep], total_seconds: float) -> None:
    """Traza de modelos: KPIs, Gantt con el paralelismo real y libro mayor por paso."""
    modelos = {s.model for s in steps if s.model and s.model != "—"}
    html(ui.kpis([
        ("Pasos", str(len(steps)), ""),
        ("Tiempo total", f"{total_seconds:.2f}", "s"),
        ("Coste estimado", f"{total_cost(steps):.4f}", CURRENCY),
        ("Modelos / motores", str(len(modelos)), ""),
    ]))
    if steps:
        st.altair_chart(gantt_chart(steps), width="stretch", theme=None)
        html('<p class="fl-note-sm">‖ = rama en paralelo. Inicio reconstruido a partir de las duraciones de '
             "la traza; el coste usa la cifra informada por el proveedor o tarifas orientativas configurables.</p>")
    st.table(trace_rows(steps))


# --- Mercado (spec 06 §10). Tolerante: los nombres internos de MarketContext se comprueban con getattr.

# Campos de `domain.technicals.TechnicalSummary` (spec 06 §10.2): (campo, etiqueta, formato).
_TECNICOS = (
    ("last_close", "Último cierre", "num"), ("period_return", "Rentabilidad periodo", "pct"),
    ("trend", "Tendencia", "txt"), ("sma20", "SMA 20", "num"), ("sma50", "SMA 50", "num"), ("ema20", "EMA 20", "num"),
    ("rsi14", "RSI 14", "num"), ("volatility_annual", "Volatilidad anual.", "pct"),
    ("max_drawdown", "Máx. drawdown", "pct"), ("range_low", "Mínimo periodo", "num"),
    ("range_high", "Máximo periodo", "num"), ("supports", "Soportes", "num"), ("resistances", "Resistencias", "num"),
)
_DERIVADOS = (
    ("funding_annualized", "Funding anualizado", "pct"), ("funding_hourly", "Funding horario", "pct4"),
    ("open_interest", "Open interest", "num"), ("mark_px", "Mark", "num"), ("oracle_px", "Oráculo", "num"),
    ("day_notional_volume", "Volumen 24 h (USD)", "num"), ("prev_day_px", "Cierre previo", "num"),
)


def _pick(obj: Any, *nombres: str) -> Any:
    for nombre in nombres:
        valor = getattr(obj, nombre, None)
        if valor is not None:
            return valor
    return None


def _fmt(valor: Any, modo: str = "num") -> str:
    if isinstance(valor, bool) or valor is None:
        return "—" if valor is None else ("sí" if valor else "no")
    if isinstance(valor, int | float):
        if modo == "pct":
            return f"{valor:.2%}"
        if modo == "pct4":
            return f"{valor:.4%}"
        return f"{valor:,.2f}" if abs(valor) < 1e6 else f"{valor:,.0f}"
    if isinstance(valor, list | tuple):
        return " · ".join(_fmt(v, modo) for v in valor[:3]) or "—"
    return str(valor)


def _campos(obj: Any) -> list[tuple[str, Any]]:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return [(f.name, getattr(obj, f.name)) for f in dataclasses.fields(obj)]
    return [(k, v) for k, v in vars(obj).items() if not k.startswith("_")] if hasattr(obj, "__dict__") else []


def market_chart_check(result: AnalysisResult) -> Any:
    mercado = getattr(result, "market", None)
    return getattr(mercado, "chart_check", None) if mercado is not None else None


def show_market(market: Any) -> None:
    """Pestaña Mercado: gráfico generado, contraste visión ↔ datos, técnicos, derivados y SEC."""
    serie = _pick(market, "series", "price_series", "prices")
    if serie is not None:
        velas = getattr(serie, "candles", ()) or ()
        html(f'<div class="fl-kicker">{ui.esc(getattr(serie, "symbol", ""))} · {ui.esc(getattr(serie, "source", ""))}'
             f' · {ui.esc(getattr(serie, "currency", ""))} · {len(velas)} velas</div>')
    izq, der = st.columns([5, 4], gap="large")
    with izq:
        html(ui.subhead("§M1", "Gráfico generado con datos reales"))
        png = _pick(market, "chart_png", "chart")
        if isinstance(png, bytes | bytearray):
            st.image(bytes(png), width="stretch")
            html('<p class="fl-note-sm">Dibujado en Python sin anotar indicadores: el modelo de visión no puede copiar '
                 "las cifras y su lectura se contrasta después con los datos.</p>")
        else:
            html('<p class="fl-empty">Se analizó el gráfico subido por el usuario.</p>')
    with der:
        html(ui.subhead("§M2", "La IA vio · los datos dicen"))
        check = getattr(market, "chart_check", None)
        if check is not None:
            html(ui.contrast_html(check))
        else:
            html('<p class="fl-empty">Sin contraste: no hubo lectura del gráfico.</p>')
    tecnicos = _pick(market, "technicals", "technical_summary", "tech")
    if tecnicos is not None:
        pares = [(etq, _fmt(getattr(tecnicos, k), modo)) for k, etq, modo in _TECNICOS if hasattr(tecnicos, k)]
        if not pares:  # versión distinta del contrato: se muestran sus campos tal cual
            pares = [(k.replace("_", " "), _fmt(v)) for k, v in _campos(tecnicos)]
        html(ui.subhead("§M3", "Indicadores técnicos (calculados en Python)") + ui.kv_grid(pares))
    derivados = _pick(market, "derivatives")
    if derivados is not None:
        pares = [(etq, _fmt(getattr(derivados, k, None), modo)) for k, etq, modo in _DERIVADOS]
        html(ui.subhead("§M4", "Derivados cripto · Hyperliquid") + ui.kv_grid(pares))
    fundamentales = _pick(market, "fundamentals")
    hechos: tuple[Any, ...] = tuple(getattr(fundamentales, "facts", None) or ())
    if hechos:
        html(ui.subhead("§M5", f"Fundamentales oficiales SEC · {getattr(fundamentales, 'company', '')}"))
        st.table([
            {"Concepto": getattr(f, "label_es", "") or getattr(f, "tag", ""), "Ejercicio": str(getattr(f, "fy", "")),
             "Valor": _fmt(getattr(f, "value", None)), "Unidad": getattr(f, "unit", ""),
             "Cierre": str(getattr(f, "end", "")), "Formulario": getattr(f, "form", "")}
            for f in hechos
        ])
    show_disclaimer()
