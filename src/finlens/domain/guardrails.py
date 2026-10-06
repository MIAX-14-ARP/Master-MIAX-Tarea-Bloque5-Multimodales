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
    r"buen momento para|oportunidad de|aprovech\w+ para|deberias?|debes|deberiais|toca|"
    r"mi consejo es|nuestro consejo es)"
)
_IMPERATIVO = r"(?:compre|compren|comprad|venda|vendan|vended)"

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
    # «precio objetivo», «price target»
    r"\b(?:precio[- ]objetivo|objetivo de precio|valor objetivo|cotizacion objetivo|"
    r"price target|target price)\b",
    # «recomendación de compra», «rating: sobreponderar»
    r"\b(?:recomendacion|rating|calificacion|consejo)\s*:?\s*(?:de\s+)?"
    r"(?:compra|venta|comprar|vender|mantener|neutral|sobreponderar|infraponderar)\b",
    r"\b(?:strong buy|strong sell|buy rating|sell rating|hold rating|overweight|underweight|"
    r"outperform|underperform)\b",
]
_REGEX = [re.compile(p) for p in _PATRONES]


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
    """Minúsculas y sin acentos, para comparar sin depender de la ortografía."""
    descompuesto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def detect_recommendations(text: str) -> list[str]:
    """Fragmentos (normalizados) de `text` que parecen una recomendación de inversión."""
    normalizado = _normalizar(text)
    return [m.group(0) for regex in _REGEX for m in regex.finditer(normalizado)]


def guard_text(text: str, field: str = "texto") -> tuple[str, list[Violation]]:
    """Devuelve `text` o, si contiene lenguaje de recomendación, el aviso de retirada."""
    encontrados = detect_recommendations(text)
    if not encontrados:
        return text, []
    return REMOVED_NOTICE, [Violation(field, m) for m in encontrados]


def with_disclaimer(text: str) -> str:
    """Añade el disclaimer a una salida de texto (chat, informe exportado...)."""
    return f"{text}\n\n{DISCLAIMER}"


def _filtrar_findings(
    items: list[Finding], field: str, violations: list[Violation]
) -> list[Finding]:
    """Descarta las afirmaciones con lenguaje de recomendación y registra la infracción."""
    limpios: list[Finding] = []
    for item in items:
        encontrados = detect_recommendations(item.statement)
        violations += [Violation(field, m) for m in encontrados]
        if not encontrados:
            limpios.append(item)
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
