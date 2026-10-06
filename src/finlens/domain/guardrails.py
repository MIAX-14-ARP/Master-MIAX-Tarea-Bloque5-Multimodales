"""Guardrail de compliance: FinLens informa, no asesora (MiFID II / CNMV).

Detección determinista por expresiones regulares de lenguaje de recomendación (compra, venta,
precio objetivo...). Es una heurística conservadora: prefiere retirar de más antes que dejar pasar
una recomendación. No sustituye la revisión legal.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from finlens.domain.schemas import AnalysisReport, Finding

DISCLAIMER = (
    "Información generada con IA con fines informativos. No constituye asesoramiento en materia "
    "de inversión ni recomendación de compra o venta de valores."
)
SPOKEN_DISCLAIMER = (
    "Aviso: contenido generado con inteligencia artificial, solo informativo; "
    "no es asesoramiento de inversión."
)
REMOVED_NOTICE = "[Contenido retirado: incumple la política de no asesoramiento]"
REPORT_NOTICE = "Se ha retirado contenido que incumplía la política de no asesoramiento."

_ACCION = (
    r"(?:comprar|vender|acumular|infraponderar|sobreponderar|liquidar|"
    r"(?:mantener|adquirir)\s+(?:mas\s+)?(?:las\s+|los\s+|la\s+|su\s+|tu\s+)?"
    r"(?:acciones|titulos|valores|posicion))"
)
_VERBO_RECOMENDACION = (
    r"(?:recom\w+|aconsej\w+|sug\w+|conviene|hay que|es (?:el |la )?(?:momento|hora) de|"
    r"buen momento para|oportunidad de|aprovech\w+ para|deberi\w+|debes|toca|"
    r"mi consejo es|nuestro consejo es)"
)
_IMPERATIVO = r"(?:compre|compren|comprad|venda|vendan|vended)"

# «Precio objetivo» describe una recomendación de valor. Si habla de un tercero no relacionado con un valor
# (regulador, banco central, inflación) es una magnitud macroeconómica y se permite. Decisión de diseño:
# solo se exime cuando la frase menciona ese contexto Y no menciona ningún valor (acción, cotización...).
_PRECIO_OBJETIVO = re.compile(
    r"\b(?:precio[- ]objetivo|objetivo de precio|valor objetivo|cotizacion objetivo|price target|target price)\b"
)
_CONTEXTO_MACRO = re.compile(
    r"\b(?:regulador\w*|banco central|bce|fed|reserva federal|inflacion|regulator|central bank|ecb)\b"
)
_CONTEXTO_VALOR = re.compile(
    r"\b(?:accion\w*|acciones|valor|titulo\w*|cotizacion|analista\w*|stock|shares?|equity|target price for)\b"
)

_PATRONES = [
    # «recomiendo comprar», «es un buen momento para vender», «hay que acumular»
    rf"\b{_VERBO_RECOMENDACION}\b(?:\W+\w+){{0,4}}?\W+\b{_ACCION}\b",
    # «compra ya», «vende ahora»
    r"\b(?:compra|vende)\s+(?:ya|ahora|hoy)\b",
    # «compren acciones», «venda su posición»
    rf"\b{_IMPERATIVO}\s+(?:\w+\s+){{0,2}}(?:acciones|accion|titulos|valores|posicion)\b",
    # «yo compraría», «nosotros venderíamos»
    r"\b(?:yo|nosotros)\s+(?:\w+\s+)?(?:comprari\w+|venderi\w+|acumulari\w+)\b",
    # «oportunidad de compra», «merece una compra»
    r"\boportunidad de compra\b|\bmerece\s+(?:una\s+)?(?:compra|venta)\b",
    # jerga de ponderación, inequívoca
    r"\b(?:sobreponderar|infraponderar|sobreponderad\w+|infraponderad\w+)\b",
    # «buy this stock», «sell now»
    r"\b(?:buy|sell)\s+(?:\w+\s+){0,2}(?:stock|shares|now)\b",
    # «precio objetivo», «price target» (ver _PRECIO_OBJETIVO: la excepción macro se resuelve por frase)
    _PRECIO_OBJETIVO.pattern,
    # «recomendación de compra», «rating: sobreponderar»
    r"\b(?:recomendacion|rating|calificacion|consejo)\s*:?\s*(?:de\s+)?"
    r"(?:compra|venta|comprar|vender|mantener|neutral|sobreponderar|infraponderar)\b",
    r"\b(?:strong buy|strong sell|buy rating|sell rating|hold rating|overweight|underweight|"
    r"outperform|underperform)\b",
]
_PATRONES += [
    # condicional: «compraría acciones», «vendería las acciones»
    r"\b(?:comprari\w+|venderi\w+|acumulari\w+)\s+(?:\w+\s+){0,2}(?:acciones|accion|titulos|valores|posicion|"
    r"el valor)\b",
    r"\bmerece\s+la\s+pena\s+(?:comprar|vender|acumular)\b",
    # inglés: «you should buy», «I recommend buying», «upgrade to buy», «rating: buy»
    r"\b(?:should|must|ought to|recommend(?:s|ed)?(?: that you| to)?|advise[sd]?(?: to)?)\s+"
    r"(?:buy|sell|accumulate|buying|selling|accumulating)\b",
    r"\b(?:recommend|advise|suggest)\w*\s+(?:a\s+)?(?:buy|sell)\b",
    r"\b(?:upgrade[sd]?|downgrade[sd]?|rated?|initiate[sd]?|reiterate[sd]?)\s+(?:to|at|as|with)?\s*"
    r"(?:a\s+)?(?:buy|sell|hold|overweight|underweight|outperform|underperform|accumulate)\b",
    r"\b(?:rating|recommendation|call)\s*:?\s*(?:a\s+)?(?:buy|sell|hold|accumulate|reduce)\b",
]
# Patrones que solo valen al principio de una frase (imperativo sin sujeto): «Compra Inditex», «Buy AAPL».
_PATRONES_INICIO = [
    r"^(?:compra|vende|acumula|compre|compren|venda|vendan)\s+(?!de\b|del\b|en\b|y\b|e\b|a\b|que\b|como\b)\w+",
    r"^(?:buy|sell|accumulate)\s+(?!back\b|side\b|and\b|of\b|in\b)\w+",
    r"^accumulate\b",
    r"^mantener\s+(?:la|su|tu)\s+posicion\b",
]
_REGEX = [re.compile(p) for p in _PATRONES]
_REGEX_INICIO = [re.compile(p) for p in _PATRONES_INICIO]



@dataclass(frozen=True)
class Violation:
    """Fragmento detectado como lenguaje de recomendación y el campo donde apareció."""

    field: str
    match: str


@dataclass(frozen=True)
class GuardrailResult:
    """Informe saneado y las infracciones detectadas (vacías si todo estaba en regla)."""

    report: AnalysisReport
    violations: tuple[Violation, ...]
    disclaimer: str = DISCLAIMER

    @property
    def blocked(self) -> bool:
        return bool(self.violations)


def _normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y sin caracteres invisibles (guion suave, ancho cero, NBSP...)."""
    visible = "".join(
        " " if unicodedata.category(c) == "Zs" else c
        for c in texto
        if unicodedata.category(c) != "Cf"  # U+00AD, U+200B..U+200F, U+2060, U+FEFF...
    )
    descompuesto = unicodedata.normalize("NFKD", visible.lower())
    sin_acentos = "".join(c for c in descompuesto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_acentos)


_FRASES = re.compile(r"(?<=[.!?;])\s+|\n+")


def split_sentences(texto: str) -> list[str]:
    """Frases del texto (sin tocar su contenido); un salto de línea también separa."""
    return [f for f in _FRASES.split(texto) if f.strip()]


def _detectar_frase(frase: str) -> list[str]:
    normalizada = _normalizar(frase).strip()
    encontrados: list[str] = []
    for regex in _REGEX:
        for m in regex.finditer(normalizada):
            texto = m.group(0)
            if (
                _PRECIO_OBJETIVO.search(texto)
                and _CONTEXTO_MACRO.search(normalizada)
                and not _CONTEXTO_VALOR.search(normalizada)
            ):
                continue  # precio objetivo de un regulador / magnitud macro: descriptivo
            encontrados.append(texto)
    encontrados += [ini.group(0) for regex in _REGEX_INICIO if (ini := regex.search(normalizada))]
    return encontrados


def detect_recommendations(text: str) -> list[str]:
    """Fragmentos (normalizados) de `text` que parecen una recomendación de inversión."""
    return [m for frase in split_sentences(text) for m in _detectar_frase(frase)]


def guard_text(text: str, field: str = "texto") -> tuple[str, list[Violation]]:
    """Devuelve `text` sin las frases que recomiendan; si no queda ninguna, el aviso de retirada.

    Se retira solo la frase infractora (no el campo entero) para no destrozar un resumen por una frase.
    """
    limpias: list[str] = []
    violaciones: list[Violation] = []
    for frase in split_sentences(text):
        encontrados = _detectar_frase(frase)
        violaciones += [Violation(field, m) for m in encontrados]
        if not encontrados:
            limpias.append(frase.strip())
    if not violaciones:
        return text, []
    return (" ".join(limpias) if limpias else REMOVED_NOTICE), violaciones


def with_disclaimer(text: str) -> str:
    """Añade el disclaimer a una salida de texto (chat, informe exportado...)."""
    return f"{text}\n\n{DISCLAIMER}"


def _filtrar_findings(
    items: list[Finding], field: str, violations: list[Violation]
) -> list[Finding]:
    """Quita de cada afirmación las frases con lenguaje de recomendación; si no queda nada, la descarta."""
    limpios: list[Finding] = []
    for item in items:
        texto, encontrados = guard_text(item.statement, field)
        violations += encontrados
        if not encontrados:
            limpios.append(item)
        elif texto != REMOVED_NOTICE:
            limpios.append(item.model_copy(update={"statement": texto}))
    return limpios


def apply_guardrails(report: AnalysisReport) -> GuardrailResult:
    """Sanea el informe: retira o sustituye lo que suene a recomendación y lo registra."""
    violations: list[Violation] = []
    summary, v = guard_text(report.summary, "summary")
    violations += v
    spoken, v = guard_text(report.spoken_summary, "spoken_summary")
    violations += v

    figuras = []
    for figura in report.key_figures:
        encontrados = detect_recommendations(f"{figura.name} {figura.value} {figura.period}")
        violations += [Violation("key_figures", m) for m in encontrados]
        if not encontrados:
            figuras.append(figura)

    chart = _filtrar_findings(
        [report.chart_reading] if report.chart_reading else [], "chart_reading", violations
    )
    management = _filtrar_findings(
        report.management_statements, "management_statements", violations
    )
    correlations = _filtrar_findings(report.correlations, "correlations", violations)
    contradictions = _filtrar_findings(report.contradictions, "contradictions", violations)

    limitations = []
    for texto in report.limitations:
        encontrados = detect_recommendations(texto)
        violations += [Violation("limitations", m) for m in encontrados]
        if not encontrados:
            limitations.append(texto)
    if violations:
        limitations.append(REPORT_NOTICE)

    saneado = report.model_copy(
        update={
            "summary": summary,
            "spoken_summary": spoken,
            "key_figures": figuras,
            "chart_reading": chart[0] if chart else None,
            "management_statements": management,
            "correlations": correlations,
            "contradictions": contradictions,
            "limitations": limitations,
        }
    )
    return GuardrailResult(saneado, tuple(violations))
