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
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar, cast

from finlens.domain import cost
from finlens.domain.cost import Tariffs
from finlens.domain.grounding import FigureCheck, check_figures
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
from finlens.domain.prompts import (
    ANALYST_SYSTEM,
    CHAT_SYSTEM,
    INFOGRAPHIC_SYSTEM,
    VISION_PROMPT,
    build_analysis_messages,
    build_chat_messages,
    build_infographic_messages,
)
from finlens.domain.rag import HybridRetriever, Retrieved
from finlens.domain.schemas import AnalysisReport, ChartReading, ChatAnswer, InfographicPrompt
from finlens.domain.structured import (
    StructuredOutputError,
    ask_structured,
    ask_structured_vision,
)
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


@dataclass(frozen=True)
class AnalysisResult:
    """Informe saneado y todo lo necesario para el chat de seguimiento y la traza."""

    question: str
    guard: GuardrailResult
    document: IngestedDocument
    retriever: HybridRetriever
    chart: ChartReading | None
    transcript: str | None
    trace: tuple[TraceStep, ...]
    warnings: tuple[str, ...]
    total_seconds: float
    figure_checks: tuple[FigureCheck, ...] = ()

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
    controlados = (StepError, ProviderError, StructuredOutputError, IngestError)
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


def _step_vision(providers: Providers, tariffs: Tariffs, inp: AnalysisInput) -> _Done[ChartReading]:
    assert inp.chart is not None
    resultado = ask_structured_vision(
        providers.vision, inp.chart, inp.chart_mime, VISION_PROMPT, ChartReading
    )
    coste = sum(cost.text_result_cost(tariffs, c) for c in resultado.calls)
    return _Done(
        resultado.value, resultado.calls[-1].model, coste, f"tendencia {resultado.value.trend}",
        *_tokens(resultado.calls), cost_real=_real(resultado.calls),
    )


def _step_stt(providers: Providers, tariffs: Tariffs, inp: AnalysisInput) -> _Done[str]:
    assert inp.audio is not None
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
    return escrita or DEFAULT_QUESTION


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
) -> _Done[AnalysisReport]:
    mensajes = build_analysis_messages(question, retrieved, chart, context_transcript)
    resultado = ask_structured(providers.llm, ANALYST_SYSTEM, mensajes, AnalysisReport, 3000)
    coste = sum(cost.text_result_cost(tariffs, c) for c in resultado.calls)
    nota = f"{len(resultado.calls)} llamada(s)" + (" · con reintento" if len(resultado.calls) > 1 else "")
    return _Done(
        resultado.value, resultado.calls[-1].model, coste, nota, *_tokens(resultado.calls),
        cost_real=_real(resultado.calls),
    )


def _step_grounding(
    report: AnalysisReport, document: IngestedDocument
) -> _Done[tuple[FigureCheck, ...]]:
    """Verificación determinista de cifras (aviso, nunca bloqueo)."""
    checks = check_figures(report, document)
    verificadas = sum(c.status == "verificada" for c in checks)
    falladas = [c for c in checks if c.status == "no_encontrada"]
    avisos: tuple[str, ...] = ()
    if falladas:
        nombres = ", ".join(f"{c.figure_name} ({c.value})" for c in falladas)
        avisos = (
            f"Cifras no encontradas en la página citada del documento: {nombres}. Verifícalas antes de usarlas.",
        )
    return _Done(
        checks, "reglas deterministas", note=f"{verificadas}/{len(checks)} cifras verificadas", warnings=avisos
    )


def _step_guardrails(report: AnalysisReport) -> _Done[GuardrailResult]:
    guard = apply_guardrails(report)
    nota = f"{len(guard.violations)} fragmento(s) retirado(s)" if guard.blocked else "sin incidencias"
    avisos = (
        ("Se retiró contenido del informe por parecer una recomendación de inversión.",)
        if guard.blocked else ()
    )
    return _Done(guard, "reglas deterministas", note=nota, warnings=avisos)


def analyze(
    providers: Providers,
    tariffs: Tariffs,
    inp: AnalysisInput,
    *,
    max_pdf_chars: int = DEFAULT_MAX_CHARS,
    on_step: OnStep | None = None,
) -> AnalysisResult:
    """Ejecuta el análisis completo. Solo PDF y análisis son obligatorios; el resto degrada.

    `on_step(nombre, "start"|"end", TraceStep|None)` es un callback opcional de progreso; puede
    llamarse desde hilos del pool, así que debe ser thread-safe.
    """
    fase = _Phase(on_step)
    trace: list[TraceStep] = []
    warnings: list[str] = []

    document, retriever = _mandatory(
        trace, "Ingesta e índice", lambda: _step_ingest(inp.pdf, max_pdf_chars), fase
    )
    if document.truncated:
        warnings.append("El PDF superaba el límite de entrada: se analizó solo el principio.")

    # Ramas independientes tras la ingesta (índice semántico, visión, STT): se lanzan a la vez.
    # Las ramas futuras (mercado, cotización...) se añaden aquí como una entrada más.
    ramas: list[tuple[str, Callable[[], _Done[Any]]]] = [
        ("Índice semántico (embeddings)", lambda: _step_embed(providers, tariffs, retriever))
    ]
    if inp.chart is not None:
        ramas.append(("Lectura del gráfico", lambda: _step_vision(providers, tariffs, inp)))
    if inp.audio is not None:
        ramas.append(("Transcripción de audio", lambda: _step_stt(providers, tariffs, inp)))
    en_paralelo = len(ramas) > 1
    resultados: dict[str, _Outcome[Any]] = {}
    with ThreadPoolExecutor(max_workers=len(ramas)) as pool:
        futuros = {
            nombre: pool.submit(_execute, nombre, fn, en_paralelo, fase) for nombre, fn in ramas
        }
        for nombre, futuro in futuros.items():  # orden fijo de la traza
            salida = futuro.result()
            resultados[nombre] = salida
            trace.extend(salida.steps)
            warnings.extend(salida.warnings)

    chart = cast("ChartReading | None", resultados.get("Lectura del gráfico", _Outcome(None, ())).value)
    transcript = cast("str | None", resultados.get("Transcripción de audio", _Outcome(None, ())).value)
    indice = cast("EmbeddingResult | None", resultados["Índice semántico (embeddings)"].value)
    if indice is not None:
        retriever = retriever.with_embeddings(indice.vectors, providers.embeddings)

    question = _resolve_question(inp, transcript)
    if inp.audio_role == "pregunta" and inp.audio is not None and transcript is None and not inp.question.strip():
        warnings.append("No se pudo leer la pregunta por voz: se usa la pregunta por defecto.")
    busqueda = _execute("Recuperación", lambda: _step_retrieve(retriever, document, question, tariffs), phase=fase)
    trace.extend(busqueda.steps)
    if busqueda.error is not None:
        raise PipelineError(busqueda.error, trace)
    warnings.extend(busqueda.warnings)
    retrieved = cast("list[Retrieved]", busqueda.value)
    context_transcript = transcript if inp.audio_role == "conferencia" else None
    report = _mandatory(
        trace,
        "Análisis (LLM)",
        lambda: _step_analysis(providers, tariffs, question, retrieved, chart, context_transcript),
        fase,
    )

    saneado = _execute("Guardrails de compliance", lambda: _step_guardrails(report), phase=fase)
    trace.extend(saneado.steps)
    if saneado.error is not None:  # sin guardrails no se entrega nada: es una barrera de seguridad
        raise PipelineError(saneado.error, trace)
    warnings.extend(saneado.warnings)
    guard = cast("GuardrailResult", saneado.value)

    verificacion = _execute(
        "Verificación de cifras", lambda: _step_grounding(guard.report, document), phase=fase
    )
    trace.extend(verificacion.steps)
    warnings.extend(verificacion.warnings)
    checks = cast("tuple[FigureCheck, ...] | None", verificacion.value) or ()

    return AnalysisResult(
        question, guard, document, retriever, chart, transcript,
        tuple(trace), tuple(warnings), fase.now(), checks,
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
    busqueda = result.retriever.search_detailed(question, RETRIEVAL_K)
    retrieved = busqueda.results
    mensajes = build_chat_messages(history, question, result.report, retrieved)
    try:
        respuesta = ask_structured(providers.llm, CHAT_SYSTEM, mensajes, ChatAnswer)
    except (StructuredOutputError, ProviderError) as exc:
        paso = TraceStep("Chat de seguimiento", "—", time.perf_counter() - inicio, str(exc), ok=False)
        raise PipelineError(str(exc), [paso]) from exc

    texto, violaciones = guard_text(respuesta.value.answer, "chat")
    answer = respuesta.value
    if violaciones:
        answer = ChatAnswer(answer=texto, grounded=False)
    coste = sum(cost.text_result_cost(tariffs, c) for c in respuesta.calls)
    if busqueda.embedding:  # solo se embebe la pregunta: el índice del documento se reutiliza
        coste += cost.embedding_cost(tariffs, busqueda.embedding)
    nota = "respuesta retirada por el guardrail" if violaciones else f"{len(retrieved)} fragmentos de contexto"
    tokens_in, tokens_out = _tokens(respuesta.calls)
    paso = TraceStep(
        "Chat de seguimiento", respuesta.calls[-1].model, time.perf_counter() - inicio, nota, coste,
        tokens_in=tokens_in, tokens_out=tokens_out, cost_real=_real(respuesta.calls),
    )
    return FollowUp(answer, paso, tuple(violaciones))
