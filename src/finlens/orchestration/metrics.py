"""Agregación de trazas de varios análisis: latencia y coste medios para la sección de viabilidad."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import mean

from finlens.domain.cost import CURRENCY, Tariffs
from finlens.orchestration.pipeline import AnalysisResult, MediaResult
from finlens.orchestration.trace import TraceStep


@dataclass(frozen=True)
class RunRecord:
    """Una ejecución medida: sus pasos y los tiempos de cada fase."""

    name: str
    steps: tuple[TraceStep, ...]
    report_seconds: float  # hasta tener el informe saneado en pantalla
    total_seconds: float  # incluye audio e infografía

    @classmethod
    def from_results(cls, name: str, analysis: AnalysisResult, media: MediaResult) -> RunRecord:
        return cls(
            name,
            (*analysis.trace, *media.trace),
            analysis.total_seconds,
            analysis.total_seconds + media.total_seconds,
        )


@dataclass(frozen=True)
class StepStats:
    """Estadísticas de un paso a través de todas las ejecuciones."""

    step: str
    model: str
    mean_seconds: float
    max_seconds: float
    mean_cost: float
    mean_tokens_in: float
    mean_tokens_out: float
    mean_quantity: float
    unit: str
    runs_ok: int
    runs_failed: int


@dataclass(frozen=True)
class Summary:
    """Resumen de N ejecuciones."""

    n_runs: int
    steps: tuple[StepStats, ...]
    mean_report_seconds: float
    max_report_seconds: float
    mean_total_seconds: float
    max_total_seconds: float
    mean_cost: float

    def step(self, name: str) -> StepStats | None:
        return next((s for s in self.steps if s.step == name), None)


def summarize(records: Sequence[RunRecord]) -> Summary:
    """Agrega las ejecuciones. Las medias de cada paso cuentan solo las ejecuciones donde corrió."""
    if not records:
        raise ValueError("No hay ejecuciones que resumir.")
    por_paso: dict[str, list[TraceStep]] = {}
    for registro in records:
        for paso in registro.steps:
            por_paso.setdefault(paso.step, []).append(paso)

    estadisticas = []
    for nombre, pasos in por_paso.items():
        correctos = [p for p in pasos if p.ok]
        base = correctos or pasos
        estadisticas.append(
            StepStats(
                step=nombre,
                model=next((p.model for p in correctos), "—"),
                mean_seconds=mean(p.seconds for p in base),
                max_seconds=max(p.seconds for p in base),
                mean_cost=mean(p.cost_usd for p in base),
                mean_tokens_in=mean(p.tokens_in for p in base),
                mean_tokens_out=mean(p.tokens_out for p in base),
                mean_quantity=mean(p.quantity for p in base),
                unit=next((p.unit for p in base if p.unit), ""),
                runs_ok=len(correctos),
                runs_failed=len(pasos) - len(correctos),
            )
        )
    informe = [r.report_seconds for r in records]
    total = [r.total_seconds for r in records]
    return Summary(
        n_runs=len(records),
        steps=tuple(estadisticas),
        mean_report_seconds=mean(informe),
        max_report_seconds=max(informe),
        mean_total_seconds=mean(total),
        max_total_seconds=max(total),
        mean_cost=mean(sum(p.cost_usd for p in r.steps) for r in records),
    )


def _componentes(resumen: Summary) -> list[tuple[str, str, float]]:
    """Filas (componente, uso medio, coste medio) en el formato de la tabla del README."""
    con_tokens = [s for s in resumen.steps if s.mean_tokens_in or s.mean_tokens_out]
    filas = [
        (
            "LLM (tokens ent./sal.)",
            f"{sum(s.mean_tokens_in for s in con_tokens):,.0f} / "
            f"{sum(s.mean_tokens_out for s in con_tokens):,.0f}",
            sum(s.mean_cost for s in con_tokens),
        )
    ]
    for etiqueta, paso, unidad in (
        ("STT", "Transcripción de audio", "min"),
        ("TTS", "Resumen en audio", "caracteres"),
        ("Imagen", "Generación de infografía", "imagen"),
    ):
        stats = resumen.step(paso)
        if stats is None:
            filas.append((etiqueta, "no ejecutado", 0.0))
            continue
        cantidad = stats.mean_quantity / 60 if unidad == "min" else stats.mean_quantity
        filas.append((etiqueta, f"{cantidad:,.1f} {unidad}", stats.mean_cost))
    return filas


def to_markdown(
    resumen: Summary,
    *,
    demo: bool,
    models: Mapping[str, str],
    tariffs: Tariffs,
    date: str,
) -> str:
    """Informe en Markdown listo para pegar en el README (sección de viabilidad)."""
    lineas = [f"# Mediciones de FinLens ({date})", ""]
    if demo:
        lineas += [
            "> ⚠️ **MODO DEMO: proveedores simulados. Estas cifras NO son válidas para el README.**",
            "> Repite la medición con claves reales.",
            "",
        ]
    lineas += [
        f"Ejecuciones medidas: **{resumen.n_runs}**. Modelos: "
        + ", ".join(f"{k}=`{v}`" for k, v in models.items()),
        "",
        f"Tarifas aplicadas ({CURRENCY}, orientativas; verificar en las páginas oficiales): "
        f"LLM {tariffs.llm_input_per_mtok}/{tariffs.llm_output_per_mtok} por millón de tokens "
        f"(entrada/salida), STT {tariffs.stt_per_minute}/min, TTS {tariffs.tts_per_mchar} por "
        f"millón de caracteres, imagen {tariffs.image_per_unit}/unidad.",
        "",
        f"## Coste medio por análisis ({CURRENCY})",
        "",
        "| Componente | Uso medio | Coste |",
        "|---|---|---|",
    ]
    lineas += [f"| {c} | {uso} | {coste:.4f} |" for c, uso, coste in _componentes(resumen)]
    lineas += [f"| **Total** | | **{resumen.mean_cost:.4f}** |", "", "## Latencia por paso (s)", ""]
    lineas += ["| Paso | Modelo | Media | Máx. | Fallos |", "|---|---|---|---|---|"]
    lineas += [
        f"| {s.step} | {s.model} | {s.mean_seconds:.2f} | {s.max_seconds:.2f} | {s.runs_failed} |"
        for s in resumen.steps
    ]
    lineas += [
        "",
        f"- **Informe en pantalla** (ingesta → guardrails): media {resumen.mean_report_seconds:.2f} s, "
        f"máx. {resumen.max_report_seconds:.2f} s.",
        f"- **Todo, incluidos audio e infografía**: media {resumen.mean_total_seconds:.2f} s, "
        f"máx. {resumen.max_total_seconds:.2f} s.",
        "- Visión y STT se ejecutan en paralelo, y también TTS e infografía; "
        "por eso los tiempos por paso no suman el total.",
    ]
    return "\n".join(lineas) + "\n"
