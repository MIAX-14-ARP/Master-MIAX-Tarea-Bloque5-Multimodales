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
MIN_ENTERO_PRECIO = 10  # los enteros sin decimales menores que 10 («2 intentos») no se toman como precio
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
_INDICADOR = re.compile(r"\b(?:SMA|EMA|RSI|MA|MM|MACD|medias?|sesion(?:es)?|velas?|d[ií]as?)\b", re.IGNORECASE)
# Palabras que reabren un contexto de precio: tras ellas, un indicador anterior ya no afecta al número.
_PALABRA_PRECIO = re.compile(r"\b(?:soporte|resistencia|precio|cierre|cierra|m[aá]ximo|m[ií]nimo|nivel|support|resistance)\b", re.IGNORECASE)
_PERIODO_FINAL = re.compile(r"per[ií]odo\s*$", re.IGNORECASE)
_CORTE_CLAUSULA = re.compile(r"[,;:()]|\d")
VENTANA_INDICADOR = 6  # palabras previas que se miran para saber si el número es el valor de un indicador
_MESES = (
    r"(?:ene(?:ro)?|feb(?:rero)?|mar(?:zo)?|abr(?:il)?|may(?:o)?|jun(?:io)?|jul(?:io)?|ago(?:sto)?"
    r"|sep(?:t(?:iembre)?)?|oct(?:ubre)?|nov(?:iembre)?|dic(?:iembre)?)"
)
_DESPUES_NO_PRECIO = re.compile(
    rf"\s*(?:de\s+)?(?:d[ií]as?|velas?|sesiones?|semanas?|meses|mes|horas?|a[ñn]os?|veces|x\b|{_MESES}\b)",
    re.IGNORECASE,
)
# Un año (1900–2100) en contexto de fecha: tras mes, «de», «del», «año», «desde», «hasta»...
_ANTES_ANIO = re.compile(rf"(?:\b{_MESES}\.?|\bde|\bdel|\ba[ñn]o|\bdesde|\bhasta)\s*$", re.IGNORECASE)
_FECHA_ANTES = re.compile(r"\d[-/]$")
_FECHA_DESPUES = re.compile(r"^[-/]\d")
_VOLUMEN = re.compile(r"\bvol[uú]men(?:es)?\b|\bvolume\b", re.IGNORECASE)
_SOPORTE_RESISTENCIA = re.compile(r"soporte|resistencia|support|resistance", re.IGNORECASE)
_SEPARADOR_ZONA = re.compile(r"\s*(?:-|–|—|a|y|hasta|and|to)\s*", re.IGNORECASE)
_FRASES = re.compile(r"(?<=[.;!?])\s+|\n+")
_ABREV_MES = re.compile(rf"\b({_MESES})\.", re.IGNORECASE)  # «6 oct. 2026»: el punto no cierra la frase


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


def _tras_indicador(antes: str) -> bool:
    """¿Las palabras previas (misma cláusula, sin otro número ni palabra de precio) nombran un indicador?"""
    corte = max((c.end() for c in _CORTE_CLAUSULA.finditer(antes)), default=0)
    precio = max((c.end() for c in _PALABRA_PRECIO.finditer(antes)), default=0)
    palabras = antes[max(corte, precio) :].split()[-VENTANA_INDICADOR:]
    segmento = " ".join(palabras)
    return bool(_INDICADOR.search(segmento) or _PERIODO_FINAL.search(segmento))


def _no_es_precio(texto: str, m: re.Match[str], rango: tuple[float, float] | None = None) -> bool:
    """¿El número es un porcentaje, un periodo, parte de una fecha o el parámetro de un indicador?"""
    if m.group(3):  # porcentaje
        return True
    antes, despues = texto[: m.start()], texto[m.end() :]
    if _tras_indicador(antes) or _DESPUES_NO_PRECIO.match(texto, m.end()):
        return True
    if _FECHA_ANTES.search(antes[-2:]) or _FECHA_DESPUES.match(despues[:2]):
        return True  # 2026-04-06, 06/04/2026
    token = m.group(1)
    if token.isdigit() and not m.group(2):
        valor = int(token)
        if valor < MIN_ENTERO_PRECIO:  # «2 intentos», «3 veces»: recuentos, no precios
            return True
        if 1900 <= valor <= 2100:  # año: en contexto de fecha siempre; suelto, salvo que el rango lo contenga
            if _ANTES_ANIO.search(antes):
                return True
            return rango is not None and not (rango[0] <= valor <= rango[1])
    return False


def _candidatos(
    texto: str, rango: tuple[float, float] | None = None
) -> list[tuple[str, list[float], int, int]]:
    """(texto, lecturas posibles, inicio, fin) de cada candidato a precio del texto."""
    salida: list[tuple[str, list[float], int, int]] = []
    for m in _NUMERO.finditer(texto):
        if _no_es_precio(texto, m, rango):
            continue
        try:
            salida.append((m.group(0).strip(), _lecturas(m.group(1), bool(m.group(2))), m.start(), m.end()))
        except ValueError:
            continue
    return salida


def _niveles_citados(texto: str, rango: tuple[float, float] | None = None) -> list[tuple[str, list[float]]]:
    return [(t, lec) for t, lec, _ini, _fin in _candidatos(texto, rango)]


def _en_rango(valor: float, tech: TechnicalSummary) -> bool:
    return tech.range_low * MARGEN_RANGO_INF <= valor <= tech.range_high * MARGEN_RANGO_SUP


def _niveles_sr(tech: TechnicalSummary) -> tuple[float, ...]:
    """Todos los niveles con los que se verifica un soporte/resistencia citado: los pivotes del periodo
    (no solo los 3 más cercanos que muestra la UI) y los extremos del periodo."""
    return tuple(sorted({*tech.pivots, *tech.supports, *tech.resistances, tech.range_low, tech.range_high}))


def _mas_cercano(valores: list[float], niveles: tuple[float, ...]) -> tuple[float, float]:
    """(nivel más cercano, distancia relativa) de `niveles` respecto a cualquiera de `valores`."""
    return min(((n, abs(v - n) / n) for v in valores for n in niveles if n), key=lambda t: t[1])


def _fmt(valor: float) -> str:
    return f"{valor:,.2f}"


def _item_trend(reading: ChartReading, tech: TechnicalSummary) -> ChartCheckItem:
    claim = f"Tendencia: {reading.trend}"
    if reading.trend == "indeterminada":
        return ChartCheckItem(claim, "no_verificable", "El modelo no se pronunció sobre la tendencia.")
    if reading.trend == tech.trend:
        return ChartCheckItem(claim, "confirmada", f"Los datos también dan tendencia {tech.trend}.")
    return ChartCheckItem(claim, "discrepa", f"Los datos dan tendencia {tech.trend}.")


def _item_sr(
    claim: str, lecturas: list[float], zona: tuple[float, float] | None, tech: TechnicalSummary
) -> ChartCheckItem:
    niveles = _niveles_sr(tech)
    if zona is not None:  # «58.000 - 60.000»: vale cualquier nivel dentro de la zona ±3 %
        bajo, alto = zona[0] * (1 - TOLERANCIA_PIVOTE), zona[1] * (1 + TOLERANCIA_PIVOTE)
        dentro = [n for n in niveles if bajo <= n <= alto]
        if dentro:
            return ChartCheckItem(claim, "confirmada", f"Hay un nivel en {_fmt(dentro[0])} dentro de la zona (±3 %).")
        n, d = _mas_cercano([zona[0], zona[1]], niveles)
        return ChartCheckItem(claim, "discrepa", f"Ningún pivote en la zona; el más cercano es {_fmt(n)} ({d:.1%} de distancia).")
    n, d = _mas_cercano(lecturas, niveles)
    if d <= TOLERANCIA_PIVOTE:
        return ChartCheckItem(claim, "confirmada", f"Hay un pivote en {_fmt(n)} (±3 %).")
    return ChartCheckItem(claim, "discrepa", f"Ningún pivote a ±3 %; el más cercano es {_fmt(n)} ({d:.1%} de distancia).")


def _item_precio(claim: str, lecturas: list[float], tech: TechnicalSummary) -> ChartCheckItem:
    dentro = [v for v in lecturas if _en_rango(v, tech)]
    if dentro:
        return ChartCheckItem(claim, "confirmada", f"{_fmt(dentro[0])} está dentro del rango del periodo.")
    return ChartCheckItem(
        claim, "discrepa", f"Fuera del rango del periodo ({_fmt(tech.range_low)} – {_fmt(tech.range_high)})."
    )


def _items_frase(frase: str, tech: TechnicalSummary, volumen: bool, tema_volumen: bool) -> list[ChartCheckItem]:
    items: list[ChartCheckItem] = []
    es_sr = bool(_SOPORTE_RESISTENCIA.search(frase))
    resumen = textwrap.shorten(frase.strip(), width=90, placeholder="…")
    cand = _candidatos(frase, (tech.range_low * MARGEN_RANGO_INF, tech.range_high * MARGEN_RANGO_SUP))
    i = 0
    while i < len(cand):
        token, lecturas, _ini, fin = cand[i]
        # «120K» o frases que arrancan hablando de volumen: es volumen, no precio.
        if tema_volumen or (volumen and token[-1] in "kK"):
            i += 1
            continue
        zona = None
        if es_sr and i + 1 < len(cand):
            token2, lec2, ini2, _fin2 = cand[i + 1]
            if _SEPARADOR_ZONA.fullmatch(frase[fin:ini2]):
                zona = (min(lecturas), max(lec2))
                token = f"{token} – {token2}"
                lecturas = lecturas + lec2
                i += 1
        claim = f"{'Soporte/resistencia' if es_sr else 'Nivel de precio'} «{token}» — {resumen}"
        items.append(_item_sr(claim, lecturas, zona, tech) if es_sr else _item_precio(claim, lecturas, tech))
        i += 1
    return items


def _items_texto(texto: str, tech: TechnicalSummary) -> list[ChartCheckItem]:
    # El volumen se decide sobre la observación entera: «Volumen: ... (120K) ... (100K)» abarca varias frases.
    volumen = bool(_VOLUMEN.search(texto))
    tema_volumen = volumen and bool(_VOLUMEN.match(texto.strip()))
    return [
        it
        for frase in _FRASES.split(_ABREV_MES.sub(r"\1", texto))
        if frase.strip()
        for it in _items_frase(frase, tech, volumen, tema_volumen)
    ]


def check_chart_reading(reading: ChartReading, tech: TechnicalSummary) -> ChartCheck:
    """Contrasta la lectura del modelo de visión con los indicadores calculados en Python."""
    items = [_item_trend(reading, tech)]
    for texto in (reading.description, *reading.observations):
        items.extend(_items_texto(texto, tech))
    confirmadas = sum(1 for i in items if i.verdict == "confirmada")
    verificables = sum(1 for i in items if i.verdict != "no_verificable")
    puntuacion = confirmadas / verificables if verificables else PUNTUACION_NEUTRA
    return ChartCheck(agreement_score=puntuacion, items=tuple(items))
