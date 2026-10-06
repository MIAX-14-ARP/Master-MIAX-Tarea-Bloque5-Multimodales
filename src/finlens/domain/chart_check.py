"""Contraste determinista «lo que ve el modelo de visión» ↔ «lo que dicen los datos» (detector de
alucinaciones visuales).

El modelo de visión devuelve un `ChartReading` (tendencia, descripción, observaciones en texto libre).
Aquí, sin IA, se comprueba cada afirmación verificable contra el `TechnicalSummary` calculado en Python:

- tendencia: coincide o no con la tendencia determinista;
- niveles de precio citados: deben caer dentro del rango del periodo (mín × 0,97 … máx × 1,03);
- soportes/resistencias citados (frases con «soporte»/«resistencia»): deben estar a ±3 % de algún pivote.

Lo que no se puede comprobar (tendencia «indeterminada», sin pivotes...) se marca `no_verificable` y no
cuenta en la puntuación.
"""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from typing import Literal

from finlens.domain.schemas import ChartReading
from finlens.domain.technicals import TechnicalSummary

Verdict = Literal["confirmada", "discrepa", "no_verificable"]

# --- TOLERANCIAS -----------------------------------------------------------------------------
MARGEN_RANGO_INF = 0.97  # un nivel vale si está en [mín × 0,97, máx × 1,03]
MARGEN_RANGO_SUP = 1.03
TOLERANCIA_PIVOTE = 0.03  # ±3 % respecto a un soporte/resistencia calculado
PUNTUACION_NEUTRA = 0.5  # sin afirmaciones verificables no hay evidencia ni a favor ni en contra
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ChartCheckItem:
    claim: str
    verdict: Verdict
    detail: str


@dataclass(frozen=True)
class ChartCheck:
    """`agreement_score` = confirmadas / (confirmadas + discrepan), en 0..1 (0,5 si nada es verificable)."""

    agreement_score: float
    items: tuple[ChartCheckItem, ...]

    @property
    def n_verifiable(self) -> int:
        return sum(1 for i in self.items if i.verdict != "no_verificable")


# Número con separadores de miles/decimales (punto o coma) y sufijo opcional «k» (63k = 63 000).
_NUMERO = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(\s?[kK]\b)?(\s?%)?")
_ANTES_NO_PRECIO = re.compile(r"(?:SMA|EMA|RSI|MA|MM|MACD|media(?:s)?(?:\s+móvil(?:es)?)?|per[ií]odo)\s*$", re.IGNORECASE)
_DESPUES_NO_PRECIO = re.compile(
    r"\s*(?:de\s+)?(?:d[ií]as?|velas?|sesiones?|semanas?|meses|mes|horas?|a[ñn]os?|veces|x\b|"
    r"ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)",
    re.IGNORECASE,
)
_SOPORTE_RESISTENCIA = re.compile(r"soporte|resistencia|support|resistance", re.IGNORECASE)


def _lecturas(token: str, kilo: bool) -> list[float]:
    """Valores posibles de un número escrito en formato español o inglés (ambiguos → varias lecturas)."""
    factor = 1000.0 if kilo else 1.0
    tiene_punto, tiene_coma = "." in token, "," in token
    if tiene_punto and tiene_coma:
        decimal = "." if token.rfind(".") > token.rfind(",") else ","
        miles = "," if decimal == "." else "."
        return [float(token.replace(miles, "").replace(decimal, ".")) * factor]
    separador = "." if tiene_punto else "," if tiene_coma else ""
    if not separador:
        return [float(token) * factor]
    partes = token.split(separador)
    if len(partes) > 2:  # varios separadores iguales → miles
        return [float("".join(partes)) * factor]
    if len(partes[1]) == 3 and 1 <= len(partes[0]) <= 3:  # «63.058» / «1,234»: miles o decimal
        return [float("".join(partes)) * factor, float(f"{partes[0]}.{partes[1]}") * factor]
    return [float(f"{partes[0]}.{partes[1]}") * factor]


def _niveles_citados(texto: str) -> list[tuple[str, list[float]]]:
    """(texto del número, lecturas posibles) de cada candidato a precio del texto."""
    salida: list[tuple[str, list[float]]] = []
    for m in _NUMERO.finditer(texto):
        if m.group(3):  # porcentaje
            continue
        if _ANTES_NO_PRECIO.search(texto[: m.start()]) or _DESPUES_NO_PRECIO.match(texto, m.end()):
            continue
        try:
            salida.append((m.group(0).strip(), _lecturas(m.group(1), bool(m.group(2)))))
        except ValueError:
            continue
    return salida


def _en_rango(valor: float, tech: TechnicalSummary) -> bool:
    return tech.range_low * MARGEN_RANGO_INF <= valor <= tech.range_high * MARGEN_RANGO_SUP


def _cerca_de_pivote(valor: float, pivotes: tuple[float, ...]) -> float | None:
    for p in pivotes:
        if p and abs(valor - p) / p <= TOLERANCIA_PIVOTE:
            return p
    return None


def _fmt(valor: float) -> str:
    return f"{valor:,.2f}"


def _item_trend(reading: ChartReading, tech: TechnicalSummary) -> ChartCheckItem:
    claim = f"Tendencia: {reading.trend}"
    if reading.trend == "indeterminada":
        return ChartCheckItem(claim, "no_verificable", "El modelo no se pronunció sobre la tendencia.")
    if reading.trend == tech.trend:
        return ChartCheckItem(claim, "confirmada", f"Los datos también dan tendencia {tech.trend}.")
    return ChartCheckItem(claim, "discrepa", f"Los datos dan tendencia {tech.trend}.")


def _items_texto(texto: str, tech: TechnicalSummary) -> list[ChartCheckItem]:
    items: list[ChartCheckItem] = []
    es_nivel_sr = bool(_SOPORTE_RESISTENCIA.search(texto))
    pivotes = tech.supports + tech.resistances
    resumen = textwrap.shorten(texto.strip(), width=90, placeholder="…")
    for token, lecturas in _niveles_citados(texto):
        claim = f"{'Soporte/resistencia' if es_nivel_sr else 'Nivel de precio'} «{token}» — {resumen}"
        if es_nivel_sr:
            if not pivotes:
                items.append(ChartCheckItem(claim, "no_verificable", "No se detectaron pivotes en el periodo."))
                continue
            cercanos = [(v, p) for v in lecturas if (p := _cerca_de_pivote(v, pivotes)) is not None]
            if cercanos:
                v, p = cercanos[0]
                items.append(ChartCheckItem(claim, "confirmada", f"Hay un pivote en {_fmt(p)} (±3 %)."))
            else:
                items.append(
                    ChartCheckItem(claim, "discrepa", f"Ningún pivote a ±3 %; los más cercanos: {', '.join(_fmt(p) for p in pivotes)}.")
                )
        else:
            dentro = [v for v in lecturas if _en_rango(v, tech)]
            if dentro:
                items.append(ChartCheckItem(claim, "confirmada", f"{_fmt(dentro[0])} está dentro del rango del periodo."))
            else:
                items.append(
                    ChartCheckItem(
                        claim,
                        "discrepa",
                        f"Fuera del rango del periodo ({_fmt(tech.range_low)} – {_fmt(tech.range_high)}).",
                    )
                )
    return items


def check_chart_reading(reading: ChartReading, tech: TechnicalSummary) -> ChartCheck:
    """Contrasta la lectura del modelo de visión con los indicadores calculados en Python."""
    items = [_item_trend(reading, tech)]
    for texto in (reading.description, *reading.observations):
        items.extend(_items_texto(texto, tech))
    confirmadas = sum(1 for i in items if i.verdict == "confirmada")
    verificables = sum(1 for i in items if i.verdict != "no_verificable")
    puntuacion = confirmadas / verificables if verificables else PUNTUACION_NEUTRA
    return ChartCheck(agreement_score=puntuacion, items=tuple(items))
