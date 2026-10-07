"""Orquestador: encadena los pasos, ejecuta visión y STT en paralelo y registra traza y coste.

Dos fases para poder renderizar de forma progresiva:
  1. `analyze`: ingesta, visión ‖ STT, recuperación, análisis y guardrails (informe listo).
  2. `generate_media`: audio TTS ‖ infografía (opcionales; si fallan se entrega el informe igual).
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Any, Generic, Literal, TypeVar, cast

from finlens.domain import cost
from finlens.domain.chart_check import ChartCheck, check_chart_reading
from finlens.domain.cost import Tariffs
from finlens.domain.grounding import FigureCheck, check_figures, check_market_claims
from finlens.domain.guardrails import (
    REMOVED_NOTICE,
    SPOKEN_DISCLAIMER,
    GuardrailResult,
    Violation,
    apply_guardrails,
    guard_text,
)
from finlens.domain.infographic import compose_infographic
from finlens.domain.ingest import DEFAULT_MAX_CHARS, IngestedDocument, IngestError, ingest_pdf
from finlens.domain.market_chart import render_market_chart
from finlens.domain.media_checks import check_audio, check_image
from finlens.domain.prompts import (
    ANALYST_SYSTEM,
    CHAT_SYSTEM,
    INFOGRAPHIC_SYSTEM,
    VISION_PROMPT,
    build_analysis_messages,
    build_chat_messages,
    build_infographic_messages,
    format_fundamentals,
    format_market,
)
from finlens.domain.rag import HybridRetriever, Retrieved
from finlens.domain.schemas import AnalysisReport, ChartReading, ChatAnswer, InfographicPrompt
from finlens.domain.structured import (
    StructuredOutputError,
    ask_structured,
    ask_structured_vision,
)
from finlens.domain.technicals import TechnicalSummary, compute_technicals
from finlens.orchestration.trace import TraceStep, total_cost
from finlens.providers.base import (
    EmbeddingResult,
    ImageResult,
    Message,
    ProviderError,
    Providers,
    SpeechResult,
    TextResult,
)
from finlens.sources.base import (  # noqa: E402
    DerivativesSnapshot,
    Fundamentals,
    PriceSeries,
    SourceError,
)
from finlens.sources.registry import MarketSources, build_sources, simbolo_visible  # noqa: E402

log = logging.getLogger("finlens.pipeline")
T = TypeVar("T")
AudioRole = Literal["conferencia", "pregunta"]

DEFAULT_QUESTION = (
    "Resume los puntos clave del informe: cifras principales, evolución del margen y "
    "declaraciones de la dirección."
)
RETRIEVAL_K = 8
OnStep = Callable[[str, Literal["start", "end"], TraceStep | None], None]


class StepError(Exception):
    """Fallo controlado de un paso. El mensaje es apto para la UI."""


class PipelineError(Exception):
    """Fallo de un paso obligatorio. Lleva la traza de lo ejecutado hasta el fallo."""

    def __init__(self, message: str, trace: Sequence[TraceStep] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.trace = tuple(trace)


@dataclass(frozen=True)
class AnalysisInput:
    """Materiales y pregunta de un análisis. Solo el PDF es obligatorio."""

    pdf: bytes
    question: str = ""
    chart: bytes | None = None
    chart_mime: str = "image/png"
    audio: bytes | None = None
    audio_name: str = "audio.wav"
    audio_role: AudioRole = "conferencia"
    ticker: str = ""  # PDF o ticker (al menos uno); sin PDF (b"") el análisis trabaja con mercado
    market_range: str = "6mo"


@dataclass(frozen=True)
class MarketContext:
    """Datos de mercado de un análisis: serie, indicadores calculados en Python y contraste con la visión."""

    series: PriceSeries
    technicals: TechnicalSummary
    derivatives: DerivativesSnapshot | None = None
    fundamentals: Fundamentals | None = None
    chart_check: ChartCheck | None = None
    chart_png: bytes | None = None  # gráfico generado (None si el usuario subió el suyo)
    kind: str = ""  # "accion" | "cripto"


@dataclass(frozen=True)
class AnalysisResult:
    """Informe saneado y todo lo necesario para el chat de seguimiento y la traza."""

    question: str
    guard: GuardrailResult
    document: IngestedDocument
    retriever: HybridRetriever | None  # None si no hubo PDF
    chart: ChartReading | None
    transcript: str | None
    trace: tuple[TraceStep, ...]
    warnings: tuple[str, ...]
    total_seconds: float
    figure_checks: tuple[FigureCheck, ...] = ()
    market: MarketContext | None = None
    chart_generated: ChartReading | None = None  # lectura del gráfico generado con la serie del ticker

    @property
    def report(self) -> AnalysisReport:
        return self.guard.report

    @property
    def cost_usd(self) -> float:
        return total_cost(self.trace)


@dataclass(frozen=True)
class MediaResult:
    """Audio e infografía (None si el paso falló o no se solicitó, ver `*_skipped`)."""

    audio: SpeechResult | None
    image: ImageResult | None
    image_prompt: str | None
    trace: tuple[TraceStep, ...]
    warnings: tuple[str, ...]
    total_seconds: float
    audio_skipped: bool = False
    image_skipped: bool = False
    illustration: ImageResult | None = None  # ilustración cruda del modelo de imagen (sin cifras)

    @property
    def cost_usd(self) -> float:
        return total_cost(self.trace)


@dataclass(frozen=True)
class FollowUp:
    """Respuesta del chat de seguimiento, ya pasada por el guardrail."""

    answer: ChatAnswer
    step: TraceStep
    violations: tuple[Violation, ...] = ()


# --- Ejecución de pasos con traza -----------------------------------------------------------


@dataclass(frozen=True)
class _Done(Generic[T]):
    """Resultado de un paso: valor y datos para la traza."""

    value: T
    model: str
    cost: float = 0.0
    note: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    quantity: float = 0.0
    unit: str = ""
    warnings: tuple[str, ...] = ()
    cost_real: bool = False


@dataclass(frozen=True)
class _Outcome(Generic[T]):
    """Valor de un paso (None si falló), sus registros de traza y avisos."""

    value: T | None
    steps: tuple[TraceStep, ...]
    warnings: tuple[str, ...] = ()
    error: str | None = None


class _Phase:
    """Reloj y callback de progreso de una fase (`analyze` o `generate_media`)."""

    def __init__(self, on_step: OnStep | None = None) -> None:
        self.t0 = time.perf_counter()
        self._on_step = on_step

    def now(self) -> float:
        return time.perf_counter() - self.t0

    def notify(self, step: str, event: Literal["start", "end"], record: TraceStep | None = None) -> None:
        if self._on_step is None:
            return
        try:
            self._on_step(step, event, record)
        except Exception:  # un callback defectuoso nunca debe tumbar el análisis
            log.exception("el callback de progreso falló en el paso '%s'", step)


def _error_message(exc: Exception) -> str:
    controlados = (StepError, ProviderError, StructuredOutputError, IngestError, SourceError)
    return str(exc) if isinstance(exc, controlados) else f"error inesperado ({type(exc).__name__})"


def _execute(
    step: str, fn: Callable[[], _Done[T]], parallel: bool = False, phase: _Phase | None = None
) -> _Outcome[T]:
    """Ejecuta `fn` midiendo el tiempo. Un fallo se registra en la traza, no se propaga."""
    inicio = time.perf_counter()
    empezo = phase.now() if phase else None
    if phase:
        phase.notify(step, "start")
    try:
        hecho = fn()
    except Exception as exc:  # frontera de paso: cualquier fallo se degrada o se reporta
        mensaje = _error_message(exc)
        log.warning("paso '%s' falló en %.2f s: %s", step, time.perf_counter() - inicio, mensaje)
        gastado = getattr(exc, "cost_usd", None)  # coste ya cobrado por una llamada fallida
        registro = TraceStep(
            step, "—", time.perf_counter() - inicio, mensaje, float(gastado or 0.0), ok=False,
            parallel=parallel, started_s=empezo, cost_real=gastado is not None,
        )
        if phase:
            phase.notify(step, "end", registro)
        return _Outcome(None, (registro,), (f"{step}: {mensaje}",), mensaje)
    log.info("paso '%s' ok en %.2f s (modelo %s)", step, time.perf_counter() - inicio, hecho.model)
    registro = TraceStep(
        step, hecho.model, time.perf_counter() - inicio, hecho.note, hecho.cost,
        parallel=parallel, tokens_in=hecho.tokens_in, tokens_out=hecho.tokens_out,
        quantity=hecho.quantity, unit=hecho.unit, started_s=empezo, cost_real=hecho.cost_real,
    )
    if phase:
        phase.notify(step, "end", registro)
    return _Outcome(hecho.value, (registro,), hecho.warnings)


def _mandatory(
    trace: list[TraceStep], step: str, fn: Callable[[], _Done[T]], phase: _Phase | None = None
) -> T:
    """Como `_execute` pero un fallo detiene el pipeline con PipelineError."""
    resultado = _execute(step, fn, phase=phase)
    trace.extend(resultado.steps)
    if resultado.error is not None:
        raise PipelineError(resultado.error, trace)
    return resultado.value  # type: ignore[return-value]


def _real(calls: Sequence[TextResult]) -> bool:
    """True si todas las llamadas traen el coste real del proveedor."""
    return bool(calls) and all(c.cost_usd is not None for c in calls)


def _tokens(calls: Sequence[TextResult]) -> tuple[int, int]:
    """Tokens de entrada y salida acumulados de las llamadas (incluye reintentos)."""
    return sum(c.tokens_in for c in calls), sum(c.tokens_out for c in calls)


# --- Fase 1: análisis -----------------------------------------------------------------------


def _step_ingest(pdf: bytes, max_chars: int) -> _Done[tuple[IngestedDocument, HybridRetriever]]:
    doc = ingest_pdf(pdf, max_chars=max_chars)
    try:
        retriever = HybridRetriever(doc.chunks)
    except ValueError as exc:
        raise StepError("No se pudo indexar el documento: no contiene términos utilizables.") from exc
    nota = f"{doc.n_pages} págs · {len(doc.chunks)} fragmentos" + (" · truncado" if doc.truncated else "")
    return _Done((doc, retriever), "pypdf + TF-IDF", note=nota)


def _step_vision(
    providers: Providers, tariffs: Tariffs, chart: bytes, mime: str
) -> _Done[ChartReading]:
    if motivo := check_image(chart):
        raise StepError(motivo)
    resultado = ask_structured_vision(providers.vision, chart, mime, VISION_PROMPT, ChartReading)
    coste = sum(cost.text_result_cost(tariffs, c) for c in resultado.calls)
    return _Done(
        resultado.value, resultado.calls[-1].model, coste, f"tendencia {resultado.value.trend}",
        *_tokens(resultado.calls), cost_real=_real(resultado.calls),
    )


def _step_stt(providers: Providers, tariffs: Tariffs, inp: AnalysisInput) -> _Done[str]:
    assert inp.audio is not None
    if motivo := check_audio(inp.audio, inp.audio_name):  # antes de la llamada de pago
        raise StepError(motivo)
    resultado = providers.stt.transcribe(inp.audio, inp.audio_name)
    if not resultado.text.strip():
        raise StepError("No se detectó voz en el audio.")
    nota = f"{resultado.duration_s:.0f} s de audio · {len(resultado.text)} caracteres"
    if resultado.notes:
        nota += " · " + " · ".join(resultado.notes)
    return _Done(
        resultado.text, resultado.model, cost.transcription_cost(tariffs, resultado), nota,
        quantity=resultado.duration_s, unit="s de audio",
        warnings=resultado.warnings, cost_real=resultado.cost_usd is not None,
    )


def _resolve_question(inp: AnalysisInput, transcript: str | None) -> str:
    """La pregunta final: texto escrito, voz transcrita (si el audio es una pregunta) o la de defecto."""
    escrita = inp.question.strip()
    if inp.audio_role == "pregunta" and transcript:
        return f"{escrita} {transcript}".strip()
    if escrita:
        return escrita
    if not inp.pdf and inp.ticker.strip():
        return (
            f"Resume la situación de mercado de {simbolo_visible(inp.ticker)}: tendencia, niveles relevantes, "
            "riesgos y, si hay fundamentales, su evolución."
        )
    return DEFAULT_QUESTION


def _modo(retriever: HybridRetriever, hibrida: bool) -> str:
    return f"híbrida (TF-IDF + {retriever.embedder_model.split('/')[-1]})" if hibrida else "solo TF-IDF"


def _step_embed(providers: Providers, tariffs: Tariffs, retriever: HybridRetriever) -> _Done[EmbeddingResult]:
    """Embebe los fragmentos del documento (índice semántico)."""
    textos = [c.text for c in retriever.chunks]
    resultado = providers.embeddings.embed(textos, "document")
    if len(resultado.vectors) != len(textos):
        raise StepError("El proveedor de embeddings devolvió un número de vectores incoherente.")
    return _Done(
        resultado, resultado.model, cost.embedding_cost(tariffs, resultado),
        f"{len(textos)} fragmentos · {resultado.tokens} tokens",
        quantity=resultado.tokens, unit="tokens", cost_real=resultado.cost_usd is not None,
    )


def _step_retrieve(
    retriever: HybridRetriever, document: IngestedDocument, question: str, tariffs: Tariffs
) -> _Done[list[Retrieved]]:
    busqueda = retriever.search_detailed(question, RETRIEVAL_K)
    hibrida = busqueda.mode == "híbrida"
    avisos = (
        (f"Recuperación semántica no disponible ({busqueda.error}): se usa solo TF-IDF.",)
        if busqueda.error else ()
    )
    modelo = f"TF-IDF + {retriever.embedder_model.split('/')[-1]}" if hibrida else "TF-IDF"
    coste = cost.embedding_cost(tariffs, busqueda.embedding) if busqueda.embedding else 0.0
    real = busqueda.embedding is not None and busqueda.embedding.cost_usd is not None
    if busqueda.results:
        nota = f"{len(busqueda.results)} fragmentos relevantes · {_modo(retriever, hibrida)}"
        if hibrida:
            nota += f" · peso léxico {busqueda.lexical_weight:.2f}"
        return _Done(busqueda.results, modelo, coste, nota, warnings=avisos, cost_real=real)
    respaldo = [Retrieved(c, 0.0) for c in document.chunks[:RETRIEVAL_K]]
    return _Done(
        respaldo, modelo, coste, "sin coincidencias: se usan los primeros fragmentos",
        warnings=avisos, cost_real=real,
    )


def _step_analysis(
    providers: Providers,
    tariffs: Tariffs,
    question: str,
    retrieved: list[Retrieved],
    chart: ChartReading | None,
    context_transcript: str | None,
    market: str | None = None,
    sec: str | None = None,
    chart_generated: ChartReading | None = None,
) -> _Done[AnalysisReport]:
    mensajes = build_analysis_messages(
        question, retrieved, chart, context_transcript, market, sec, chart_generated
    )
    resultado = ask_structured(providers.llm, ANALYST_SYSTEM, mensajes, AnalysisReport, 3000)
    coste = sum(cost.text_result_cost(tariffs, c) for c in resultado.calls)
    nota = f"{len(resultado.calls)} llamada(s)" + (" · con reintento" if len(resultado.calls) > 1 else "")
    return _Done(
        resultado.value, resultado.calls[-1].model, coste, nota, *_tokens(resultado.calls),
        cost_real=_real(resultado.calls),
    )


def _step_grounding(
    report: AnalysisReport,
    document: IngestedDocument | None,
    market: MarketContext | None = None,
    fundamentals: Fundamentals | None = None,
) -> _Done[tuple[FigureCheck, ...]]:
    """Verificación determinista de cifras (aviso, nunca bloqueo)."""
    checks = check_figures(
        report, document,
        technicals=market.technicals if market else None,
        derivatives=market.derivatives if market else None,
        fundamentals=fundamentals,
    )
    verificadas = sum(c.status == "verificada" for c in checks)
    falladas = [c for c in checks if c.status == "no_encontrada"]
    avisos: tuple[str, ...] = ()
    if falladas:
        nombres = ", ".join(f"{c.figure_name} ({c.value})" for c in falladas)
        avisos = (
            f"Cifras no encontradas en la página citada del documento: {nombres}. Verifícalas antes de usarlas.",
        )
    relaciones = check_market_claims(report, market.technicals if market else None)
    nota = f"{verificadas}/{len(checks)} cifras verificadas" + (
        f" · {len(relaciones)} relación(es) incoherente(s)" if relaciones else ""
    )
    return _Done(checks, "reglas deterministas", note=nota, warnings=(*avisos, *relaciones))


def _step_guardrails(report: AnalysisReport) -> _Done[GuardrailResult]:
    guard = apply_guardrails(report)
    nota = f"{len(guard.violations)} fragmento(s) retirado(s)" if guard.blocked else "sin incidencias"
    avisos = (
        ("Se retiró contenido del informe por parecer una recomendación de inversión.",)
        if guard.blocked else ()
    )
    return _Done(guard, "reglas deterministas", note=nota, warnings=avisos)


# --- Datos de mercado (ticker) ---------------------------------------------------------------


def _step_prices(
    sources: MarketSources, ticker: str, rango: str
) -> _Done[tuple[PriceSeries, DerivativesSnapshot | None, str]]:
    kind = sources.kind(ticker)
    serie = sources.prices(ticker, rango)
    derivados: DerivativesSnapshot | None = None
    avisos: tuple[str, ...] = ()
    if kind == "cripto":
        try:
            derivados = sources.derivatives_for(ticker)
        except SourceError as exc:  # los derivados son un extra: sin ellos se sigue con precios
            avisos = (f"Derivados no disponibles: {exc}",)
    nota = f"{len(serie.candles)} velas ({rango}) · {serie.currency}" + (" · con derivados" if derivados else "")
    return _Done((serie, derivados, kind), serie.source, note=nota, warnings=avisos)


def _step_technicals(serie: PriceSeries, kind: str) -> _Done[TechnicalSummary]:
    try:
        tech = compute_technicals(serie, "cripto" if kind == "cripto" else "accion")
    except ValueError as exc:
        raise StepError(str(exc)) from exc
    nota = f"tendencia {tech.trend} · RSI {tech.rsi14:.0f}" if tech.rsi14 is not None else f"tendencia {tech.trend}"
    return _Done(tech, "reglas deterministas", note=nota)


def _step_market_chart(serie: PriceSeries) -> _Done[bytes]:
    return _Done(render_market_chart(serie), "matplotlib", note=f"{len(serie.candles)} velas")


def _step_contrast(reading: ChartReading, tech: TechnicalSummary) -> _Done[ChartCheck]:
    check = check_chart_reading(reading, tech)
    nota = f"concordancia {check.agreement_score:.0%} ({check.n_verifiable} afirmaciones verificables)"
    return _Done(check, "reglas deterministas", note=nota)


def _step_sec(sources: MarketSources, ticker: str) -> _Done[Fundamentals | None]:
    fund = sources.fundamentals_for(ticker)
    if fund is None:
        return _Done(None, "SEC EDGAR", note="sin fundamentales (cripto o empresa que no reporta a la SEC)")
    ejercicios = sorted({h.fy for h in fund.facts}, reverse=True)
    nota = f"{fund.company} · {len(fund.facts)} cifras" + (f" · FY{ejercicios[0]}" if ejercicios else "")
    return _Done(fund, "SEC EDGAR", note=nota)


def _market_branch(
    providers: Providers, tariffs: Tariffs, inp: AnalysisInput, sources: MarketSources, fase: _Phase,
    parallel: bool,
) -> _Outcome[dict[str, Any]]:
    """Cadena de mercado: datos → técnicos → gráfico generado → visión → contraste. Cada fallo degrada."""
    pasos: list[TraceStep] = []
    avisos: list[str] = []

    def correr(nombre: str, fn: Callable[[], _Done[Any]]) -> Any:
        salida = _execute(nombre, fn, parallel, fase)
        pasos.extend(salida.steps)
        avisos.extend(salida.warnings)
        return salida.value

    ticker = inp.ticker.strip()
    datos = correr("Datos de mercado", lambda: _step_prices(sources, ticker, inp.market_range))
    serie: PriceSeries | None = datos[0] if datos else None
    derivados: DerivativesSnapshot | None = datos[1] if datos else None
    kind: str = datos[2] if datos else ""
    tech = correr("Indicadores técnicos", lambda: _step_technicals(serie, kind)) if serie else None
    # El contraste visión ↔ datos se hace SIEMPRE sobre el gráfico generado con esta serie: un gráfico
    # subido puede cubrir otro periodo y daría falsas discrepancias. El subido se lee como entrada propia.
    generado: bytes | None = None
    lectura_generada = None
    if serie is not None:
        generado = correr("Gráfico generado", lambda: _step_market_chart(serie))
        if generado is not None:
            png = generado
            lectura_generada = correr(
                "Lectura del gráfico (generado)", lambda: _step_vision(providers, tariffs, png, "image/png")
            )
    lectura_aportada = None
    if inp.chart is not None:
        subido = inp.chart
        lectura_aportada = correr(
            "Lectura del gráfico (aportado)", lambda: _step_vision(providers, tariffs, subido, inp.chart_mime)
        )
    contraste = None
    if lectura_generada is not None and tech is not None:
        contraste = correr("Contraste visión ↔ datos", lambda: _step_contrast(lectura_generada, tech))
    contexto = None
    if serie is not None and tech is not None:
        contexto = MarketContext(
            serie, tech, derivados, None, contraste, generado, kind
        )
    return _Outcome(
        {"chart": lectura_aportada, "chart_generated": lectura_generada, "market": contexto},
        tuple(pasos), tuple(avisos),
    )


def analyze(
    providers: Providers,
    tariffs: Tariffs,
    inp: AnalysisInput,
    *,
    max_pdf_chars: int = DEFAULT_MAX_CHARS,
    on_step: OnStep | None = None,
    sources: MarketSources | None = None,
) -> AnalysisResult:
    """Ejecuta el análisis completo. Vale PDF o ticker; el resto de pasos degrada si falla.

    `on_step(nombre, "start"|"end", TraceStep|None)` es un callback opcional de progreso; puede
    llamarse desde hilos del pool, así que debe ser thread-safe. `sources` son los conectores de
    mercado; por defecto, simulados si todos los proveedores de IA lo son y reales si no.
    """
    fase = _Phase(on_step)
    trace: list[TraceStep] = []
    warnings: list[str] = []
    ticker = inp.ticker.strip()
    usa_pdf = bool(inp.pdf) or not ticker  # sin PDF ni ticker: ingesta falla con «El PDF está vacío»

    document = IngestedDocument((), 0)
    retriever: HybridRetriever | None = None
    if usa_pdf:
        document, retriever = _mandatory(
            trace, "Ingesta e índice", lambda: _step_ingest(inp.pdf, max_pdf_chars), fase
        )
        if document.truncated:
            warnings.append("El PDF superaba el límite de entrada: se analizó solo el principio.")
    if ticker and sources is None:
        sources = build_sources(demo=providers.is_demo)

    # Ramas independientes tras la ingesta: índice semántico, [mercado → visión → contraste], SEC y STT.
    # Se lanzan a la vez; una rama nueva es una entrada más de esta lista.
    Rama = Callable[[bool], _Outcome[Any]]
    ramas: list[tuple[str, Rama]] = []

    def simple(nombre: str, fn: Callable[[], _Done[Any]]) -> None:
        ramas.append((nombre, lambda par: _execute(nombre, fn, par, fase)))

    if retriever is not None:
        base_retriever = retriever
        simple("Índice semántico (embeddings)", lambda: _step_embed(providers, tariffs, base_retriever))
    if inp.chart is not None and not ticker:
        simple("Lectura del gráfico", lambda: _step_vision(providers, tariffs, inp.chart or b"", inp.chart_mime))
    if ticker and sources is not None:
        mercado_src = sources
        ramas.append(("mercado", lambda par: _market_branch(providers, tariffs, inp, mercado_src, fase, par)))
        simple("Fundamentales SEC", lambda: _step_sec(mercado_src, ticker))
    if inp.audio is not None:
        simple("Transcripción de audio", lambda: _step_stt(providers, tariffs, inp))
    en_paralelo = len(ramas) > 1
    resultados: dict[str, _Outcome[Any]] = {}
    if ramas:
        with ThreadPoolExecutor(max_workers=len(ramas)) as pool:
            futuros = {nombre: pool.submit(fn, en_paralelo) for nombre, fn in ramas}
            for nombre, futuro in futuros.items():  # orden fijo de la traza
                salida = futuro.result()
                resultados[nombre] = salida
                trace.extend(salida.steps)
                warnings.extend(salida.warnings)

    def valor(nombre: str) -> Any:
        return resultados[nombre].value if nombre in resultados else None

    rama_mercado: dict[str, Any] = valor("mercado") or {}
    chart_generated = cast("ChartReading | None", rama_mercado.get("chart_generated"))
    chart_aportado = cast("ChartReading | None", rama_mercado.get("chart") or valor("Lectura del gráfico"))
    chart = chart_aportado or chart_generated  # lo que muestra la UI: la lectura del gráfico del usuario o la generada
    market = cast("MarketContext | None", rama_mercado.get("market"))
    fundamentals = cast("Fundamentals | None", valor("Fundamentales SEC"))
    if market is not None and fundamentals is not None:
        market = replace(market, fundamentals=fundamentals)
    transcript = cast("str | None", valor("Transcripción de audio"))
    indice = cast("EmbeddingResult | None", valor("Índice semántico (embeddings)"))
    if retriever is not None and indice is not None:
        retriever = retriever.with_embeddings(indice.vectors, providers.embeddings)

    if not usa_pdf and market is None and fundamentals is None and chart is None and transcript is None:
        # Solo ticker y la fuente falló: sin ningún material el LLM inventaría el informe.
        motivo = next(
            (t.note for t in trace if not t.ok and t.step.startswith(("Datos de mercado", "Indicadores técnicos"))),
            "no hay datos disponibles",
        )
        raise PipelineError(f"No se pudieron obtener datos de mercado para «{ticker}»: {motivo}", trace)

    question = _resolve_question(inp, transcript)
    if inp.audio_role == "pregunta" and inp.audio is not None and transcript is None and not inp.question.strip():
        warnings.append("No se pudo leer la pregunta por voz: se usa la pregunta por defecto.")
    retrieved: list[Retrieved] = []
    if retriever is not None:
        busqueda = _execute(
            "Recuperación", lambda: _step_retrieve(retriever, document, question, tariffs), phase=fase
        )
        trace.extend(busqueda.steps)
        if busqueda.error is not None:
            raise PipelineError(busqueda.error, trace)
        warnings.extend(busqueda.warnings)
        retrieved = cast("list[Retrieved]", busqueda.value)
    context_transcript = transcript if inp.audio_role == "conferencia" else None
    texto_mercado = format_market(market.technicals, market.derivatives) if market else None
    texto_sec = format_fundamentals(fundamentals) if fundamentals else None
    report = _mandatory(
        trace,
        "Análisis (LLM)",
        lambda: _step_analysis(
            providers, tariffs, question, retrieved, chart_aportado, context_transcript, texto_mercado, texto_sec,
            chart_generated
        ),
        fase,
    )

    saneado = _execute("Guardrails de compliance", lambda: _step_guardrails(report), phase=fase)
    trace.extend(saneado.steps)
    if saneado.error is not None:  # sin guardrails no se entrega nada: es una barrera de seguridad
        raise PipelineError(saneado.error, trace)
    warnings.extend(saneado.warnings)
    guard = cast("GuardrailResult", saneado.value)

    verificacion = _execute(
        "Verificación de cifras",
        lambda: _step_grounding(guard.report, document if usa_pdf else None, market, fundamentals),
        phase=fase,
    )
    trace.extend(verificacion.steps)
    warnings.extend(verificacion.warnings)
    checks = cast("tuple[FigureCheck, ...] | None", verificacion.value) or ()

    return AnalysisResult(
        question, guard, document, retriever, chart, transcript,
        tuple(trace), tuple(warnings), fase.now(), checks, market, chart_generated,
    )


# --- Fase 2: medios opcionales --------------------------------------------------------------


def _step_tts(providers: Providers, tariffs: Tariffs, report: AnalysisReport) -> _Done[SpeechResult]:
    if report.spoken_summary == REMOVED_NOTICE:
        raise StepError("El guion de audio incumplía la política de no asesoramiento.")
    resultado = providers.tts.synthesize(f"{report.spoken_summary} {SPOKEN_DISCLAIMER}")
    nota = f"{resultado.chars} caracteres"
    return _Done(
        resultado, resultado.model, cost.speech_cost(tariffs, resultado), nota,
        quantity=resultado.chars, unit="caracteres", cost_real=resultado.cost_usd is not None,
    )


def _step_image_prompt(
    providers: Providers, tariffs: Tariffs, report: AnalysisReport
) -> _Done[str]:
    resultado = ask_structured(
        providers.llm, INFOGRAPHIC_SYSTEM, build_infographic_messages(report), InfographicPrompt
    )
    prompt, violaciones = guard_text(resultado.value.prompt, "image_prompt")
    if violaciones:
        raise StepError("El prompt de la infografía incumplía la política de no asesoramiento.")
    coste = sum(cost.text_result_cost(tariffs, c) for c in resultado.calls)
    return _Done(
        prompt, resultado.calls[-1].model, coste, f"{len(prompt)} caracteres", *_tokens(resultado.calls),
        cost_real=_real(resultado.calls),
    )


def _step_image(providers: Providers, tariffs: Tariffs, prompt: str) -> _Done[ImageResult]:
    resultado = providers.image.generate(prompt)
    return _Done(
        resultado, resultado.model, cost.image_result_cost(tariffs, resultado), "1 imagen", quantity=1,
        unit="imagen", cost_real=resultado.cost_usd is not None,
    )


@dataclass(frozen=True)
class _Infographic:
    """Infografía final compuesta, su prompt y la ilustración cruda (None si degradó)."""

    image: ImageResult
    prompt: str | None
    illustration: ImageResult | None


def _step_compose(
    result: AnalysisResult, illustration: ImageResult | None
) -> _Done[ImageResult]:
    png = compose_infographic(
        result.report, result.figure_checks, result.chart,
        illustration.image if illustration else None,
    )
    modelo = f"{illustration.model} + composición Python" if illustration else "composición Python"
    nota = "con ilustración de IA" if illustration else "sin ilustración (degradada)"
    return _Done(ImageResult(png, "image/png", modelo), modelo, 0.0, nota)


def _infographic(
    providers: Providers, tariffs: Tariffs, result: AnalysisResult, parallel: bool, fase: _Phase
) -> _Outcome[_Infographic]:
    """Ilustración sin texto (prompt del LLM + modelo de imagen) y composición con las cifras reales.

    Si falla la ilustración (o su prompt) se compone igualmente sin ella.
    """
    report = result.report
    pasos: list[TraceStep] = []
    avisos: list[str] = []
    prompt: str | None = None
    ilustracion: ImageResult | None = None

    paso_prompt = _execute(
        "Prompt de infografía", lambda: _step_image_prompt(providers, tariffs, report), parallel, fase
    )
    pasos += paso_prompt.steps
    avisos += paso_prompt.warnings
    if paso_prompt.value is not None:
        prompt = paso_prompt.value
        paso_imagen = _execute(
            "Generación de infografía", lambda: _step_image(providers, tariffs, prompt or ""), parallel, fase
        )
        pasos += paso_imagen.steps
        avisos += paso_imagen.warnings
        ilustracion = paso_imagen.value

    composicion = _execute("Composición de infografía", lambda: _step_compose(result, ilustracion), parallel, fase)
    pasos += composicion.steps
    avisos += composicion.warnings
    if composicion.value is None:
        return _Outcome(None, tuple(pasos), tuple(avisos), composicion.error)
    if ilustracion is None:
        avisos.append("La infografía se generó sin ilustración de IA; las cifras son las del informe.")
    return _Outcome(_Infographic(composicion.value, prompt, ilustracion), tuple(pasos), tuple(avisos))


def generate_media(
    providers: Providers,
    tariffs: Tariffs,
    result: AnalysisResult,
    *,
    with_audio: bool = True,
    with_image: bool = True,
    on_step: OnStep | None = None,
) -> MediaResult:
    """Genera audio e infografía (los solicitados) en paralelo.

    Un fallo se avisa pero no impide entregar el informe. Omitir un medio evita su coste.
    """
    fase = _Phase(on_step)
    report = result.report
    paralelo = with_audio and with_image
    vacio: _Outcome = _Outcome(None, ())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuro_audio = (
            pool.submit(_execute, "Resumen en audio", lambda: _step_tts(providers, tariffs, report), paralelo, fase)
            if with_audio else None
        )
        futuro_imagen = (
            pool.submit(_infographic, providers, tariffs, result, paralelo, fase) if with_image else None
        )
        audio = futuro_audio.result() if futuro_audio else vacio
        infografia = futuro_imagen.result() if futuro_imagen else vacio
    info = infografia.value
    return MediaResult(
        audio.value, info.image if info else None, info.prompt if info else None,
        audio.steps + infografia.steps,
        audio.warnings + infografia.warnings,
        fase.now(),
        audio_skipped=not with_audio,
        image_skipped=not with_image,
        illustration=info.illustration if info else None,
    )


# --- Chat de seguimiento --------------------------------------------------------------------


def answer_followup(
    providers: Providers,
    tariffs: Tariffs,
    result: AnalysisResult,
    history: Sequence[Message],
    question: str,
) -> FollowUp:
    """Responde una pregunta de seguimiento con el informe y los fragmentos relevantes."""
    inicio = time.perf_counter()
    busqueda = result.retriever.search_detailed(question, RETRIEVAL_K) if result.retriever else None
    retrieved = busqueda.results if busqueda else []
    mensajes = build_chat_messages(history, question, result.report, retrieved)
    try:
        respuesta = ask_structured(providers.llm, CHAT_SYSTEM, mensajes, ChatAnswer)
    except (StructuredOutputError, ProviderError) as exc:
        gastado = getattr(exc, "cost_usd", None)
        paso = TraceStep(
            "Chat de seguimiento", "—", time.perf_counter() - inicio, str(exc), float(gastado or 0.0), ok=False,
            cost_real=gastado is not None,
        )
        raise PipelineError(str(exc), [paso]) from exc

    texto, violaciones = guard_text(respuesta.value.answer, "chat")
    answer = respuesta.value
    if violaciones:
        answer = ChatAnswer(answer=texto, grounded=False)
    coste = sum(cost.text_result_cost(tariffs, c) for c in respuesta.calls)
    if busqueda and busqueda.embedding:  # solo se embebe la pregunta: el índice del documento se reutiliza
        coste += cost.embedding_cost(tariffs, busqueda.embedding)
    nota = "respuesta retirada por el guardrail" if violaciones else f"{len(retrieved)} fragmentos de contexto"
    tokens_in, tokens_out = _tokens(respuesta.calls)
    paso = TraceStep(
        "Chat de seguimiento", respuesta.calls[-1].model, time.perf_counter() - inicio, nota, coste,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_real=_real(respuesta.calls),
    )
    return FollowUp(answer, paso, tuple(violaciones))
