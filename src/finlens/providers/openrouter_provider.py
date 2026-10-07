"""Proveedores de OpenRouter: una sola clave para LLM, visión, voz a texto, texto a voz e imagen.

OpenRouter es compatible con el SDK `openai` (base URL propia). Endpoints usados:
`/chat/completions` (LLM y visión), `/audio/transcriptions`, `/audio/speech` e `/images`
(este último no existe en el SDK: se llama con `client.post`). Los nombres de modelo son slugs del
catálogo público (`GET /api/v1/models`) y cambian con el tiempo: VERIFICAR antes de usarlos.
La respuesta informa del coste real en USD (`usage.cost`), que se propaga como `cost_usd`.
"""
from __future__ import annotations

import base64
import logging
from collections.abc import Sequence
from typing import Any, Literal

import openai

from finlens.providers.base import (
    EmbeddingResult,
    ImageResult,
    Message,
    ProviderError,
    SpeechResult,
    TextResult,
    TranscriptionResult,
)
from finlens.providers.media import detect_image_mime, measure_audio_duration
from finlens.providers.openai_provider import MAX_AUDIO_BYTES, embed_in_batches, estimate_duration_s

BASE_URL = "https://openrouter.ai/api/v1"
log = logging.getLogger("finlens.stt")
TIMEOUT_S = 120.0
EMBEDDINGS_MAX_RETRIES = 4
MIN_DURATION_RATIO = 0.8  # duración informada / real por debajo de la cual se considera truncada
MIN_CHARS_PER_SECOND = 4.0
MIN_SECONDS_FOR_CHARS_CHECK = 5.0  # en clips muy cortos el criterio de caracteres no es fiable
ATTRIBUTION_HEADERS = {"X-Title": "FinLens"}  # HTTP-Referer es opcional y no se envía


def translate_error(exc: openai.OpenAIError, model: str) -> ProviderError:
    """Convierte un error del SDK en un ProviderError con mensaje claro (sin datos sensibles)."""
    if isinstance(exc, openai.APITimeoutError):
        return ProviderError("OpenRouter no respondió a tiempo.")
    if isinstance(exc, openai.APIConnectionError):
        return ProviderError("No se pudo conectar con OpenRouter. Revisa tu conexión a internet.")
    if isinstance(exc, openai.APIStatusError):
        codigo = exc.status_code
        if codigo == 401:
            return ProviderError("Clave de OpenRouter no válida. Revisa OPENROUTER_API_KEY.")
        if codigo == 402:
            return ProviderError("Saldo de OpenRouter insuficiente: recarga créditos en openrouter.ai.")
        if codigo == 403:
            return ProviderError(
                f"OpenRouter denegó el acceso (clave sin permisos o modelo {model} bloqueado)."
            )
        if codigo == 404:
            return ProviderError(
                f"Modelo de OpenRouter no encontrado: revisa su variable de entorno ({model})."
            )
        if codigo == 413:
            return ProviderError("La petición es demasiado grande para OpenRouter.")
        if codigo == 429:
            return ProviderError("Límite de uso de OpenRouter alcanzado: inténtalo de nuevo en unos segundos.")
        if codigo >= 500:
            return ProviderError(f"Error del servicio de OpenRouter (código {codigo}).")
        return ProviderError(f"OpenRouter rechazó la petición (código {codigo}): {_detalle_error(exc)}")
    return ProviderError("Error inesperado al llamar a OpenRouter.")


MAX_DETALLE = 200


def _detalle_error(exc: openai.APIStatusError) -> str:
    """Mensaje del cuerpo `error.message` truncado; nunca vuelca el cuerpo completo (metadata upstream)."""
    cuerpo = getattr(exc, "body", None)
    error = cuerpo.get("error") if isinstance(cuerpo, dict) else None
    mensaje = error.get("message") if isinstance(error, dict) else None
    if not isinstance(mensaje, str) or not mensaje.strip():
        return "sin detalle"
    mensaje = " ".join(mensaje.split())
    return mensaje if len(mensaje) <= MAX_DETALLE else mensaje[: MAX_DETALLE - 1] + "…"


def make_client(api_key: str, client: Any = None, max_retries: int | None = None) -> Any:
    """Cliente `openai` apuntando a OpenRouter (o el inyectado en los tests).

    `max_retries` bajo en peticiones que se cobran (imagen, TTS) evita dobles cargos y esperas largas.
    """
    if client is not None:
        return client
    extra: dict[str, Any] = {} if max_retries is None else {"max_retries": max_retries}
    return openai.OpenAI(
        api_key=api_key, base_url=BASE_URL, timeout=TIMEOUT_S, default_headers=ATTRIBUTION_HEADERS, **extra
    )


def _campo(objeto: Any, nombre: str) -> Any:
    """Lee un campo de un objeto del SDK o de un dict (los campos extra como `cost` varían)."""
    if isinstance(objeto, dict):
        return objeto.get(nombre)
    return getattr(objeto, nombre, None)


def _coste(respuesta: Any) -> float | None:
    """Coste real en USD de `usage.cost`, o None si el proveedor no lo informa."""
    valor = _campo(_campo(respuesta, "usage"), "cost")
    return float(valor) if isinstance(valor, (int, float)) else None


class _ChatBase:
    """Lógica común de LLM y visión: llamada a /chat/completions y validación de la respuesta."""

    def __init__(
        self,
        api_key: str,
        model: str,
        client: Any = None,
        *,
        reasoning_effort: str = "",
        min_output_tokens: int = 0,
    ) -> None:
        self.model = model
        self._reasoning_effort = reasoning_effort.strip()
        self._min_output_tokens = min_output_tokens
        self._client = make_client(api_key, client)

    def _send(self, mensajes: list[dict[str, Any]], max_tokens: int) -> TextResult:
        # Algunos modelos razonan siempre y sus tokens de razonamiento cuentan contra max_tokens:
        # un límite bajo deja la respuesta vacía (y cobrada). Se fija un mínimo y el esfuerzo.
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": mensajes,
            "max_tokens": max(max_tokens, self._min_output_tokens),
        }
        if self._reasoning_effort:
            kwargs["extra_body"] = {"reasoning": {"effort": self._reasoning_effort}}
        try:
            respuesta = self._client.chat.completions.create(**kwargs)
        except openai.OpenAIError as exc:
            raise translate_error(exc, self.model) from exc
        coste = _coste(respuesta)
        if not respuesta.choices:
            raise ProviderError("OpenRouter devolvió una respuesta vacía.", coste)
        eleccion = respuesta.choices[0]
        uso = _campo(respuesta, "usage")
        razonamiento = int(
            _campo(_campo(uso, "completion_tokens_details"), "reasoning_tokens") or 0
        )
        if razonamiento:
            log.debug("tokens de razonamiento: %d", razonamiento)
        if eleccion.finish_reason == "length":
            raise ProviderError(
                "La respuesta del modelo se cortó por límite de tokens"
                + (f" (razonamiento: {razonamiento} tokens)." if razonamiento else "."),
                coste,
            )
        texto = eleccion.message.content or ""
        if not texto.strip():
            raise ProviderError("El modelo devolvió una respuesta vacía.", coste)
        return TextResult(
            texto,
            _campo(respuesta, "model") or self.model,
            int(_campo(uso, "prompt_tokens") or 0),
            int(_campo(uso, "completion_tokens") or 0),
            coste,
            razonamiento,
        )


class OpenRouterLLM(_ChatBase):
    """LLM de razonamiento y síntesis. El JSON lo valida `domain.structured`, no `response_format`."""

    def complete(
        self, system: str, messages: Sequence[Message], max_tokens: int = 2048
    ) -> TextResult:
        mensajes: list[dict[str, Any]] = [{"role": "system", "content": system}] if system else []
        mensajes += [{"role": m.role, "content": m.content} for m in messages]
        return self._send(mensajes, max_tokens)


class OpenRouterVision(_ChatBase):
    """Lectura de un gráfico con un modelo multimodal (imagen como data URL)."""

    def describe_image(self, image: bytes, mime: str, prompt: str) -> TextResult:
        if not image:
            raise ProviderError("La imagen está vacía.")
        real = detect_image_mime(image)  # la firma manda: el tipo declarado puede ser erróneo
        if real is None:
            raise ProviderError("La imagen está dañada o no es PNG, JPEG, GIF ni WebP.")
        url = f"data:{real};base64,{base64.standard_b64encode(image).decode('ascii')}"
        contenido = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": url}},
        ]
        return self._send([{"role": "user", "content": contenido}], 2048)


def _formato_stt(model: str) -> str:
    """Los modelos `gpt-4o*-transcribe` solo admiten `json` (sin duración); el resto, verbose_json."""
    return "json" if "gpt-4o" in model else "verbose_json"


def _suma(a: float | None, b: float | None) -> float | None:
    return None if a is None and b is None else (a or 0.0) + (b or 0.0)


class OpenRouterSTT:
    """Voz a texto (`/audio/transcriptions`) en español, con detección de transcripciones truncadas.

    Algunos modelos upstream (p.ej. whisper-large-v3) devuelven a veces solo el primer segmento.
    Se mide la duración real del audio con mutagen y, si lo transcrito es claramente menor, se reintenta
    una vez con `fallback_model`; si el respaldo tampoco convence se acepta la transcripción más larga.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        client: Any = None,
        fallback_model: str = "",
        language: str = "",
    ) -> None:
        self.model = model
        self._fallback = fallback_model.strip()
        self._language = language.strip()
        self._client = make_client(api_key, client)

    def _llamar(self, model: str, audio: bytes, filename: str) -> tuple[str, float | None, float | None]:
        """Una transcripción: (texto, duración informada o None, coste real o None)."""
        try:
            extra = {"language": self._language} if self._language else {}
            respuesta = self._client.audio.transcriptions.create(
                model=model, file=(filename, audio), response_format=_formato_stt(model), **extra
            )
        except openai.OpenAIError as exc:
            raise translate_error(exc, model) from exc
        uso = _campo(respuesta, "usage")
        informada = _campo(respuesta, "duration") or _campo(uso, "seconds")
        return (
            _campo(respuesta, "text") or "",
            float(informada) if informada else None,
            _coste(respuesta),
        )

    @staticmethod
    def _truncada(texto: str, informada: float | None, real: float | None) -> bool:
        if not real:
            return False
        if informada is not None and informada < MIN_DURATION_RATIO * real:
            return True
        return real >= MIN_SECONDS_FOR_CHARS_CHECK and len(texto.strip()) < MIN_CHARS_PER_SECOND * real

    def transcribe(self, audio: bytes, filename: str) -> TranscriptionResult:
        if not audio:
            raise ProviderError("El audio está vacío.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise ProviderError("El audio supera el límite de 25 MB de OpenRouter.")
        real = measure_audio_duration(audio)
        texto, informada, coste = self._llamar(self.model, audio, filename)
        modelo = self.model
        notas: tuple[str, ...] = ()
        avisos: tuple[str, ...] = ()
        if self._fallback and self._fallback != self.model and self._truncada(texto, informada, real):
            log.warning("transcripción truncada con %s: reintento con %s", self.model, self._fallback)
            notas = ("reintento por transcripción truncada",)
            try:
                texto2, informada2, coste2 = self._llamar(self._fallback, audio, filename)
            except ProviderError as exc:
                avisos = (f"El respaldo de transcripción falló ({exc}); se usa la transcripción original.",)
            else:
                coste = _suma(coste, coste2)
                if not self._truncada(texto2, informada2, real):
                    texto, informada, modelo = texto2, informada2, self._fallback
                else:
                    avisos = ("La transcripción parece incompleta con ambos modelos: se usa la más larga.",)
                    if len(texto2.strip()) > len(texto.strip()):
                        texto, informada, modelo = texto2, informada2, self._fallback
        duracion = real or informada or estimate_duration_s(audio, filename)
        return TranscriptionResult(texto, modelo, float(duracion), coste, notas, avisos)


class OpenRouterTTS:
    """Texto a voz (`/audio/speech`); devuelve MP3 (por defecto la API devolvería PCM)."""

    def __init__(self, api_key: str, model: str, voice: str, client: Any = None) -> None:
        self.model = model
        self._voice = voice
        self._client = make_client(api_key, client, max_retries=1)

    def synthesize(self, text: str) -> SpeechResult:
        if not text.strip():
            raise ProviderError("No hay texto que sintetizar.")
        try:
            respuesta = self._client.audio.speech.create(
                model=self.model, voice=self._voice, input=text, response_format="mp3"
            )
        except openai.OpenAIError as exc:
            raise translate_error(exc, self.model) from exc
        audio = respuesta.content
        if not audio:
            raise ProviderError("OpenRouter devolvió un audio vacío.")
        return SpeechResult(audio, "audio/mpeg", self.model, len(text))


class OpenRouterImage:
    """Generación de imagen con `POST /images` (no es `/images/generations`)."""

    def __init__(self, api_key: str, model: str, client: Any = None) -> None:
        self.model = model
        self._client = make_client(api_key, client, max_retries=0)

    def generate(self, prompt: str) -> ImageResult:
        cuerpo = {
            "model": self.model, "prompt": prompt, "n": 1,
            "aspect_ratio": "4:3", "output_format": "png",
        }
        try:
            respuesta = self._client.post("/images", body=cuerpo, cast_to=object)
        except openai.OpenAIError as exc:
            raise translate_error(exc, self.model) from exc
        datos = _campo(respuesta, "data")
        b64 = _campo(datos[0], "b64_json") if datos else None
        if not b64:
            raise ProviderError("OpenRouter no devolvió ninguna imagen.")
        try:
            imagen = base64.b64decode(b64)
        except ValueError as exc:
            raise ProviderError("OpenRouter devolvió una imagen no válida.") from exc
        mime = _campo(datos[0], "media_type") or "image/png"
        return ImageResult(imagen, mime, self.model, _coste(respuesta))


class OpenRouterEmbeddings:
    """Embeddings multilingües (`POST /embeddings`), p.ej. `baai/bge-m3`, en lotes de 64 textos."""

    def __init__(self, api_key: str, model: str, client: Any = None) -> None:
        self.model = model
        # Idempotente y casi gratis (≈0,0002 USD): más reintentos con espera exponencial ante 429 transitorios
        # del proveedor upstream, que si no degradan la recuperación a solo TF-IDF.
        self._client = make_client(api_key, client, max_retries=EMBEDDINGS_MAX_RETRIES)

    def embed(
        self, texts: Sequence[str], kind: Literal["query", "document"] = "document"
    ) -> EmbeddingResult:
        return embed_in_batches(self._client, self.model, texts, lambda e: translate_error(e, self.model))
