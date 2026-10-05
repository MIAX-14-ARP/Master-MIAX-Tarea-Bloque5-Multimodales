"""Componentes de Streamlit para mostrar resultados. Sin lógica de negocio."""
from __future__ import annotations

from typing import Sequence

import streamlit as st

from finlens.domain.cost import CURRENCY
from finlens.domain.guardrails import DISCLAIMER, GuardrailResult
from finlens.domain.schemas import Citation, Finding
from finlens.orchestration.pipeline import AnalysisResult, MediaResult
from finlens.orchestration.trace import TraceStep, total_cost


def show_disclaimer() -> None:
    """Aviso legal y de contenido generado por IA (AI Act); se muestra en cada salida."""
    st.caption(f"⚠️ {DISCLAIMER} Contenido generado por IA; contrasta siempre las fuentes citadas.")


def citations_text(citations: Sequence[Citation]) -> str:
    return " · ".join(f"`{c.label}`" for c in citations)


def _show_findings(findings: Sequence[Finding]) -> None:
    for hallazgo in findings:
        st.markdown(f"- {hallazgo.statement}  \n  Fuentes: {citations_text(hallazgo.citations)}")


def show_warnings(warnings: Sequence[str]) -> None:
    for aviso in warnings:
        st.warning(aviso)


def show_report(guard: GuardrailResult) -> None:
    """Informe estructurado: resumen, cifras, gráfico, dirección y correlaciones, todo con fuentes."""
    informe = guard.report
    st.subheader("Resumen")
    st.write(informe.summary)

    if informe.key_figures:
        st.subheader("Cifras clave")
        st.table(
            [
                {
                    "Concepto": f.name, "Valor": f.value, "Periodo": f.period,
                    "Fuente": ", ".join(c.label for c in f.citations),
                }
                for f in informe.key_figures
            ]
        )
    if informe.chart_reading:
        st.subheader("Lectura del gráfico")
        _show_findings([informe.chart_reading])
    if informe.management_statements:
        st.subheader("Declaraciones de la dirección")
        _show_findings(informe.management_statements)
    if informe.correlations:
        st.subheader("Correlación entre modalidades")
        _show_findings(informe.correlations)
    if informe.limitations:
        st.subheader("Limitaciones")
        for limitacion in informe.limitations:
            st.markdown(f"- {limitacion}")
    show_disclaimer()


def show_inputs_read(result: AnalysisResult) -> None:
    """Lo que el sistema entendió de cada modalidad de entrada."""
    st.markdown(f"**Pregunta analizada:** {result.question}")
    st.markdown(
        f"**Documento:** {result.document.n_pages} páginas, {len(result.document.chunks)} fragmentos"
        + (" (truncado por el límite de entrada)" if result.document.truncated else "")
    )
    if result.chart:
        st.markdown(f"**Gráfico:** tendencia *{result.chart.trend}*. {result.chart.description}")
        for observacion in result.chart.observations:
            st.markdown(f"- {observacion}")
    else:
        st.markdown("**Gráfico:** no aportado o no se pudo leer.")
    if result.transcript:
        st.markdown("**Transcripción del audio:**")
        st.info(result.transcript)
    else:
        st.markdown("**Audio:** no aportado o no se pudo transcribir.")


def show_media(media: MediaResult | None) -> None:
    """Audio TTS e infografía; si un paso falló se avisa y el resto se muestra igualmente."""
    if media is None:
        st.info("Generando audio e infografía…")
        return
    show_warnings(media.warnings)
    st.subheader("Resumen en audio")
    if media.audio:
        st.audio(media.audio.audio, format=media.audio.mime)
    else:
        st.caption("No solicitado." if media.audio_skipped else "No disponible.")
    st.subheader("Infografía")
    if media.image:
        st.image(media.image.image, caption=media.image_prompt)
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
            "Estado": "✅" if s.ok else "❌",
            "Nota": s.note,
        }
        for s in steps
    ]


def show_trace(steps: Sequence[TraceStep], total_seconds: float) -> None:
    """Traza de modelos: la evidencia de la orquestación multimodal."""
    columnas = st.columns(3)
    columnas[0].metric("Pasos", len(steps))
    columnas[1].metric("Tiempo total (s)", f"{total_seconds:.2f}")
    columnas[2].metric(f"Coste estimado ({CURRENCY})", f"{total_cost(steps):.4f}")
    st.table(trace_rows(steps))
    st.caption(
        "⇉ = pasos ejecutados en paralelo. Los segundos son por paso (los paralelos se solapan); "
        "el coste usa tarifas orientativas configurables, a verificar en la documentación oficial."
    )
