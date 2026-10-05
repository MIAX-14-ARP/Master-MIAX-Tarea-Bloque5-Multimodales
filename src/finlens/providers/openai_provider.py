"""Proveedores reales de OpenAI: voz a texto, texto a voz e imagen (SDK `openai`).

Nombres de modelo y formatos: VERIFICAR en la documentación oficial; OpenAI renueva su catálogo
(p.ej. `gpt-transcribe`, `gpt-4o-mini-tts` o nuevos modelos de imagen) y retira modelos antiguos.
"""
from __future__ import annotations

import base64
import io
import wave
from typing import Any

import openai

from finlens.providers.base import (
    ImageResult,
    ProviderError,
    SpeechResult,
    TranscriptionResult,
)

TIMEOUT_S = 120.0
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # límite de subida de la API de transcripción
BYTES_POR_SEGUNDO_ESTIMADO = 16_000  # ~128 kbps, solo para formatos comprimidos sin duración


def translate_error(exc: openai.OpenAIError, model: str) -> ProviderError:
    """Convierte un error del SDK en un ProviderError con mensaje claro (sin datos sensibles)."""
    if isinstance(exc, openai.AuthenticationError):
        return ProviderError("Clave de OpenAI no válida. Revisa OPENAI_API_KEY.")
    if isinstance(exc, openai.PermissionDeniedError):
        return ProviderError(f"La clave de OpenAI no tiene acceso a esta operación o al modelo {model}.")
    if isinstance(exc, openai.NotFoundError):
        return ProviderError(f"Modelo de OpenAI no encontrado: revisa su variable de entorno ({model}).")
    if isinstance(exc, openai.RateLimitError):
        return ProviderError("Límite de uso o saldo de OpenAI agotado: revisa tu cuenta o inténtalo luego.")
    if isinstance(exc, openai.APITimeoutError):
        return ProviderError("OpenAI no respondió a tiempo.")
    if isinstance(exc, openai.APIConnectionError):
        return ProviderError("No se pudo conectar con OpenAI. Revisa tu conexión a internet.")
    if isinstance(exc, openai.BadRequestError):
        return ProviderError(f"OpenAI rechazó la petición: {exc.message}")
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code >= 500:
            return ProviderError(f"Error del servicio de OpenAI (código {exc.status_code}).")
        return ProviderError(f"Error de OpenAI (código {exc.status_code}): {exc.message}")
    return ProviderError("Error inesperado al llamar a OpenAI.")


def estimate_duration_s(audio: bytes, filename: str) -> float:
    """Duración del audio: exacta para WAV; aproximada por tamaño para el resto de formatos."""
    if filename.lower().endswith(".wav"):
        try:
            with wave.open(io.BytesIO(audio)) as wav:
                return wav.getnframes() / wav.getframerate()
        except (wave.Error, EOFError):
            pass
    return len(audio) / BYTES_POR_SEGUNDO_ESTIMADO


def _cliente(api_key: str, client: Any) -> Any:
    return client or openai.OpenAI(api_key=api_key, timeout=TIMEOUT_S)


class OpenAISTT:
    """Transcripción de audio. Con `whisper-*` se obtiene la duración real (verbose_json)."""

    def __init__(self, api_key: str, model: str, client: Any = None) -> None:
        self.model = model
        self._client = _cliente(api_key, client)

    def transcribe(self, audio: bytes, filename: str) -> TranscriptionResult:
        if not audio:
            raise ProviderError("El audio está vacío.")
        if len(audio) > MAX_AUDIO_BYTES:
            raise ProviderError("El audio supera el límite de 25 MB de OpenAI.")
        kwargs: dict[str, Any] = {"model": self.model, "file": (filename, audio)}
        if self.model.startswith("whisper"):
            kwargs["response_format"] = "verbose_json"
        try:
            respuesta = self._client.audio.transcriptions.create(**kwargs)
        except openai.OpenAIError as exc:
            raise translate_error(exc, self.model) from exc
        duracion = getattr(respuesta, "duration", None) or estimate_duration_s(audio, filename)
        return TranscriptionResult(respuesta.text or "", self.model, float(duracion))


class OpenAITTS:
    """Síntesis de voz; devuelve MP3."""

    def __init__(self, api_key: str, model: str, voice: str, client: Any = None) -> None:
        self.model = model
        self._voice = voice
        self._client = _cliente(api_key, client)

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
            raise ProviderError("OpenAI devolvió un audio vacío.")
        return SpeechResult(audio, "audio/mpeg", self.model, len(text))


class OpenAIImage:
    """Generación de la infografía. Los modelos `gpt-image-*` devuelven la imagen en base64."""

    def __init__(self, api_key: str, model: str, size: str, quality: str, client: Any = None) -> None:
        self.model = model
        self._size = size
        self._quality = quality
        self._client = _cliente(api_key, client)

    def generate(self, prompt: str) -> ImageResult:
        kwargs: dict[str, Any] = {"model": self.model, "prompt": prompt, "n": 1, "size": self._size}
        if self._quality:
            kwargs["quality"] = self._quality
        try:
            respuesta = self._client.images.generate(**kwargs)
        except openai.OpenAIError as exc:
            raise translate_error(exc, self.model) from exc
        datos = respuesta.data[0].b64_json if respuesta.data else None
        if not datos:
            raise ProviderError("OpenAI no devolvió ninguna imagen.")
        return ImageResult(base64.b64decode(datos), "image/png", self.model)
