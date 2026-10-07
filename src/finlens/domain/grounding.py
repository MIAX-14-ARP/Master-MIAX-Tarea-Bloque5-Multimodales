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
import unicodedata
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
TOLERANCIA_REDONDEO = Decimal("0.75")  # de una unidad del último dígito citado: redondeo o truncado
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
    simple: bool = False  # entero pelado sin unidad ni escala (p.ej. un año o un «3»)

    @property
    def porcentaje(self) -> bool:
        return self.unidad_txt == "%"


def _canonico(texto: str) -> str | None:
    try:
        return format(Decimal(texto).normalize(), "f")
    except InvalidOperation:
        return None


def _lecturas(token: str, pista: str | None = None) -> list[str]:
    """Cadenas decimales (con punto) que puede representar un token numérico.

    `pista` es el separador decimal dominante del texto («.» o «,»): resuelve «10.712» como decimal en un
    texto inglés y como miles en uno español.
    """
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
        if pista is not None and forma_miles:  # la notación del texto decide (salvo «12.300»: acaba en 0)
            return [como_decimal] if sep == pista and not fraccion.endswith("0") else [como_miles]
        # «1.234» puede ser miles o decimal; «12.300» o «1.450» (acaba en 0) casi seguro son miles.
        if forma_miles and not fraccion.endswith("0"):
            return [como_decimal, como_miles]
        return [como_miles] if forma_miles else [como_decimal]
    return [limpio]


def _pista_decimal(text: str) -> str | None:
    """Separador decimal dominante del texto según los números inequívocos, o None si no hay evidencia."""
    votos = {".": 0, ",": 0}
    for m in _NUMERO.finditer(text):
        t = re.sub(rf"{_WS}", "", m.group())
        puntos, comas = t.count("."), t.count(",")
        if puntos and comas:
            votos["." if t.rfind(".") > t.rfind(",") else ","] += 1
        elif puntos + comas > 1:
            votos["," if puntos else "."] += 1  # el repetido son miles: el decimal es el otro
        elif puntos + comas == 1:
            sep = "." if puntos else ","
            if len(t.split(sep)[1]) != 3:
                votos[sep] += 1
    if votos["."] == votos[","]:
        return None
    return "." if votos["."] > votos[","] else ","


_ESCALA_IMPLICITA = re.compile(
    r"\b(?:in|en|expressed in|expresad\w+ en)\s+(?P<w>thousands|millions|billions|miles|millones)\b", re.IGNORECASE
)
_EXP_IMPLICITA = {"thousands": 3, "miles": 3, "millions": 6, "millones": 6, "billions": 9}


def _escala_implicita(text: str) -> int:
    """Escala de la tabla si la página lo declara («Amounts in millions of euros»): 3, 6, 9 o 0."""
    m = _ESCALA_IMPLICITA.search(text)
    return _EXP_IMPLICITA[m.group("w").lower()] if m else 0


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


def _nums_del_texto(
    text: str, *, split_spaces: bool, escala_implicita: bool = False
) -> list[tuple[str, list[_Num]]]:
    """Cada número del texto: (fragmento tal cual, lecturas posibles con escala y porcentaje).

    Con `escala_implicita` (páginas) un número sin escala propia se lee también multiplicado por la escala
    que declara la página («Amounts in millions of euros»).
    """
    salida: list[tuple[str, list[_Num]]] = []
    pista = _pista_decimal(text)
    exp_tabla = _escala_implicita(text) if escala_implicita else 0
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
            for cad in _lecturas(trozo, pista):
                valor = Decimal(cad)
                decimales = len(cad.split(".")[1]) if "." in cad else 0
                factor = Decimal(10) ** exp
                digitos = len(re.sub(r"\D", "", trozo))
                simple = trozo.isdigit() and exp == 0 and not unidad_txt
                lecturas.append(
                    _Num(valor * factor, Decimal(10) ** -decimales * factor, exp > 0, unidad_txt, digitos,
                         inicio, fin, simple)
                )
                es_anio = simple and 1900 <= valor <= 2100
                if exp_tabla and exp == 0 and not unidad_txt and not es_anio:
                    f2 = Decimal(10) ** exp_tabla
                    lecturas.append(
                        _Num(valor * f2, Decimal(10) ** -decimales * f2, True, "", digitos, inicio, fin)
                    )
        salida.append((text[inicio:fin].strip(), lecturas))
    return salida


def _equivalentes(a: _Num, b: _Num) -> bool:
    """¿Es `b` (texto de la fuente) la cifra citada `a`? Exacta, o con escala y tolerancia de redondeo.

    Reglas anti-falsos positivos: una unidad citada («%», «bps») debe aparecer pegada al número de la
    fuente; la coincidencia aproximada y el cambio de escala exigen palabra de escala en algún lado (y, en
    el lado sin ella, al menos 3 cifras); y el número de la fuente debe tener al menos la precisión del
    citado (2.3 no casa con 2). La tolerancia es 0,75 unidades del último dígito citado (redondeo o truncado): «39.8 bn» casa
    con 39,864 M pero «2.4 bn» no casa con «2.3 bn» ni «$417 bn» con 416,2.
    """
    if a.unidad_txt and b.unidad_txt != a.unidad_txt:
        return False
    if a.valor == b.valor:
        return True
    if a.unidad_txt or b.unidad_txt or not (a.escalado or b.escalado):
        return False
    # Con palabra de escala en AMBOS lados la magnitud ya está fijada: solo k=0 (10,7 bn ≠ 10.712 millones).
    for k in (0,) if (a.escalado and b.escalado) else (0, *_K_ESCALA):
        factor = Decimal(10) ** k
        if (not a.escalado and a.digitos < MIN_DIGITOS_SIN_ESCALA) or (
            not b.escalado and b.digitos < MIN_DIGITOS_SIN_ESCALA
        ):
            continue
        if a.valor == b.valor * factor:
            return True
        unidad_b = b.unidad * factor
        if unidad_b <= a.unidad and abs(a.valor - b.valor * factor) < TOLERANCIA_REDONDEO * a.unidad:
            return True
    return False


def _paginas_citadas(citations: list[Citation]) -> tuple[list[int], bool]:
    """Páginas de las citas a documento y si alguna cita a documento viene con una página mal formada.

    Una cita sin localización (location vacío) no se puede comprobar; una con localización que no
    contiene ninguna página válida («p.-1», «p.abc») es una cita rota: no es neutral.
    """
    paginas: list[int] = []
    malformada = False
    for c in citations:
        if c.origin != "documento":
            continue
        encontradas = False
        for m in _PAGINA.finditer(c.location):
            desde = int(m.group(1))
            hasta = int(m.group(2)) if m.group(2) else desde
            if desde <= hasta <= desde + 50:  # rango «pp. 3-4»
                paginas += range(desde, hasta + 1)
                encontradas = True
        if c.location.strip() and not encontradas:
            malformada = True
    return list(dict.fromkeys(paginas)), malformada


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
) -> list[tuple[str, str, float, bool]]:
    """(clave, etiqueta, valor, es_fraccion) de las cifras de mercado calculadas; una fracción se compara también ×100."""
    objetivos: list[tuple[str, str, float, bool]] = []
    if tech is not None:
        for clave, etiqueta, valor, fraccion in (
            ("cierre", "Último cierre", tech.last_close, False), ("sma20", "SMA20", tech.sma20, False),
            ("sma50", "SMA50", tech.sma50, False), ("ema", "EMA20", tech.ema20, False),
            ("rsi", "RSI14", tech.rsi14, False), ("minimo", "Mínimo del periodo", tech.range_low, False),
            ("maximo", "Máximo del periodo", tech.range_high, False),
            ("rentabilidad", "Rentabilidad del periodo", tech.period_return, True),
            ("volatilidad", "Volatilidad anualizada", tech.volatility_annual, True),
            ("drawdown", "Máximo drawdown", tech.max_drawdown, True),
        ):
            if valor is not None:
                objetivos.append((clave, etiqueta, float(valor), fraccion))
        objetivos += [("soporte", f"Soporte {i + 1}", float(v), False) for i, v in enumerate(tech.supports)]
        objetivos += [("resistencia", f"Resistencia {i + 1}", float(v), False) for i, v in enumerate(tech.resistances)]
    if derivs is not None:
        objetivos += [
            ("funding", "Funding anualizado", derivs.funding_annualized, True),
            ("funding", "Funding horario", derivs.funding_hourly, True),
            ("oi", "Open interest (unidades del activo)", derivs.open_interest, False),
            ("oi", "Open interest nocional (USD)", derivs.open_interest * derivs.mark_px, False),
            ("precio", "Precio mark", derivs.mark_px, False), ("precio", "Precio oráculo", derivs.oracle_px, False),
            ("volumen", "Volumen nocional 24 h", derivs.day_notional_volume, False),
            ("precio", "Cierre previo", derivs.prev_day_px, False),
        ]
    return objetivos


def _sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c))


_NOMBRE_INDICADOR = re.compile(r"\b(rsi|sma|ema|ma|mm)\s*\(?\s*\d+\s*\)?", re.IGNORECASE)
_ASOCIACION = (  # (regex sobre nombre+valor sin acentos, claves de objetivo)
    (r"\brsi\b", {"rsi"}),
    (r"\bsma\s*\(?\s*50\b|media.{0,20}\b50\b", {"sma50"}),
    (r"\bsma\s*\(?\s*20\b|media.{0,20}\b20\b", {"sma20"}),
    (r"\bsma\b|media movil|moving average", {"sma20", "sma50"}),
    (r"\bema\b", {"ema"}),
    (r"cierre|close|ultimo precio|precio actual|cotizacion", {"cierre"}),
    (r"rentabilidad|retorno|return|variacion", {"rentabilidad"}),
    (r"volatilidad|volatility", {"volatilidad"}),
    (r"drawdown|caida maxima", {"drawdown"}),
    (r"maximo|maximum|\bhigh\b|\bmax\b", {"maximo"}),
    (r"minimo|minimum|\blow\b|\bmin\b", {"minimo"}),
    (r"soporte|support", {"soporte"}),
    (r"resistencia|resistance", {"resistencia"}),
    (r"funding", {"funding"}),
    (r"open interest|interes abierto|\boi\b", {"oi"}),
    (r"volumen|volume", {"volumen"}),
    (r"\bmark\b|oraculo|oracle", {"precio"}),
)


def _claves_de(nombre: str, valor: str) -> set[str] | None:
    """Clave(s) del indicador al que se refiere la cifra (por su nombre/valor), o None si no se reconoce."""
    texto = _sin_acentos(f"{nombre} {valor}")
    for patron, claves in _ASOCIACION:
        if re.search(patron, texto):
            return set(claves)
    return None


def _cerca(a: float, t: float) -> bool:
    return abs(abs(a) - abs(t)) <= TOLERANCIA_MERCADO * abs(t)


def _buscar_en_mercado(
    valores: list[list[_Num]], objetivos: list[tuple[str, str, float, bool]], claves: set[str] | None = None
) -> list[str] | None:
    """Etiquetas de las cifras de mercado (tolerancia 1 %) que casan con todos los números del valor.

    Si se reconoce el indicador (`claves`) solo se compara con él: «RSI 54» no puede casar con el cierre.
    """
    candidatos = [o for o in objetivos if claves is None or o[0] in claves]
    encontrados: list[str] = []
    for lecturas in valores:
        hallado = None
        for a in lecturas:
            for _clave, etiqueta, t, fraccion in candidatos:
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
            b = _Num(Decimal(str(abs(hecho.value))), Decimal(1), False, "", 12, 0, 0)  # el hecho no trae escala: la exige el citado
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
        paginas, malformada = _paginas_citadas(cifra.citations)
        origenes = {c.origin for c in cifra.citations}
        valor_texto = _NOMBRE_INDICADOR.sub(lambda m: m.group(1), cifra.value)  # «RSI (14): 61,7» → «RSI: 61,7»
        valores = [lect for _, lect in _nums_del_texto(valor_texto, split_spaces=False)]
        comprobable = bool(paginas) or malformada or "sec" in origenes or "mercado" in origenes
        if not comprobable or not valores:
            resultado.append(FigureCheck(cifra.name, cifra.value, "sin_fuente_documental"))
            continue
        if all(lect[0].simple and (lect[0].valor < 10 or 1900 <= lect[0].valor <= 2100) for lect in valores):
            # un año o un entero < 10 sin unidad coincide con cualquier página: no es una cifra verificable
            resultado.append(FigureCheck(cifra.name, cifra.value, "sin_fuente_documental"))
            continue
        veredicto: FigureCheck | None = None
        for pagina in paginas:
            if pagina not in cache:
                cache[pagina] = _nums_del_texto(texto_paginas.get(pagina, ""), split_spaces=True, escala_implicita=True)
            hallados = _buscar_en_pagina(valores, cache[pagina])
            if hallados is not None:
                veredicto = FigureCheck(cifra.name, cifra.value, "verificada", pagina, " · ".join(dict.fromkeys(hallados)))
                break
        if veredicto is None and "sec" in origenes and fundamentals is not None:
            hallados = _buscar_en_sec(valores, fundamentals)
            if hallados is not None:
                veredicto = FigureCheck(cifra.name, cifra.value, "verificada", None, " · ".join(dict.fromkeys(hallados)))
        if veredicto is None and "mercado" in origenes and objetivos:
            hallados = _buscar_en_mercado(valores, objetivos, _claves_de(cifra.name, cifra.value))
            if hallados is not None:
                veredicto = FigureCheck(cifra.name, cifra.value, "verificada", None, " · ".join(dict.fromkeys(hallados)))
        resultado.append(veredicto or FigureCheck(cifra.name, cifra.value, "no_encontrada", paginas[0] if paginas else None))
    return tuple(resultado)
