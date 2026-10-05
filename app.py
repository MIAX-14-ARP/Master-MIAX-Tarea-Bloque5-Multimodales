"""Entrada de Streamlit de FinLens. Solo UI: la lógica vive en src/finlens."""
import sys
from pathlib import Path

# Permite ejecutar `streamlit run app.py` sin instalar el paquete.
sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st  # noqa: E402

from finlens.config import Settings, get_settings  # noqa: E402
from finlens.domain.cost import Tariffs  # noqa: E402
from finlens.orchestration.cache import AnalysisCache, cache_key  # noqa: E402
from finlens.orchestration.pipeline import (  # noqa: E402
    AnalysisInput,
    PipelineError,
    analyze,
    answer_followup,
    generate_media,
)
from finlens.orchestration.trace import TraceStep  # noqa: E402
from finlens.providers.base import Message, Providers, ProviderError  # noqa: E402
from finlens.providers.registry import build_mock_providers, build_providers  # noqa: E402
from finlens.ui import views  # noqa: E402
from finlens.ui.demo_samples import (  # noqa: E402
    DEMO_QUESTION,
    demo_audio_wav,
    demo_chart_png,
    demo_pdf,
)


def load_providers(settings: Settings) -> tuple[Providers, str | None]:
    """Proveedores configurados; si no están disponibles, cae a modo demo con un aviso."""
    try:
        return build_providers(settings), None
    except ProviderError as exc:
        return build_mock_providers(), f"{exc} Se usa el modo demo."


def read_inputs(demo: bool) -> tuple[AnalysisInput | None, bool, tuple[bool, bool]]:
    """Formulario de entrada. Devuelve (entrada, pulsó_analizar, (con_audio, con_infografía))."""
    st.subheader("1. Materiales")
    usar_ejemplos = demo and st.checkbox(
        "Usar materiales de ejemplo ficticios (informe, gráfico y audio)", value=True
    )
    pdf = chart = audio = None
    if usar_ejemplos:
        st.caption("Informe anual ficticio de 4 páginas, gráfico de velas y audio de demostración.")
    else:
        columnas = st.columns(3)
        pdf = columnas[0].file_uploader("Informe (PDF)", type=["pdf"])
        chart = columnas[1].file_uploader("Gráfico de cotización", type=["png", "jpg", "jpeg"])
        audio = columnas[2].file_uploader("Audio", type=["wav", "mp3", "m4a", "ogg", "webm"])

    rol = st.radio(
        "El audio es…", ["conferencia", "pregunta"], horizontal=True,
        format_func=lambda r: "la conferencia de resultados" if r == "conferencia" else "mi pregunta por voz",
    )
    pregunta = st.text_area(
        "Pregunta", value=DEMO_QUESTION if usar_ejemplos else "",
        placeholder="Déjala vacía para un resumen general.",
    )
    columnas = st.columns(2)
    con_audio = columnas[0].checkbox("Generar resumen en audio", value=True)
    con_imagen = columnas[1].checkbox("Generar infografía", value=True, help="Con APIs reales cada imagen tiene coste.")
    pulsado = st.button("Analizar", type="primary")

    if usar_ejemplos:
        entrada = AnalysisInput(
            pdf=demo_pdf(), question=pregunta, chart=demo_chart_png(),
            chart_mime="image/png", audio=demo_audio_wav(), audio_name="demo.wav", audio_role=rol,
        )
    elif pdf is not None:
        entrada = AnalysisInput(
            pdf=pdf.getvalue(), question=pregunta,
            chart=chart.getvalue() if chart else None, chart_mime=chart.type if chart else "image/png",
            audio=audio.getvalue() if audio else None, audio_name=audio.name if audio else "audio",
            audio_role=rol,
        )
    else:
        entrada = None
    return entrada, pulsado, (con_audio, con_imagen)


def run_analysis(
    entrada: AnalysisInput,
    providers: Providers,
    tariffs: Tariffs,
    settings: Settings,
    medios: tuple[bool, bool],
) -> None:
    """Ejecuta (o recupera de caché) el análisis y guarda el resultado en la sesión."""
    cache: AnalysisCache = st.session_state.setdefault("cache", AnalysisCache())
    clave = cache_key(entrada, demo=providers.is_demo, max_pdf_chars=settings.max_pdf_chars)
    st.session_state.update(
        error=None, chat=[], chat_trace=[], clave=clave, desde_cache=False, pedidos=medios
    )

    resultado = cache.get_analysis(clave)
    if resultado is not None:
        st.session_state.update(result=resultado, media=cache.get_media(clave, *medios), desde_cache=True)
        return
    try:
        with st.spinner("Analizando informe, gráfico y audio…"):
            resultado = analyze(providers, tariffs, entrada, max_pdf_chars=settings.max_pdf_chars)
    except PipelineError as exc:
        st.session_state.update(result=None, media=None, error=exc)
        return
    cache.put_analysis(clave, resultado)
    st.session_state.update(result=resultado, media=None)


def chat_tab(providers: Providers, tariffs: Tariffs) -> None:
    """Chat de seguimiento con el contexto del informe."""
    result = st.session_state.result
    pregunta = st.chat_input("Pregunta de seguimiento sobre el informe")
    if pregunta:
        historial = [Message(m["role"], m["content"]) for m in st.session_state.chat]
        try:
            with st.spinner("Pensando…"):
                respuesta = answer_followup(providers, tariffs, result, historial, pregunta)
            st.session_state.chat += [
                {"role": "user", "content": pregunta, "citations": ""},
                {
                    "role": "assistant", "content": respuesta.answer.answer,
                    "citations": views.citations_text(respuesta.answer.citations),
                },
            ]
            st.session_state.chat_trace.append(respuesta.step)
        except PipelineError as exc:
            st.session_state.chat_trace.extend(exc.trace)
            st.error(exc.message)
    if not st.session_state.chat:
        st.caption("Aún no hay preguntas. Escribe abajo para seguir investigando el informe.")
    for mensaje in st.session_state.chat:
        with st.chat_message(mensaje["role"]):
            st.write(mensaje["content"])
            if mensaje["citations"]:
                st.caption(f"Fuentes: {mensaje['citations']}")
    views.show_disclaimer()


def show_results(providers: Providers, tariffs: Tariffs, settings: Settings) -> None:
    """Pestañas de resultados; el informe se pinta antes de generar audio e infografía."""
    result = st.session_state.result
    if st.session_state.desde_cache:
        st.info("Resultado recuperado de la caché: no se han repetido llamadas a los modelos.")
    views.show_warnings(result.warnings)

    media = st.session_state.media
    pestanas = st.tabs(["Informe", "Entradas leídas", "Audio e infografía", "Chat", "Traza de modelos"])
    with pestanas[0]:
        views.show_report(result.guard)
    with pestanas[1]:
        views.show_inputs_read(result)
    with pestanas[2]:
        views.show_media(media)
    with pestanas[3]:
        chat_tab(providers, tariffs)
    with pestanas[4]:
        pasos: list[TraceStep] = [*result.trace, *(media.trace if media else ()), *st.session_state.chat_trace]
        tiempo = result.total_seconds + (media.total_seconds if media else 0.0)
        views.show_trace(pasos, tiempo)

    if media is None:  # render progresivo: el informe ya está en pantalla
        with st.spinner("Generando audio e infografía…"):
            con_audio, con_imagen = st.session_state.pedidos
            media = generate_media(
                providers, tariffs, result, with_audio=con_audio, with_image=con_imagen
            )
        cache: AnalysisCache = st.session_state.cache
        cache.put_media(st.session_state.clave, media, *st.session_state.pedidos)
        st.session_state.media = media
        st.rerun()


def main() -> None:
    """Pantalla principal de FinLens."""
    settings = get_settings()
    providers, aviso = load_providers(settings)
    tariffs = Tariffs.from_settings(settings)

    st.set_page_config(page_title="FinLens", page_icon="🔎", layout="wide")
    st.title("FinLens")
    st.caption("Análisis multimodal de informes financieros: PDF, gráfico y audio en un solo informe citado.")
    if aviso:
        st.warning(aviso)
    if providers.is_demo:
        st.warning(f"Modo demo: se usan respuestas simuladas. {settings.demo_reason or ''}".strip())
    else:
        st.success("APIs reales configuradas.")
    st.caption("Tus documentos se procesan en esta sesión y no se almacenan; en modo real se envían a los proveedores de IA.")

    entrada, pulsado, medios = read_inputs(providers.is_demo)
    if pulsado:
        if entrada is None:
            st.error("Sube al menos el informe en PDF para analizar.")
        else:
            run_analysis(entrada, providers, tariffs, settings, medios)

    error: PipelineError | None = st.session_state.get("error")
    if error:
        st.error(error.message)
        if error.trace:
            st.caption("Pasos ejecutados antes del fallo:")
            views.show_trace(error.trace, sum(s.seconds for s in error.trace))
    elif st.session_state.get("result"):
        st.divider()
        show_results(providers, tariffs, settings)


main()
