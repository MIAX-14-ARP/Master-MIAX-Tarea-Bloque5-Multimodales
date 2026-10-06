"""Entrada de Streamlit de FinLens. Solo UI: la lógica vive en src/finlens."""
import base64
import dataclasses
import hmac
import logging
import os
import sys
from datetime import date
from pathlib import Path

# Permite ejecutar `streamlit run app.py` sin instalar el paquete.
sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st  # noqa: E402

from finlens.config import Settings, get_settings  # noqa: E402
from finlens.domain.cost import Tariffs  # noqa: E402
from finlens.logging_config import configure_logging  # noqa: E402
from finlens.orchestration.cache import AnalysisCache, cache_key  # noqa: E402
from finlens.orchestration.pipeline import (  # noqa: E402
    AnalysisInput,
    AnalysisResult,
    MediaResult,
    PipelineError,
    analyze,
    answer_followup,
    generate_media,
)
from finlens.orchestration.trace import TraceStep, total_cost  # noqa: E402
from finlens.providers.base import Message, ProviderError, Providers  # noqa: E402
from finlens.providers.registry import build_mock_providers, build_providers  # noqa: E402
from finlens.ui import brain, pipeline_map, theme, views  # noqa: E402
from finlens.ui import components as ui  # noqa: E402
from finlens.ui.demo_samples import (  # noqa: E402
    DEMO_QUESTION,
    demo_audio_wav,
    demo_chart_png,
    demo_pdf,
)
from finlens.ui.live import run_live  # noqa: E402

log = logging.getLogger("finlens.app")

_MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
SUGERENCIAS = (
    "¿Qué riesgos o limitaciones señala el informe?",
    "¿Cuál fue el margen operativo y con qué fuente?",
    "¿Qué dijo la dirección sobre la guía?",
)
HAS_COMPOSE = "illustration" in {f.name for f in dataclasses.fields(MediaResult)}
# Datos de mercado (spec 06 §10): la UI se activa sola cuando el backend añade `ticker` a AnalysisInput.
MARKET = "ticker" in {f.name for f in dataclasses.fields(AnalysisInput)}
DEMO_TICKER = "ACME"
RANGOS = {"1mo": "1 mes", "3mo": "3 meses", "6mo": "6 meses", "1y": "1 año", "2y": "2 años"}


def load_providers(settings: Settings) -> tuple[Providers, str | None]:
    """Proveedores configurados; si no están disponibles, cae a modo demo con un aviso."""
    try:
        return build_providers(settings), None
    except ProviderError as exc:
        log.warning("Proveedores no disponibles; se usa el modo demo")
        return build_mock_providers(), f"{exc} Se usa el modo demo."


# --- §1 Materiales --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Formulario:
    """Lo que el usuario ha preparado en §1."""

    entrada: AnalysisInput | None
    pulsado: bool
    medios: tuple[bool, bool]
    omitidos: frozenset[str]
    aportes: frozenset[str]


def _ranura_mercado(usar_ejemplos: bool) -> tuple[str, str]:
    """Ranura D: ticker (acciones vía Yahoo + SEC, cripto vía Hyperliquid) y rango."""
    ticker = st.text_input(
        "Ticker", value=DEMO_TICKER if usar_ejemplos else "", placeholder="ITX.MC · AAPL · BTC",
        label_visibility="collapsed", max_chars=20,
    ).strip().upper()
    rango = st.selectbox("Rango", list(RANGOS), index=2, format_func=RANGOS.get, label_visibility="collapsed")
    views.html(ui.slot("D", "Mercado", "Ticker: datos reales, técnicos y SEC · opcional",
                       nombre=f"{ticker} · {RANGOS[rango]}" if ticker else None, ejemplo=usar_ejemplos and bool(ticker)))
    return ticker, rango


def read_inputs(providers: Providers) -> Formulario:
    """Formulario en ranuras (A informe, B gráfico, C audio y, si hay datos de mercado, D ticker)."""
    obligatorio = "informe en PDF o ticker: al menos uno" if MARKET else "solo el informe en PDF es obligatorio"
    views.html(ui.section("1", "Materiales", obligatorio))
    usar_ejemplos = st.toggle(
        "Usar materiales de ejemplo (ficticios: informe, gráfico de velas y audio)",
        value=providers.is_demo,
        help="Informe anual ficticio de ACME Corp (4 páginas), gráfico de velas y audio de demostración.",
    )
    columnas = st.columns(4 if MARKET else 3, gap="medium" if MARKET else "large")
    col_a, col_b, col_c = columnas[:3]
    pdf = chart = audio = grabacion = None
    ticker, rango = "", "6mo"
    with col_a:
        if usar_ejemplos:
            views.html(ui.slot("A", "Informe anual", "PDF con texto", nombre="acme_informe_2025.pdf", ejemplo=True))
        else:
            pdf = st.file_uploader("Informe (PDF)", type=["pdf"], label_visibility="collapsed")
            views.html(ui.slot("A", "Informe anual", "PDF con texto" + ("" if MARKET else " · obligatorio"),
                               nombre=pdf.name if pdf else None, tamano=pdf.size if pdf else None,
                               vacio="pendiente" if MARKET else "pendiente · obligatorio"))
    with col_b:
        if usar_ejemplos:
            miniatura = base64.b64encode(demo_chart_png()).decode()
            views.html(ui.slot("B", "Gráfico de cotización", "Velas japonesas · PNG o JPG", nombre="velas_acme.png", ejemplo=True)
                       + f'<img class="fl-thumb" src="data:image/png;base64,{miniatura}" alt="Gráfico de velas de ejemplo">')
        else:
            chart = st.file_uploader("Gráfico de cotización", type=["png", "jpg", "jpeg"], label_visibility="collapsed")
            detalle = "Velas japonesas · opcional" + (" (con ticker se genera)" if MARKET else "")
            views.html(ui.slot("B", "Gráfico de cotización", detalle,
                               nombre=chart.name if chart else None, tamano=chart.size if chart else None))
    with col_c:
        rol = "conferencia"
        if usar_ejemplos:
            views.html(ui.slot("C", "Audio", "Earnings call o pregunta por voz", nombre="call_demo.wav", ejemplo=True))
        else:
            modos = ["Subir archivo", "Grabar pregunta"] if hasattr(st, "audio_input") else ["Subir archivo"]
            modo = st.radio("Origen del audio", modos, horizontal=True, label_visibility="collapsed")
            if modo == "Grabar pregunta":
                grabacion = st.audio_input("Graba tu pregunta", label_visibility="collapsed")
                rol = "pregunta"
            else:
                audio = st.file_uploader("Audio", type=["wav", "mp3", "m4a", "ogg", "webm"], label_visibility="collapsed")
            fuente = grabacion or audio
            views.html(ui.slot("C", "Audio", "Earnings call o pregunta por voz · opcional",
                               nombre=fuente.name if fuente else None, tamano=fuente.size if fuente else None))
        if grabacion is None:
            rol = st.radio(
                "El audio es…", ["conferencia", "pregunta"], horizontal=True,
                format_func=lambda r: "la conferencia de resultados" if r == "conferencia" else "mi pregunta por voz",
            )
    if MARKET:
        with columnas[3]:
            ticker, rango = _ranura_mercado(usar_ejemplos)

    pregunta = st.text_area(
        "Tu pregunta al informe", value=DEMO_QUESTION if usar_ejemplos else "",
        placeholder="Déjala vacía para un resumen general, o grábala por voz en la ranura C.",
    )
    op1, op2, boton = st.columns([1, 1, 1], vertical_alignment="center")
    con_audio = op1.toggle("Generar resumen en audio", value=True)
    con_imagen = op2.toggle("Generar infografía", value=True, help="Con APIs reales cada imagen tiene coste.")
    pulsado = boton.button("Analizar", type="primary", width="stretch")

    mercado = {"ticker": ticker, "market_range": rango} if MARKET else {}
    fuente = grabacion or audio
    if usar_ejemplos:
        entrada: AnalysisInput | None = AnalysisInput(
            pdf=demo_pdf(), question=pregunta, chart=demo_chart_png(),
            chart_mime="image/png", audio=demo_audio_wav(), audio_name="demo.wav", audio_role=rol, **mercado,
        )
    elif pdf is not None or ticker:
        entrada = AnalysisInput(
            pdf=pdf.getvalue() if pdf else b"", question=pregunta,
            chart=chart.getvalue() if chart else None, chart_mime=chart.type if chart else "image/png",
            audio=fuente.getvalue() if fuente else None,
            audio_name=(fuente.name or "pregunta.wav") if fuente else "audio", audio_role=rol, **mercado,
        )
    else:
        entrada = None

    aportes = set()
    if entrada is not None:
        aportes |= {k for k, v in (("pdf", entrada.pdf), ("chart", entrada.chart), ("audio", entrada.audio)) if v}
    if pregunta.strip() or rol == "pregunta":
        aportes.add("question")
    if ticker:
        aportes |= {"ticker", "sec"}
    omitidos = set()
    if entrada is not None:
        if entrada.chart is None and not ticker:
            omitidos.add("vision")
        if entrada.audio is None:
            omitidos.add("stt")
        if not ticker:
            omitidos |= set(pipeline_map.MARKET_NODES)
        if not entrada.pdf:
            omitidos |= {"ingest", "retrieve"}
    if not con_audio:
        omitidos.add("tts")
    if not con_imagen:
        omitidos.update({"prompt", "image", "compose"})
    return Formulario(entrada, pulsado, (con_audio, con_imagen), frozenset(omitidos), frozenset(aportes))


# --- §2 Cadena de modelos -------------------------------------------------------------------


def render_map(lugar, providers: Providers, *, steps1=None, steps2=None, live=None, live_phase=None,
               headline: str = "", en_vivo: bool = False) -> None:
    vistas = pipeline_map.build_nodes(
        pipeline_map.provider_info(providers), pipeline_map.mock_capabilities(providers),
        steps1=steps1, steps2=steps2, live=live, live_phase=live_phase,
        skipped=st.session_state.get("omitidos", frozenset()),
    )
    lugar.markdown(
        pipeline_map.map_html(vistas, headline=headline, live=en_vivo, with_compose=HAS_COMPOSE, with_market=MARKET),
        unsafe_allow_html=True,
    )


def _resumen_traza(pasos: list[TraceStep], segundos: float) -> str:
    fallos = sum(1 for p in pasos if not p.ok)
    texto = f"{len(pasos)} pasos · {segundos:.2f} s · {total_cost(pasos):.4f} USD"
    return texto + (f" · {fallos} fallo(s)" if fallos else "")


def run_analysis(entrada: AnalysisInput, providers: Providers, tariffs: Tariffs, settings: Settings,
                 medios: tuple[bool, bool], mapa) -> None:
    """Ejecuta (o recupera de caché) el análisis con el mapa en vivo y guarda el resultado."""
    cache: AnalysisCache = st.session_state.setdefault("cache", AnalysisCache())
    clave = cache_key(entrada, demo=providers.is_demo, max_pdf_chars=settings.max_pdf_chars)
    st.session_state.update(error=None, chat=[], chat_trace=[], clave=clave, desde_cache=False, pedidos=medios)

    resultado = cache.get_analysis(clave)
    if resultado is not None:
        st.session_state.update(result=resultado, media=cache.get_media(clave, *medios), desde_cache=True)
        return

    def tick(live: dict[str, str], segundos: float) -> None:
        render_map(mapa, providers, live=live, live_phase=1, en_vivo=True,
                   headline=f"Fase I · análisis en curso · {segundos:.1f} s")

    try:
        resultado = run_live(
            lambda p: analyze(p, tariffs, entrada, max_pdf_chars=settings.max_pdf_chars), providers, tick
        )
    except PipelineError as exc:
        log.info("Análisis interrumpido: %s", exc.message)
        st.session_state.update(result=None, media=None, error=exc)
        return
    cache.put_analysis(clave, resultado)
    st.session_state.update(result=resultado, media=None)


# --- §3 Nota: chat --------------------------------------------------------------------------


def chat_tab(providers: Providers, tariffs: Tariffs) -> None:
    """Chat de seguimiento con el contexto del informe y citas como chips."""
    result: AnalysisResult = st.session_state.result
    views.html('<p class="fl-q">Pregunta al informe: las respuestas citan documento, gráfico o audio, '
               "y dicen cuándo no hay base en los materiales.</p>")
    sugeridas = st.columns(len(SUGERENCIAS))
    pregunta = None
    for col, texto in zip(sugeridas, SUGERENCIAS, strict=True):
        if col.button(texto, width="stretch"):
            pregunta = texto
    escrita = st.chat_input("Pregunta de seguimiento sobre el informe")
    pregunta = escrita or pregunta
    if pregunta:
        historial = [Message(m["role"], m["content"]) for m in st.session_state.chat]
        try:
            with st.spinner("Consultando el informe…"):
                respuesta = answer_followup(providers, tariffs, result, historial, pregunta)
            st.session_state.chat += [
                {"role": "user", "content": pregunta, "citations": "", "chips": ""},
                {
                    "role": "assistant", "content": respuesta.answer.answer,
                    "citations": views.citations_text(respuesta.answer.citations),
                    "chips": ui.chips(respuesta.answer.citations),
                    "grounded": respuesta.answer.grounded,
                },
            ]
            st.session_state.chat_trace.append(respuesta.step)
        except PipelineError as exc:
            st.session_state.chat_trace.extend(exc.trace)
            views.html(ui.editor_note(exc.message, error=True, titulo="El chat no pudo responder"))
    if not st.session_state.chat:
        views.html('<p class="fl-empty">Aún no hay preguntas. Elige una sugerida o escribe abajo.</p>')
    for mensaje in st.session_state.chat:
        avatar = ":material/person:" if mensaje["role"] == "user" else ":material/query_stats:"
        with st.chat_message(mensaje["role"], avatar=avatar):
            extra = ""
            if mensaje["role"] == "assistant":
                base = "" if mensaje.get("grounded", True) else '<span class="fl-stamp s">sin base en los materiales</span> '
                extra = f'<div class="fl-find__c">{base}{mensaje.get("chips", "")}</div>'
            views.html(f'<div class="fl-find__s">{ui.esc(mensaje["content"])}</div>{extra}')
    views.show_disclaimer()


# --- Resultados -----------------------------------------------------------------------------


def show_results(providers: Providers, tariffs: Tariffs, mapa) -> None:
    """Mapa final + pestañas; el informe se pinta antes de generar audio e infografía."""
    result: AnalysisResult = st.session_state.result
    media: MediaResult | None = st.session_state.media
    pasos = [*result.trace, *(media.trace if media else ())]
    segundos = result.total_seconds + (media.total_seconds if media else 0.0)
    titular = _resumen_traza(pasos, segundos)
    if st.session_state.desde_cache:
        titular = "Recuperado de la caché: 0 llamadas nuevas a modelos · " + titular
    render_map(mapa, providers, steps1=result.trace, steps2=media.trace if media else None, headline=titular,
               live=None if media else {}, live_phase=None if media else 2, en_vivo=media is None)

    views.html(ui.section("3", "Nota de análisis", "fuentes citadas en cada afirmación"))
    views.show_warnings(result.warnings)
    mercado = getattr(result, "market", None)
    nombres = ["Informe", "Entradas leídas", *(["Mercado"] if mercado is not None else []),
               "Audio e infografía", "Chat", "Traza de modelos"]
    pestanas = dict(zip(nombres, st.tabs(nombres), strict=True))
    with pestanas["Informe"]:
        views.show_report(result)
    with pestanas["Entradas leídas"]:
        views.show_inputs_read(result)
    if mercado is not None:
        with pestanas["Mercado"]:
            views.show_market(mercado)
    with pestanas["Audio e infografía"]:
        views.show_media(media, result.report.spoken_summary)
    with pestanas["Chat"]:
        chat_tab(providers, tariffs)
    with pestanas["Traza de modelos"]:
        todos: list[TraceStep] = [*pasos, *st.session_state.chat_trace]
        views.show_trace(todos, segundos)

    if media is None:  # render progresivo: el informe ya está en pantalla
        con_audio, con_imagen = st.session_state.pedidos

        def tick(live: dict[str, str], t: float) -> None:
            render_map(mapa, providers, steps1=result.trace, live=live, live_phase=2, en_vivo=True,
                       headline=f"Fase II · audio e infografía en curso · {t:.1f} s")

        media = run_live(
            lambda p: generate_media(p, tariffs, result, with_audio=con_audio, with_image=con_imagen),
            providers, tick,
        )
        cache: AnalysisCache = st.session_state.cache
        cache.put_media(st.session_state.clave, media, *st.session_state.pedidos)
        st.session_state.media = media
        st.rerun()


def show_brain(providers: Providers, form: Formulario) -> None:
    """§0: reposo con las entradas elegidas; reproducción de la traza cuando hay informe y medios."""
    result = st.session_state.get("result")
    media = st.session_state.get("media")
    replay = result is not None and media is not None and not st.session_state.get("error")
    datos = brain.build_brain(
        providers, aportes=st.session_state.get("aportes", form.aportes) if replay else form.aportes,
        result=result if replay else None, media=media if replay else None,
        with_market=MARKET, with_compose=HAS_COMPOSE,
    )
    brain.render(datos)


def access_granted() -> bool:
    """Contraseña de la demo pública (APP_PASSWORD). Sin ella definida, el acceso es libre (uso local)."""
    esperada = os.environ.get("APP_PASSWORD", "")
    if not esperada or st.session_state.get("acceso_ok"):
        return True
    views.html(ui.editor_note(
        "Demo privada: cada análisis consume crédito de APIs reales. Introduce la contraseña de acceso.",
        titulo="Acceso",
    ))
    with st.form("acceso"):
        clave = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            if hmac.compare_digest(clave.encode(), esperada.encode()):
                st.session_state.acceso_ok = True
                st.rerun()
            st.error("Contraseña incorrecta.")
    return False


def main() -> None:
    """Pantalla principal de FinLens."""
    st.set_page_config(page_title="FinLens · research multimodal", page_icon=":material/query_stats:",
                       layout="wide")
    theme.inject()
    if not access_granted():
        return
    settings = get_settings()
    configure_logging(settings.log_level)
    providers, aviso = load_providers(settings)
    tariffs = Tariffs.from_settings(settings)

    hoy = date.today()
    views.html(ui.masthead(
        f"{hoy.day} {_MESES[hoy.month - 1]} {hoy.year}",
        pipeline_map.provider_info(providers), pipeline_map.mock_capabilities(providers), aviso,
    ))
    for degradada in providers.warnings:  # capacidades que caen a simulado por configuración
        views.html(ui.editor_note(degradada, titulo="Proveedor"))

    views.html(ui.section("0", "Cerebro", "la red de modelos de esta sesión"))
    lienzo = st.container()
    form = read_inputs(providers)
    entrada, pulsado, medios, omitidos = form.entrada, form.pulsado, form.medios, form.omitidos
    with lienzo:
        show_brain(providers, form)
    if pulsado and entrada is None:
        falta = "Sube al menos el informe en PDF (ranura A)" + (" o indica un ticker (ranura D)" if MARKET else "")
        views.html(ui.editor_note(falta + " para analizar.", error=True, titulo="Falta material"))

    activo = (pulsado and entrada is not None) or st.session_state.get("result") or st.session_state.get("error")
    if not activo:
        return
    views.html(ui.section("2", "Cadena de modelos", "proveedor y modelo reales de cada paso"))
    mapa = st.empty()
    if pulsado and entrada is not None:
        st.session_state.omitidos = omitidos
        st.session_state.aportes = form.aportes
        run_analysis(entrada, providers, tariffs, settings, medios, mapa)

    error: PipelineError | None = st.session_state.get("error")
    if error:
        render_map(mapa, providers, steps1=error.trace, headline="Análisis interrumpido · " +
                   _resumen_traza(list(error.trace), sum(s.seconds for s in error.trace)))
        views.html(ui.editor_note(error.message, error=True, titulo="Análisis interrumpido"))
        if error.trace:
            views.show_trace(error.trace, sum(s.seconds for s in error.trace))
    elif st.session_state.get("result"):
        show_results(providers, tariffs, mapa)


main()
