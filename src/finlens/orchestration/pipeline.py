"""Orquestador: encadena los pasos, ejecuta visión y STT en paralelo y registra traza y coste.

Dos fases para poder renderizar de forma progresiva:
  1. `analyze`: ingesta, visión ‖ STT, recuperación, análisis y guardrails (informe listo).
  2. `generate_media`: audio TTS ‖ infografía (opcionales; si fallan se entrega el informe igual).
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Generic, Literal, Sequence, TypeVar

from finlens.domain import cost
from finlens.domain.cost import Tariffs
from finlens.domain.guardrails import (
    REMOVED_NOTICE,
    SPOKEN_DISCLAIMER,
    GuardrailResult,
    Violation,
    apply_guardrails,
    guard_text,
)
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
from finlens.domain.rag import Retrieved, Retriever
from finlens.domain.schemas import AnalysisReport, ChartReading, ChatAnswer, InfographicPrompt
from finlens.domain.structured import (
    StructuredOutputError,
    ask_structured,
    ask_structured_vision,
)
from finlens.orchestration.trace import TraceStep, total_cost
from finlens.providers.base import (
    ImageResult,
    Message,
    ProviderError,
    Providers,
    SpeechResult,
    TextResult,
)

T = TypeVar("T")
AudioRole = Literal["conferencia", "pregunta"]

DEFAULT_QUESTION = (
    "Resume los puntos clave del informe: cifras principales, evolución del margen y "
    "declaraciones de la dirección."
)
RETRIEVAL_K = 4


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
    retriever: Retriever
    chart: ChartReading | None
    transcript: str | None
    trace: tuple[TraceStep, ...]
    warnings: tuple[str, ...]
    total_seconds: float

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


@dataclass(frozen=True)
class _Outcome(Generic[T]):
    """Valor de un paso (None si falló), sus registros de traza y avisos."""

    value: T | None
    steps: tuple[TraceStep, ...]
    warnings: tuple[str, ...] = ()
    error: str | None = None


def _error_message(exc: Exception) -> str:
    controlados = (StepError, ProviderError, StructuredOutputError, IngestError)
    return str(exc) if isinstance(exc, controlados) else f"error inesperado ({type(exc).__name__})"


def _execute(step: str, fn: Callable[[], _Done[T]], parallel: bool = False) -> _Outcome[T]:
    """Ejecuta `fn` midiendo el tiempo. Un fallo se registra en la traza, no se propaga."""
    inicio = time.perf_counter()
    try:
        hecho = fn()
    except Exception as exc:  # frontera de paso: cualquier fallo se degrada o se reporta
        mensaje = _error_message(exc)
        registro = TraceStep(
            step, "—", time.perf_counter() - inicio, mensaje, ok=False, parallel=parallel
        )
        return _Outcome(None, (registro,), (f"{step}: {mensaje}",), mensaje)
    registro = TraceStep(
        step, hecho.model, time.perf_counter() - inicio, hecho.note, hecho.cost,
        parallel=parallel, tokens_in=hecho.tokens_in, tokens_out=hecho.tokens_out,
        quantity=hecho.quantity, unit=hecho.unit,
    )
    return _Outcome(hecho.value, (registro,))


def _mandatory(trace: list[TraceStep], step: str, fn: Callable[[], _Done[T]]) -> T:
    """Como `_execute` pero un fallo detiene el pipeline con PipelineError."""
    resultado = _execute(step, fn)
    trace.extend(resultado.steps)
    if resultado.error is not None:
        raise PipelineError(resultado.error, trace)
    return resultado.value  # type: ignore[return-value]


def _tokens(calls: Sequence[TextResult]) -> tuple[int, int]:
    """Tokens de entrada y salida acumulados de las llamadas (incluye reintentos)."""
    return sum(c.tokens_in for c in calls), sum(c.tokens_out for c in calls)


# --- Fase 1: análisis -----------------------------------------------------------------------


def _step_ingest(pdf: bytes, max_chars: int) -> _Done[tuple[IngestedDocument, Retriever]]:
    doc = ingest_pdf(pdf, max_chars=max_chars)
    try:
        retriever = Retriever(doc.chunks)
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
        *_tokens(resultado.calls),
    )


def _step_stt(providers: Providers, tariffs: Tariffs, inp: AnalysisInput) -> _Done[str]:
    assert inp.audio is not None
    resultado = providers.stt.transcribe(inp.audio, inp.audio_name)
    if not resultado.text.strip():
        raise StepError("No se detectó voz en el audio.")
    nota = f"{resultado.duration_s:.0f} s de audio · {len(resultado.text)} caracteres"
    return _Done(
        resultado.text, resultado.model, cost.stt_cost(tariffs, resultado.duration_s), nota,
        quantity=resultado.duration_s, unit="s de audio",
    )


def _resolve_question(inp: AnalysisInput, transcript: str | None) -> str:
    """La pregunta final: texto escrito, voz transcrita (si el audio es una pregunta) o la de defecto."""
    escrita = inp.question.strip()
    if inp.audio_role == "pregunta" and transcript:
        return f"{escrita} {transcript}".strip()
    return escrita or DEFAULT_QUESTION


def _step_retrieve(
    retriever: Retriever, document: IngestedDocument, question: str
) -> _Done[list[Retrieved]]:
    encontrados = retriever.search(question, RETRIEVAL_K)
    if encontrados:
        return _Done(encontrados, "TF-IDF", note=f"{len(encontrados)} fragmentos relevantes")
    respaldo = [Retrieved(c, 0.0) for c in document.chunks[:RETRIEVAL_K]]
    return _Done(respaldo, "TF-IDF", note="sin coincidencias: se usan los primeros fragmentos")


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
    return _Done(resultado.value, resultado.calls[-1].model, coste, nota, *_tokens(resultado.calls))


def analyze(
    providers: Providers,
    tariffs: Tariffs,
    inp: AnalysisInput,
    *,
    max_pdf_chars: int = DEFAULT_MAX_CHARS,
) -> AnalysisResult:
    """Ejecuta el análisis completo. Solo PDF y análisis son obligatorios; el resto degrada."""
    inicio = time.perf_counter()
    trace: list[TraceStep] = []
    warnings: list[str] = []

    document, retriever = _mandatory(trace, "Ingesta e índice", lambda: _step_ingest(inp.pdf, max_pdf_chars))
    if document.truncated:
        warnings.append("El PDF superaba el límite de entrada: se analizó solo el principio.")

    # Visión y STT son independientes: se lanzan a la vez.
    chart: ChartReading | None = None
    transcript: str | None = None
    en_paralelo = inp.chart is not None and inp.audio is not None
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuro_vision = (
            pool.submit(_execute, "Lectura del gráfico", lambda: _step_vision(providers, tariffs, inp), en_paralelo)
            if inp.chart is not None else None
        )
        futuro_stt = (
            pool.submit(_execute, "Transcripción de audio", lambda: _step_stt(providers, tariffs, inp), en_paralelo)
            if inp.audio is not None else None
        )
        for futuro in (futuro_vision, futuro_stt):
            if futuro is None:
                continue
            salida = futuro.result()
            trace.extend(salida.steps)
            warnings.extend(salida.warnings)
            if futuro is futuro_vision:
                chart = salida.value
            else:
                transcript = salida.value

    question = _resolve_question(inp, transcript)
    if inp.audio_role == "pregunta" and inp.audio is not None and transcript is None and not inp.question.strip():
        warnings.append("No se pudo leer la pregunta por voz: se usa la pregunta por defecto.")
    retrieved = _mandatory(trace, "Recuperación", lambda: _step_retrieve(retriever, document, question))
    context_transcript = transcript if inp.audio_role == "conferencia" else None
    report = _mandatory(
        trace,
        "Análisis (LLM)",
        lambda: _step_analysis(providers, tariffs, question, retrieved, chart, context_transcript),
    )

    guard = apply_guardrails(report)
    trace.append(
        TraceStep(
            "Guardrails de compliance", "reglas deterministas", 0.0,
            f"{len(guard.violations)} fragmento(s) retirado(s)" if guard.blocked else "sin incidencias",
        )
    )
    if guard.blocked:
        warnings.append(
            "Se retiró contenido del informe por parecer una recomendación de inversión."
        )

    return AnalysisResult(
        question, guard, document, retriever, chart, transcript,
        tuple(trace), tuple(warnings), time.perf_counter() - inicio,
    )


# --- Fase 2: medios opcionales --------------------------------------------------------------


def _step_tts(providers: Providers, tariffs: Tariffs, report: AnalysisReport) -> _Done[SpeechResult]:
    if report.spoken_summary == REMOVED_NOTICE:
        raise StepError("El guion de audio incumplía la política de no asesoramiento.")
    resultado = providers.tts.synthesize(f"{report.spoken_summary} {SPOKEN_DISCLAIMER}")
    nota = f"{resultado.chars} caracteres"
    return _Done(
        resultado, resultado.model, cost.tts_cost(tariffs, resultado.chars), nota,
        quantity=resultado.chars, unit="caracteres",
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
        prompt, resultado.calls[-1].model, coste, f"{len(prompt)} caracteres", *_tokens(resultado.calls)
    )


def _step_image(providers: Providers, tariffs: Tariffs, prompt: str) -> _Done[ImageResult]:
    resultado = providers.image.generate(prompt)
    return _Done(
        resultado, resultado.model, cost.image_cost(tariffs), "1 imagen", quantity=1, unit="imagen"
    )


def _infographic(
    providers: Providers, tariffs: Tariffs, report: AnalysisReport, parallel: bool
) -> _Outcome[tuple[ImageResult, str]]:
    """Prompt de imagen (LLM) y generación; si falla el primero no se intenta el segundo."""
    paso_prompt = _execute(
        "Prompt de infografía", lambda: _step_image_prompt(providers, tariffs, report), parallel
    )
    if paso_prompt.value is None:
        return _Outcome(None, paso_prompt.steps, paso_prompt.warnings, paso_prompt.error)
    prompt = paso_prompt.value
    paso_imagen = _execute(
        "Generación de infografía", lambda: _step_image(providers, tariffs, prompt), parallel
    )
    imagen = None if paso_imagen.value is None else (paso_imagen.value, prompt)
    return _Outcome(
        imagen, paso_prompt.steps + paso_imagen.steps, paso_prompt.warnings + paso_imagen.warnings
    )


def generate_media(
    providers: Providers,
    tariffs: Tariffs,
    result: AnalysisResult,
    *,
    with_audio: bool = True,
    with_image: bool = True,
) -> MediaResult:
    """Genera audio e infografía (los solicitados) en paralelo.

    Un fallo se avisa pero no impide entregar el informe. Omitir un medio evita su coste.
    """
    inicio = time.perf_counter()
    report = result.report
    paralelo = with_audio and with_image
    vacio: _Outcome = _Outcome(None, ())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuro_audio = (
            pool.submit(_execute, "Resumen en audio", lambda: _step_tts(providers, tariffs, report), paralelo)
            if with_audio else None
        )
        futuro_imagen = (
            pool.submit(_infographic, providers, tariffs, report, paralelo) if with_image else None
        )
        audio = futuro_audio.result() if futuro_audio else vacio
        infografia = futuro_imagen.result() if futuro_imagen else vacio
    imagen, prompt = infografia.value if infografia.value else (None, None)
    return MediaResult(
        audio.value, imagen, prompt,
        audio.steps + infografia.steps,
        audio.warnings + infografia.warnings,
        time.perf_counter() - inicio,
        audio_skipped=not with_audio,
        image_skipped=not with_image,
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
    retrieved = result.retriever.search(question, RETRIEVAL_K)
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
    nota = "respuesta retirada por el guardrail" if violaciones else f"{len(retrieved)} fragmentos de contexto"
    tokens_in, tokens_out = _tokens(respuesta.calls)
    paso = TraceStep(
        "Chat de seguimiento", respuesta.calls[-1].model, time.perf_counter() - inicio, nota, coste,
        tokens_in=tokens_in, tokens_out=tokens_out,
    )
    return FollowUp(answer, paso, tuple(violaciones))
