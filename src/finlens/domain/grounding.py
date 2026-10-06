"""Verificación determinista de las cifras del informe contra el texto del documento.

Los LLM pueden inventar o alterar cifras aunque citen una página. Aquí se comprueba, sin IA, que cada
número de una cifra clave citada a «documento p.N» aparece en el texto de esa página. Se toleran:

- formatos español (`1.234,5`) e inglés (`1,234.5`); los símbolos (`%`, `€`, `M€`...) no participan;
- números ambiguos (`1.234`, `1,234`): se aceptan ambas lecturas (si acaban en 0, como `12.300`, se
  leen como miles);
- equivalencia de escala: «€10.7 billion», «10.700 millones» y «10,700» (tabla en millones) son la
  misma cifra. Se reconocen las palabras miles/thousand/k, millones/million/mn/M y
  mil millones/billion/bn/B, y se acepta `a == b * 10**k` con k ∈ {±3, ±6, ±9} y tolerancia de
  redondeo. Los porcentajes solo casan exactamente (sin cambio de escala).

Se compara la magnitud: el signo no se tiene en cuenta. No se busca nunca fuera de la página citada.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from finlens.domain.ingest import IngestedDocument
from finlens.domain.schemas import AnalysisReport, Citation
from finlens.domain.technicals import TechnicalSummary
from finlens.sources.base import DerivativesSnapshot, Fundamentals

Status = Literal["verificada", "no_encontrada", "sin_fuente_documental"]

_ESPACIOS = "   "
_WS = rf"[\s{_ESPACIOS}]"
# Número con separadores de miles (punto, coma o espacio) y/o decimales, o número simple.
_NUMERO = re.compile(
    rf"(?<![\w.,])\d{{1,3}}(?:[.,{_WS[1:-1]}]\d{{3}})+(?:[.,]\d+)?(?![\d])|(?<![\w.,])\d+(?:[.,]\d+)?"
)
_PAGINA = re.compile(
    r"\b(?:pp?|pags?|p[aá]g(?:inas?)?|pages?)\.?\s*(\d+)(?:\s*[-–]\s*(\d+))?", re.IGNORECASE
)
# Moneda opcional y palabra de escala justo después del número (de mayor a menor longitud).
_ESCALA = re.compile(
    rf"^{_WS}*(?:[€$£]|EUR\b|USD\b|euros?\b)?{_WS}*"
    r"(?P<w>mil\s+millones|miles\s+de\s+millones|billions?|bn|millones|mill[oó]n|millions?|mn|M|B"
    r"|miles|thousands?|mil|k|K)(?![A-Za-zÁ-ú])"
)
_ESCALAS = {
    "mil millones": 9, "miles de millones": 9, "billion": 9, "billions": 9, "bn": 9, "b": 9,
    "millones": 6, "millón": 6, "millon": 6, "million": 6, "millions": 6, "mn": 6, "m": 6,
    "miles": 3, "thousand": 3, "thousands": 3, "mil": 3, "k": 3,
}
_PORCENTAJE = re.compile(rf"^{_WS}*(?:%|por\s+ciento|percent|pp\b)", re.IGNORECASE)
_BPS = re.compile(rf"^{_WS}*(?:bps?\b|basis\s+points?|puntos\s+b[aá]sicos)", re.IGNORECASE)
MIN_DIGITOS_SIN_ESCALA = 3  # un número suelto de 1-2 cifras no puede «ser» una cifra escalada (p.ej. 2 ≠ 2 bn)
_K_ESCALA = (3, -3, 6, -6, 9, -9)


@dataclass(frozen=True)
class FigureCheck:
    """Resultado de verificar una cifra clave del informe.

    `matched` es el texto encontrado en la página (p.ej. «€10.7 billion») cuando está verificada.
    """

    figure_name: str
    value: str
    status: Status
    page: int | None = None
    matched: str | None = None


@dataclass(frozen=True)
class _Num:
    """Una lectura posible de un número del texto, con su escala y posición."""

    valor: Decimal  # efectivo, con la escala aplicada
    unidad: Decimal  # precisión del último dígito (con escala)
    escalado: bool  # lleva palabra de escala
    unidad_txt: str  # «%», «bps» o «» (unidad pegada al número)
    digitos: int  # cifras del token (sin separadores)
    inicio: int
    fin: int

    @property
    def porcentaje(self) -> bool:
        return self.unidad_txt == "%"


def _canonico(texto: str) -> str | None:
    try:
        return format(Decimal(texto).normalize(), "f")
    except InvalidOperation:
        return None


def _lecturas(token: str) -> list[str]:
    """Cadenas decimales (con punto) que puede representar un token numérico."""
    limpio = re.sub(rf"{_WS}", "", token)
    tenia_espacios = limpio != token
    puntos, comas = limpio.count("."), limpio.count(",")
    if puntos and comas:
        decimal = "." if limpio.rfind(".") > limpio.rfind(",") else ","
        miles = "," if decimal == "." else "."
        return [limpio.replace(miles, "").replace(decimal, ".")]
    if puntos + comas > 1:  # mismo separador repetido: miles
        return [limpio.replace(".", "").replace(",", "")]
    if puntos + comas == 1:
        sep = "." if puntos else ","
        entero, fraccion = limpio.split(sep)
        como_decimal = f"{entero}.{fraccion}"
        como_miles = f"{entero}{fraccion}"
        forma_miles = len(fraccion) == 3 and 1 <= len(entero) <= 3 and entero != "0"
        if tenia_espacios:  # «1 234,5»: el separador es decimal
            return [como_decimal]
        # «1.234» puede ser miles o decimal; «12.300» o «1.450» (acaba en 0) casi seguro son miles.
        if forma_miles and not fraccion.endswith("0"):
            return [como_decimal, como_miles]
        return [como_miles] if forma_miles else [como_decimal]
    return [limpio]


def number_candidates(token: str) -> set[str]:
    """Valores canónicos que puede representar un token numérico (más de uno si es ambiguo)."""
    return {c for c in map(_canonico, _lecturas(token)) if c is not None}


def extract_numbers(text: str, *, split_spaces: bool = False) -> set[str]:
    """Valores canónicos de todos los números de `text` (sin escalas).

    Con `split_spaces` los números con espacios («12 300») también cuentan por partes; así una
    tabla con columnas separadas por espacios no oculta una cifra.
    """
    encontrados: set[str] = set()
    for m in _NUMERO.finditer(text):
        token = m.group()
        encontrados |= number_candidates(token)
        if split_spaces and re.search(_WS, token):
            for parte in re.split(rf"{_WS}+", token):
                encontrados |= number_candidates(parte)
    return encontrados


def _nums_del_texto(text: str, *, split_spaces: bool) -> list[tuple[str, list[_Num]]]:
    """Cada número del texto: (fragmento tal cual, lecturas posibles con escala y porcentaje)."""
    salida: list[tuple[str, list[_Num]]] = []
    for m in _NUMERO.finditer(text):
        resto = text[m.end():m.end() + 40]
        escala_m = _ESCALA.match(resto)
        exp = _ESCALAS.get(re.sub(r"\s+", " ", escala_m.group("w")).lower(), 0) if escala_m else 0
        if escala_m and escala_m.group("w") in ("M", "B"):
            exp = 6 if escala_m.group("w") == "M" else 9
        fin = m.end() + (escala_m.end() if escala_m else 0)
        pct, bps = _PORCENTAJE.match(resto), _BPS.match(resto)
        unidad_txt = "%" if pct else ("bps" if bps else "")
        if not escala_m and (pct or bps):
            fin = m.end() + (pct or bps).end()  # type: ignore[union-attr]
        inicio = m.start()
        if inicio > 0 and text[inicio - 1] in "€$£":
            inicio -= 1
        trozos = [m.group()]
        if split_spaces and re.search(_WS, m.group()):
            trozos += re.split(rf"{_WS}+", m.group())
        lecturas: list[_Num] = []
        for trozo in trozos:
            for cad in _lecturas(trozo):
                valor = Decimal(cad)
                decimales = len(cad.split(".")[1]) if "." in cad else 0
                factor = Decimal(10) ** exp
                digitos = len(re.sub(r"\D", "", trozo))
                lecturas.append(
                    _Num(valor * factor, Decimal(10) ** -decimales * factor, exp > 0, unidad_txt, digitos,
                         inicio, fin)
                )
        salida.append((text[inicio:fin].strip(), lecturas))
    return salida


def _equivalentes(a: _Num, b: _Num) -> bool:
    """¿Es `b` (texto de la fuente) la cifra citada `a`? Exacta, o con escala y tolerancia de redondeo.

    Reglas anti-falsos positivos: una unidad citada («%», «bps») debe aparecer pegada al número de la
    fuente; el cambio de escala exige palabra de escala en algún lado y, en el lado sin ella, al menos
    3 cifras; y una coincidencia aproximada exige que el número de la fuente tenga al menos la
    precisión del citado (2.3 no casa con 2).
    """
    if a.unidad_txt and b.unidad_txt != a.unidad_txt:
        return False
    if a.valor == b.valor:
        return True
    if a.unidad_txt or b.unidad_txt or not (a.escalado or b.escalado):
        return False
    for k in _K_ESCALA:
        factor = Decimal(10) ** k
        if (not a.escalado and a.digitos < MIN_DIGITOS_SIN_ESCALA) or (
            not b.escalado and b.digitos < MIN_DIGITOS_SIN_ESCALA
        ):
            continue
        if a.valor == b.valor * factor:
            return True
        unidad_b = b.unidad * factor
        if unidad_b <= a.unidad and abs(a.valor - b.valor * factor) <= max(a.unidad, unidad_b) / 2:
            return True
    return False


def _paginas_citadas(citations: list[Citation]) -> list[int]:
    """Páginas de las citas a documento (las citas sin página no se pueden comprobar)."""
    paginas: list[int] = []
    for c in citations:
        if c.origin != "documento":
            continue
        for m in _PAGINA.finditer(c.location):
            desde = int(m.group(1))
            hasta = int(m.group(2)) if m.group(2) else desde
            if desde <= hasta <= desde + 50:  # rango «pp. 3-4»
                paginas += range(desde, hasta + 1)
    return list(dict.fromkeys(paginas))


def _texto_por_pagina(document: IngestedDocument) -> dict[int, str]:
    paginas: dict[int, list[str]] = {}
    for chunk in document.chunks:
        paginas.setdefault(chunk.page, []).append(chunk.text)
    return {p: " ".join(textos) for p, textos in paginas.items()}


def _buscar_en_pagina(valores: list[list[_Num]], pagina: list[tuple[str, list[_Num]]]) -> list[str] | None:
    """Fragmentos de la página que casan con todos los números del valor, o None si falta alguno."""
    encontrados: list[str] = []
    for lecturas in valores:
        hallado = next(
            (frag for frag, cands in pagina if any(_equivalentes(a, b) for a in lecturas for b in cands)),
            None,
        )
        if hallado is None:
            return None
        encontrados.append(hallado)
    return encontrados


TOLERANCIA_MERCADO = 0.01  # 1 % relativo frente a los números calculados en Python


def _objetivos_mercado(
    tech: TechnicalSummary | None, derivs: DerivativesSnapshot | None
) -> list[tuple[str, float, bool]]:
    """(etiqueta, valor, es_fraccion) de las cifras de mercado calculadas; una fracción se compara también ×100."""
    objetivos: list[tuple[str, float, bool]] = []
    if tech is not None:
        for etiqueta, valor, fraccion in (
            ("Último cierre", tech.last_close, False), ("SMA20", tech.sma20, False), ("SMA50", tech.sma50, False),
            ("EMA20", tech.ema20, False), ("RSI14", tech.rsi14, False), ("Mínimo del periodo", tech.range_low, False),
            ("Máximo del periodo", tech.range_high, False), ("Rentabilidad del periodo", tech.period_return, True),
            ("Volatilidad anualizada", tech.volatility_annual, True), ("Máximo drawdown", tech.max_drawdown, True),
        ):
            if valor is not None:
                objetivos.append((etiqueta, float(valor), fraccion))
        objetivos += [(f"Soporte {i + 1}", float(v), False) for i, v in enumerate(tech.supports)]
        objetivos += [(f"Resistencia {i + 1}", float(v), False) for i, v in enumerate(tech.resistances)]
    if derivs is not None:
        objetivos += [
            ("Funding anualizado", derivs.funding_annualized, True), ("Funding horario", derivs.funding_hourly, True),
            ("Open interest", derivs.open_interest, False), ("Precio mark", derivs.mark_px, False),
            ("Precio oráculo", derivs.oracle_px, False), ("Volumen nocional 24 h", derivs.day_notional_volume, False),
            ("Cierre previo", derivs.prev_day_px, False),
        ]
    return objetivos


def _cerca(a: float, t: float) -> bool:
    return abs(abs(a) - abs(t)) <= TOLERANCIA_MERCADO * abs(t)


def _buscar_en_mercado(valores: list[list[_Num]], objetivos: list[tuple[str, float, bool]]) -> list[str] | None:
    """Etiquetas de las cifras de mercado (tolerancia 1 %) que casan con todos los números del valor."""
    encontrados: list[str] = []
    for lecturas in valores:
        hallado = None
        for a in lecturas:
            for etiqueta, t, fraccion in objetivos:
                if a.porcentaje and not fraccion:
                    continue  # un porcentaje citado solo casa con magnitudes que son proporciones
                destinos = (t * 100, t) if fraccion else (t,)
                if any(_cerca(float(a.valor), d) for d in destinos):
                    hallado = f"{etiqueta}: {t:.4g}"
                    break
            if hallado:
                break
        if hallado is None:
            return None
        encontrados.append(hallado)
    return encontrados


def _buscar_en_sec(valores: list[list[_Num]], fund: Fundamentals) -> list[str] | None:
    """Hechos del 10-K que casan (con escala y redondeo) con todos los números del valor."""
    encontrados: list[str] = []
    for lecturas in valores:
        hallado = None
        for hecho in fund.facts:
            b = _Num(Decimal(str(abs(hecho.value))), Decimal(1), True, "", 12, 0, 0)
            if any(_equivalentes(a, b) for a in lecturas):
                hallado = f"{hecho.label_es} FY{hecho.fy}: {hecho.value / 1e6:,.0f} M {hecho.unit}"
                break
        if hallado is None:
            return None
        encontrados.append(hallado)
    return encontrados


def check_figures(
    report: AnalysisReport,
    document: IngestedDocument | None,
    *,
    technicals: TechnicalSummary | None = None,
    derivatives: DerivativesSnapshot | None = None,
    fundamentals: Fundamentals | None = None,
) -> tuple[FigureCheck, ...]:
    """Verifica cada cifra clave del informe contra la fuente que cita.

    - `documento p.N`: contra el texto de esa página (nunca contra el resto del documento).
    - `sec`: contra los hechos del 10-K (equivalencia de escala y redondeo).
    - `mercado`: contra los números calculados en Python (indicadores, derivados), con tolerancia del 1 %.

    Estados: `verificada` (todos sus números aparecen; `matched` recoge lo hallado), `no_encontrada`
    (cita una fuente comprobable pero algún número no aparece) y `sin_fuente_documental` (solo cita
    gráfico/audio, no hay página citada o su valor no contiene ningún número).
    """
    texto_paginas = _texto_por_pagina(document) if document is not None else {}
    cache: dict[int, list[tuple[str, list[_Num]]]] = {}
    objetivos = _objetivos_mercado(technicals, derivatives)
    resultado: list[FigureCheck] = []
    for cifra in report.key_figures:
        paginas = _paginas_citadas(cifra.citations)
        origenes = {c.origin for c in cifra.citations}
        valores = [lect for _, lect in _nums_del_texto(cifra.value, split_spaces=False)]
        comprobable = bool(paginas) or "sec" in origenes or "mercado" in origenes
        if not comprobable or not valores:
            resultado.append(FigureCheck(cifra.name, cifra.value, "sin_fuente_documental"))
            continue
        veredicto: FigureCheck | None = None
        for pagina in paginas:
            if pagina not in cache:
                cache[pagina] = _nums_del_texto(texto_paginas.get(pagina, ""), split_spaces=True)
            hallados = _buscar_en_pagina(valores, cache[pagina])
            if hallados is not None:
                veredicto = FigureCheck(cifra.name, cifra.value, "verificada", pagina, " · ".join(dict.fromkeys(hallados)))
                break
        if veredicto is None and "sec" in origenes and fundamentals is not None:
            hallados = _buscar_en_sec(valores, fundamentals)
            if hallados is not None:
                veredicto = FigureCheck(cifra.name, cifra.value, "verificada", None, " · ".join(dict.fromkeys(hallados)))
        if veredicto is None and "mercado" in origenes and objetivos:
            hallados = _buscar_en_mercado(valores, objetivos)
            if hallados is not None:
                veredicto = FigureCheck(cifra.name, cifra.value, "verificada", None, " · ".join(dict.fromkeys(hallados)))
        resultado.append(veredicto or FigureCheck(cifra.name, cifra.value, "no_encontrada", paginas[0] if paginas else None))
    return tuple(resultado)
