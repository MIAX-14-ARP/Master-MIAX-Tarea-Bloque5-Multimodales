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
    porcentaje: bool
    inicio: int
    fin: int


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
        porcentaje = bool(_PORCENTAJE.match(resto))
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
                lecturas.append(
                    _Num(valor * factor, Decimal(10) ** -decimales * factor, exp > 0, porcentaje, inicio, fin)
                )
        salida.append((text[inicio:fin].strip(), lecturas))
    return salida


def _equivalentes(a: _Num, b: _Num) -> bool:
    """¿Son la misma cifra? Exacta, o con equivalencia de escala y tolerancia de redondeo."""
    if a.valor == b.valor:
        return True
    if a.porcentaje or b.porcentaje or not (a.escalado or b.escalado):
        return False
    for k in _K_ESCALA:
        factor = Decimal(10) ** k
        tolerancia = max(a.unidad, b.unidad * factor) / 2
        if abs(a.valor - b.valor * factor) <= tolerancia:
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


def check_figures(report: AnalysisReport, document: IngestedDocument) -> tuple[FigureCheck, ...]:
    """Verifica cada cifra clave del informe contra la página del documento que cita.

    - `verificada`: todos sus números aparecen (con tolerancia de formato y escala) en alguna de las
      páginas citadas; `matched` recoge lo hallado.
    - `no_encontrada`: cita una página pero algún número no aparece en ella.
    - `sin_fuente_documental`: no cita el documento con página (solo gráfico/audio) o su valor no
      contiene ningún número que comprobar. No se busca nunca en el resto del documento.
    """
    texto_paginas = _texto_por_pagina(document)
    cache: dict[int, list[tuple[str, list[_Num]]]] = {}
    resultado: list[FigureCheck] = []
    for cifra in report.key_figures:
        paginas = _paginas_citadas(cifra.citations)
        valores = [lect for _, lect in _nums_del_texto(cifra.value, split_spaces=False)]
        if not paginas or not valores:
            resultado.append(FigureCheck(cifra.name, cifra.value, "sin_fuente_documental"))
            continue
        for pagina in paginas:
            if pagina not in cache:
                cache[pagina] = _nums_del_texto(texto_paginas.get(pagina, ""), split_spaces=True)
            hallados = _buscar_en_pagina(valores, cache[pagina])
            if hallados is not None:
                resultado.append(
                    FigureCheck(cifra.name, cifra.value, "verificada", pagina, " · ".join(dict.fromkeys(hallados)))
                )
                break
        else:
            resultado.append(FigureCheck(cifra.name, cifra.value, "no_encontrada", paginas[0]))
    return tuple(resultado)
