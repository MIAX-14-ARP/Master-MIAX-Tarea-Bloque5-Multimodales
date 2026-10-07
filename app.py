"""Entrada de Streamlit de FinLens. Solo UI: la lógica vive en src/finlens."""
import base64
import dataclasses
import hmac
import logging
import os
import re
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
from finlens.sources.registry import PREFIJO_ACCION, PREFIJO_CRIPTO, build_sources  # noqa: E402
from finlens.ui import brain, pipeline_map, theme, views  # noqa: E402
from finlens.ui import components as ui  # noqa: E402
from finlens.ui.casos import FORMATOS, TICKERS_EJEMPLO, casos  # noqa: E402
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
PROPIO = "propio"
RANGOS = {"1mo": "1 mes", "3mo": "3 meses", "6mo": "6 meses", "1y": "1 año", "2y": "2 años"}
# Mercado del ticker: «Auto» deja decidir al registro; los otros fuerzan la fuente con su prefijo.
MERCADOS = {"Auto": "", "Cripto · Hyperliquid": PREFIJO_CRIPTO, "Acción · Yahoo + SEC": PREFIJO_ACCION}


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
    detalles: dict[str, str] = dataclasses.field(default_factory=dict)  # entrada → «1,5 MB», «BTC · 6 meses»…


def _tamano(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{max(1, round(n / 1024))} KB"


def _cab(lugar, fragmento: str) -> None:
    lugar.markdown(fragmento, unsafe_allow_html=True)


def _ranura_mercado(caso: str, ticker_caso: str) -> tuple[str, str, str]:
    """Ranura D: ticker (acciones vía Yahoo + SEC, cripto vía Hyperliquid), mercado y rango.

    El ticker se valida contra la fuente elegida: si no cotiza ahí, el paso «Datos de mercado» lo dice.
    """
    cab = st.empty()
    ticker = st.text_input(
        "Ticker", value=ticker_caso, placeholder="ITX.MC · AAPL · BTC",
        label_visibility="collapsed", max_chars=20, key=f"ticker_{caso}",
    ).strip().upper()
    mercado = st.radio(
        "Mercado", list(MERCADOS), horizontal=True, label_visibility="collapsed", key=f"mercado_{caso}",
        help="Auto: BTC, ETH… son cripto; un ticker de la SEC es acción; si no, Hyperliquid. "
        "Elige el mercado si el ticker existe en los dos (p. ej. BTC también es un ETF).",
    )
    rango = st.selectbox("Rango", list(RANGOS), index=2, format_func=RANGOS.get, label_visibility="collapsed",
                         key=f"rango_{caso}")
    etiqueta = f"{ticker} · {mercado} · {RANGOS[rango]}" if mercado != "Auto" else f"{ticker} · {RANGOS[rango]}"
    _cab(cab, ui.slot("D", "Mercado", "Ticker: datos reales, técnicos y SEC · opcional",
                       nombre=etiqueta if ticker else None, ejemplo=caso != PROPIO and bool(ticker)))
    return (MERCADOS[mercado] + ticker if ticker else ""), rango, f"{ticker} · {RANGOS[rango]}"


def _ayuda_materiales() -> None:
    """Formatos aceptados y descarga de los materiales de ejemplo (para probar con archivos propios)."""
    with st.expander("Formatos aceptados y materiales de ejemplo para descargar"):
        filas = "".join(f"<li><b>{ui.esc(k)}</b> {ui.esc(v)}</li>" for k, v in FORMATOS)
        views.html(f'<ul class="fl-formats">{filas}</ul><p class="fl-note-sm">Tickers de ejemplo: '
                   f'{ui.esc(" · ".join(TICKERS_EJEMPLO))}. Los archivos se procesan en esta sesión y no se guardan '
                   "en el servidor.</p>")
        for caso in casos().values():
            if not caso.archivos:
                continue
            columnas = st.columns([2, 1, 1, 1], vertical_alignment="center")
            columnas[0].markdown(f"**{caso.titulo}**")
            for col, archivo in zip(columnas[1:], caso.archivos, strict=False):
                tipo = {"application/pdf": "Informe PDF", "image/png": "Gráfico PNG"}.get(archivo.mime, "Audio")
                col.download_button(f"{tipo} · {_tamano(len(archivo.datos))}", archivo.datos, help=archivo.nombre,
                                    file_name=archivo.nombre, mime=archivo.mime, on_click="ignore",
                                    key=f"dl_{caso.clave}_{archivo.nombre}", width="stretch")


def _grabacion(grabacion) -> None:
    """La pregunta grabada: dónde va, escucharla y descargarla."""
    views.html('<p class="fl-note-sm">Tu grabación se usa solo como pregunta de este análisis: se transcribe y '
               "no se guarda en el servidor (se descarta al cerrar la pestaña).</p>")
    if grabacion is not None:
        st.audio(grabacion.getvalue(), format=grabacion.type or "audio/wav")
        st.download_button("Descargar grabación", grabacion.getvalue(), file_name="pregunta_finlens.wav",
                           mime=grabacion.type or "audio/wav", on_click="ignore", key="dl_grabacion")


def read_inputs(providers: Providers) -> Formulario:
    """Formulario en ranuras (A informe, B gráfico, C audio y, si hay datos de mercado, D ticker)."""
    obligatorio = "informe en PDF o ticker: al menos uno" if MARKET else "solo el informe en PDF es obligatorio"
    views.html(ui.section("1", "Materiales", obligatorio))
    opciones = [PROPIO, *casos()]
    caso_id = st.radio(
        "Empezar con", opciones, horizontal=True, index=opciones.index("ficticio") if providers.is_demo else 0,
        format_func=lambda c: "Mis archivos" if c == PROPIO else casos()[c].titulo, key="caso",
        help="Los casos de ejemplo precargan los materiales; con modelos reales también tienen coste.",
    )
    caso = casos().get(caso_id)
    if caso is not None:
        views.html(f'<p class="fl-case">{ui.esc(caso.descripcion)}</p>')
    _ayuda_materiales()

    columnas = st.columns(4 if MARKET else 3, gap="medium" if MARKET else "large")
    col_a, col_b, col_c = columnas[:3]
    pdf = chart = audio = grabacion = None
    ticker, rango, ticker_det = "", "6mo", ""
    with col_a:
        cab = st.empty()  # cabecera de la ranura encima de sus controles
        if caso is not None:
            _cab(cab, ui.slot("A", "Informe anual", "PDF con texto", nombre=caso.pdf.nombre if caso.pdf else None,
                               tamano=len(caso.pdf.datos) if caso.pdf else None, ejemplo=caso.pdf is not None,
                               vacio="no incluido en este caso"))
        else:
            pdf = st.file_uploader("Informe (PDF)", type=["pdf"], label_visibility="collapsed", max_upload_size=30)
            _cab(cab, ui.slot("A", "Informe anual", "PDF con texto seleccionable" + ("" if MARKET else " · obligatorio"),
                               nombre=pdf.name if pdf else None, tamano=pdf.size if pdf else None,
                               vacio="pendiente" if MARKET else "pendiente · obligatorio"))
    with col_b:
        cab = st.empty()  # cabecera de la ranura encima de sus controles
        if caso is not None:
            miniatura = ""
            if caso.chart is not None:
                b64 = base64.b64encode(caso.chart.datos).decode()
                miniatura = f'<img class="fl-thumb" src="data:image/png;base64,{b64}" alt="Gráfico de velas del caso">'
            _cab(cab, ui.slot("B", "Gráfico de cotización", "Velas japonesas · PNG o JPG",
                               nombre=caso.chart.nombre if caso.chart else None, ejemplo=caso.chart is not None,
                               vacio="se genera desde el ticker" if caso.ticker else "no incluido") + miniatura)
        else:
            chart = st.file_uploader("Gráfico de cotización", type=["png", "jpg", "jpeg"], label_visibility="collapsed",
                                     max_upload_size=10)
            detalle = "PNG o JPG · opcional" + (" (con ticker se genera)" if MARKET else "")
            _cab(cab, ui.slot("B", "Gráfico de cotización", detalle,
                               nombre=chart.name if chart else None, tamano=chart.size if chart else None))
    with col_c:
        cab = st.empty()  # cabecera de la ranura encima de sus controles
        rol = "conferencia"
        grabando = False
        if caso is not None:
            _cab(cab, ui.slot("C", "Audio", "Earnings call o pregunta por voz",
                               nombre=caso.audio.nombre if caso.audio else None, ejemplo=caso.audio is not None,
                               vacio="no incluido en este caso"))
            if caso.audio is not None:
                st.audio(caso.audio.datos, format=caso.audio.mime)
        else:
            modos = ["Subir archivo", "Grabar pregunta"] if hasattr(st, "audio_input") else ["Subir archivo"]
            modo = st.radio("Origen del audio", modos, horizontal=True, label_visibility="collapsed")
            grabando = modo == "Grabar pregunta"
            if grabando:
                grabacion = st.audio_input("Graba tu pregunta", label_visibility="collapsed")
                rol = "pregunta"
                _grabacion(grabacion)
            else:
                audio = st.file_uploader("Audio", type=["wav", "mp3", "m4a", "ogg", "webm"], label_visibility="collapsed",
                                         max_upload_size=25)
            fuente = grabacion or audio
            _cab(cab, ui.slot("C", "Audio", "WAV, MP3, M4A… · opcional",
                               nombre=fuente.name if fuente else None, tamano=fuente.size if fuente else None))
        if not grabando and (caso is None or caso.audio is not None):
            rol = st.radio(
                "El audio es…", ["conferencia", "pregunta"], horizontal=True,
                format_func=lambda r: "la conferencia de resultados" if r == "conferencia" else "mi pregunta por voz",
            )
    if MARKET:
        with columnas[3]:
            ticker, rango, ticker_det = _ranura_mercado(caso_id, caso.ticker if caso else "")

    pregunta = st.text_area(
        "Tu pregunta al informe", value=caso.question if caso else "", key=f"pregunta_{caso_id}",
        placeholder="Déjala vacía para un resumen general, o grábala por voz en la ranura C.",
    )
    op1, op2, boton = st.columns([1, 1, 1], vertical_alignment="center")
    con_audio = op1.toggle("Generar resumen en audio", value=True)
    con_imagen = op2.toggle("Generar infografía", value=True, help="Con APIs reales cada imagen tiene coste.")
    pulsado = boton.button("Analizar", type="primary", width="stretch")

    mercado = {"ticker": ticker, "market_range": rango} if MARKET else {}
    if caso is not None:
        pdf_b, chart_b = (caso.pdf.datos if caso.pdf else b""), (caso.chart.datos if caso.chart else None)
        chart_mime = caso.chart.mime if caso.chart else "image/png"
        audio_b, audio_nombre = (caso.audio.datos, caso.audio.nombre) if caso.audio else (None, "audio")
    else:
        fuente = grabacion or audio
        pdf_b, chart_b = (pdf.getvalue() if pdf else b""), (chart.getvalue() if chart else None)
        chart_mime = chart.type if chart else "image/png"
        audio_b = fuente.getvalue() if fuente else None
        audio_nombre = (fuente.name or "pregunta.wav") if fuente else "audio"
    entrada: AnalysisInput | None = None
    if pdf_b or ticker:
        entrada = AnalysisInput(pdf=pdf_b, question=pregunta, chart=chart_b, chart_mime=chart_mime, audio=audio_b,
                                audio_name=audio_nombre, audio_role=rol, **mercado)

    detalles: dict[str, str] = {}
    if pdf_b:
        detalles["pdf"] = _tamano(len(pdf_b))
    if chart_b:
        detalles["chart"] = _tamano(len(chart_b))
    if audio_b:
        detalles["audio"] = ("voz · " if rol == "pregunta" else "") + _tamano(len(audio_b))
    if pregunta.strip() or rol == "pregunta":
        detalles["question"] = f"{len(pregunta.strip())} car." if pregunta.strip() else "por voz"
    if ticker:
        detalles["ticker"] = ticker_det
        detalles["sec"] = "si cotiza en EE. UU."
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
    return Formulario(entrada, pulsado, (con_audio, con_imagen), frozenset(omitidos), frozenset(detalles), detalles)


# --- §2 Cadena de modelos -------------------------------------------------------------------


def render_map(lugar, providers: Providers, *, steps1=None, steps2=None, live=None, live_steps=(),
               live_phase=None, headline: str = "", en_vivo: bool = False) -> None:
    vistas = pipeline_map.build_nodes(
        pipeline_map.provider_info(providers), pipeline_map.mock_capabilities(providers),
        steps1=steps1, steps2=steps2, live=live, live_steps=live_steps, live_phase=live_phase,
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
    clave = cache_key(entrada, demo=providers.is_demo, max_pdf_chars=settings.max_pdf_chars,
                      providers_info=providers.info)
    st.session_state.update(error=None, chat=[], chat_trace=[], clave=clave, desde_cache=False, pedidos=medios)

    resultado = cache.get_analysis(clave)
    if resultado is not None:
        st.session_state.update(result=resultado, media=cache.get_media(clave, *medios), desde_cache=True)
        return

    def tick(en_curso: tuple[str, ...], hechos: tuple[TraceStep, ...], segundos: float) -> None:
        render_map(mapa, providers, live=en_curso, live_steps=hechos, live_phase=1, en_vivo=True,
                   headline=f"Fase I · análisis en curso · {segundos:.1f} s")

    fuentes = build_sources(demo=providers.is_demo, sec_user_agent=settings.sec_user_agent)
    try:
        resultado = run_live(
            lambda on_step: analyze(providers, tariffs, entrada, max_pdf_chars=settings.max_pdf_chars,
                                    on_step=on_step, sources=fuentes),
            tick,
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
               live=None if media else (), live_phase=None if media else 2, en_vivo=media is None)

    views.html(ui.section("3", "Nota de análisis", "fuentes citadas en cada afirmación"))
    pdf_nota(result, media)
    views.show_warnings(result.warnings)
    mercado = getattr(result, "market", None)
    nombres = ["Informe", "Entradas leídas", *(["Mercado"] if mercado is not None else []),
               "Audio e infografía", "Chat", "Traza de modelos"]
    pestanas = dict(zip(nombres, st.tabs(nombres), strict=True))
    with pestanas["Informe"]:
        views.show_report(result)
    with pestanas["Entradas leídas"]:
        views.show_inputs_read(result, voz=st.session_state.get("detalles", {}).get("audio", "").startswith("voz"))
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

        def tick(en_curso: tuple[str, ...], hechos: tuple[TraceStep, ...], t: float) -> None:
            render_map(mapa, providers, steps1=result.trace, live=en_curso, live_steps=hechos, live_phase=2,
                       en_vivo=True, headline=f"Fase II · audio e infografía en curso · {t:.1f} s")

        media = run_live(
            lambda on_step: generate_media(providers, tariffs, result, with_audio=con_audio,
                                           with_image=con_imagen, on_step=on_step),
            tick,
        )
        cache: AnalysisCache = st.session_state.cache
        cache.put_media(st.session_state.clave, media, *st.session_state.pedidos)
        st.session_state.media = media
        st.rerun()


def _nombre_pdf(result: AnalysisResult) -> str:
    mercado = getattr(result, "market", None)
    simbolo = getattr(getattr(mercado, "series", None), "symbol", "") or "informe"
    limpio = re.sub(r"[^A-Za-z0-9.-]+", "-", simbolo).strip("-") or "informe"
    return f"finlens_{limpio}_{date.today():%Y%m%d}.pdf"


def pdf_nota(result: AnalysisResult, media: MediaResult | None) -> None:
    """«Descargar nota en PDF»: se genera una vez por análisis y estado del chat (caché en la sesión)."""
    chat = [(m["role"], m["content"]) for m in st.session_state.get("chat", [])]
    clave = (st.session_state.get("clave"), len(chat), media is not None)
    cache = st.session_state.setdefault("pdf_nota", {})
    if clave not in cache:
        try:
            cache.clear()
            from finlens.export.report_pdf import build_report_pdf  # perezoso: un fallo aquí no tumba la app

            cache[clave] = build_report_pdf(result, media, chat)
        except Exception:  # la exportación nunca debe tumbar la nota
            log.exception("No se pudo generar el PDF de la nota")
            cache[clave] = None
    datos = cache[clave]
    _, derecha = st.columns([3, 1], vertical_alignment="center")
    if datos is None:
        derecha.caption("No se pudo generar el PDF de la nota; el análisis sigue disponible en pantalla.")
        return
    derecha.download_button(
        "Descargar nota en PDF", datos, file_name=_nombre_pdf(result), mime="application/pdf",
        on_click="ignore", type="secondary", icon=":material/download:", width="stretch",
        help="Informe, cifras con sus sellos, contraste, traza y chat de esta sesión."
        + ("" if media is not None else " Los medios se añadirán cuando terminen."),
    )


def show_brain(providers: Providers, form: Formulario) -> None:
    """§0: reposo con las entradas elegidas; reproducción de la traza cuando hay informe y medios."""
    result = st.session_state.get("result")
    media = st.session_state.get("media")
    replay = result is not None and media is not None and not st.session_state.get("error")
    datos = brain.build_brain(
        providers, aportes=st.session_state.get("aportes", form.aportes) if replay else form.aportes,
        detalles=st.session_state.get("detalles", form.detalles) if replay else form.detalles,
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
        st.session_state.detalles = form.detalles
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
