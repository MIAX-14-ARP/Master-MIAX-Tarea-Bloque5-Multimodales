"""Traza como diagrama de Gantt (Altair). La línea de tiempo se reconstruye de las duraciones.

`TraceStep` no guarda la hora de inicio: los pasos en serie se encadenan y los bloques de pasos
paralelos consecutivos arrancan a la vez, con un carril por rama (la rama de imagen agrupa prompt,
generación y composición, que van en serie dentro de ella).
"""
from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

import altair as alt
import pandas as pd

from finlens.orchestration.trace import TraceStep
from finlens.ui import theme

_RAMA_IMAGEN = ("infografia", "ilustracion", "imagen", "composicion")


@dataclass(frozen=True)
class Bar:
    step: str
    model: str
    start: float
    end: float
    ok: bool
    parallel: bool
    cost: float
    local: bool


def _rama(paso: TraceStep) -> str:
    nombre = unicodedata.normalize("NFKD", paso.step).encode("ascii", "ignore").decode().lower()
    return "imagen" if any(k in nombre for k in _RAMA_IMAGEN) else nombre


def _es_local(paso: TraceStep) -> bool:
    return paso.cost_usd == 0 and paso.tokens_in == 0 and paso.quantity == 0 and (
        "regla" in paso.model or "TF-IDF" in paso.model or "pypdf" in paso.model or paso.model == "—"
    )


def timeline(steps: Sequence[TraceStep]) -> list[Bar]:
    """Barras (inicio, fin) en segundos desde el comienzo."""
    barras: list[Bar] = []
    t = 0.0
    i = 0
    while i < len(steps):
        if not steps[i].parallel:
            p = steps[i]
            barras.append(Bar(p.step, p.model, t, t + p.seconds, p.ok, False, p.cost_usd, _es_local(p)))
            t += p.seconds
            i += 1
            continue
        bloque: list[TraceStep] = []
        while i < len(steps) and steps[i].parallel:
            bloque.append(steps[i])
            i += 1
        relojes: dict[str, float] = {}
        for p in bloque:
            inicio = relojes.get(_rama(p), t)
            barras.append(Bar(p.step, p.model, inicio, inicio + p.seconds, p.ok, True, p.cost_usd, _es_local(p)))
            relojes[_rama(p)] = inicio + p.seconds
        t = max(relojes.values(), default=t)
    return barras


def gantt_chart(steps: Sequence[TraceStep]) -> alt.LayerChart:
    barras = timeline(steps)
    df = pd.DataFrame(
        [
            {
                "paso": f"{b.step}{'  ‖' if b.parallel else ''}",
                "modelo": b.model,
                "inicio": round(b.start, 3),
                "fin": round(max(b.end, b.start + 0.004), 3),
                "segundos": round(b.end - b.start, 3),
                "coste": round(b.cost, 5),
                "tipo": "fallo" if not b.ok else ("local" if b.local else "modelo"),
                "etiqueta": f"{b.end - b.start:.2f} s" + (f" · ${b.cost:.4f}" if b.cost else ""),
            }
            for b in barras
        ]
    )
    orden = list(df["paso"]) if not df.empty else []
    y = alt.Y("paso:N", sort=orden, title=None, axis=alt.Axis(labelLimit=220))
    tooltip = [
        alt.Tooltip("paso:N", title="Paso"), alt.Tooltip("modelo:N", title="Modelo"),
        alt.Tooltip("segundos:Q", title="Segundos", format=".3f"),
        alt.Tooltip("coste:Q", title="Coste USD", format=".5f"),
    ]
    color = alt.Color(
        "tipo:N",
        scale=alt.Scale(domain=["modelo", "local", "fallo"],
                        range=[theme.CHART["modelo"], theme.CHART["local"], theme.CHART["fallo"]]),
        legend=alt.Legend(title=None, orient="top", direction="horizontal",
                          labelExpr="{'modelo':'modelo de IA','local':'paso local','fallo':'fallo'}[datum.label]"),
    )
    base = alt.Chart(df)
    barras_ch = base.mark_bar(height=12).encode(
        x=alt.X("inicio:Q", title="segundos desde el inicio"), x2="fin:Q", y=y, color=color, tooltip=tooltip
    )
    textos = base.mark_text(align="left", dx=6, font=theme.FONT_MONO, fontSize=10.5,
                            color=theme.CHART["texto"]).encode(x="fin:Q", y=y, text="etiqueta:N")
    alto = max(140, 30 * len(df) + 40)
    return (
        alt.layer(barras_ch, textos)
        .properties(height=alto)
        .configure(background="transparent", font=theme.FONT_MONO)
        .configure_view(strokeWidth=0)
        .configure_axis(labelColor=theme.CHART["texto"], titleColor=theme.MUTED, gridColor=theme.CHART["rejilla"],
                        domainColor=theme.RULE_STRONG, tickColor=theme.RULE_STRONG, labelFont=theme.FONT_MONO,
                        titleFont=theme.FONT_MONO, labelFontSize=11, titleFontSize=10, titleFontWeight=500)
        .configure_legend(labelColor=theme.CHART["texto"], labelFont=theme.FONT_MONO, labelFontSize=10.5,
                          symbolType="square")
    )
