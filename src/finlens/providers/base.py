"""Contratos (Protocols) de la capa de modelos de IA.

La lógica de negocio (domain/, orchestration/) solo depende de este módulo;
los SDK (anthropic, openai) viven únicamente en las implementaciones de providers/.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, Sequence, runtime_checkable


class ProviderError(Exception):
    """Fallo controlado de un proveedor (red, cuota, respuesta inválida...)."""


@dataclass(frozen=True)
class Message:
    """Mensaje de una conversación con el LLM."""

    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class TextResult:
    """Respuesta de texto de un LLM o de un modelo de visión, con su consumo."""

    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass(frozen=True)
class TranscriptionResult:
    """Resultado de transcribir un audio."""

    text: str
    model: str
    duration_s: float = 0.0


@dataclass(frozen=True)
class SpeechResult:
    """Audio sintetizado a partir de un texto."""

    audio: bytes
    mime: str
    model: str
    chars: int = 0


@dataclass(frozen=True)
class ImageResult:
    """Imagen generada a partir de un prompt."""

    image: bytes
    mime: str
    model: str


@runtime_checkable
class LLMProvider(Protocol):
    """Razonamiento y síntesis de texto (también chat de seguimiento)."""

    def complete(
        self, system: str, messages: Sequence[Message], max_tokens: int = 2048
    ) -> TextResult: ...


@runtime_checkable
class VisionProvider(Protocol):
    """Lectura de una imagen (gráfico de velas) guiada por un prompt."""

    def describe_image(self, image: bytes, mime: str, prompt: str) -> TextResult: ...


@runtime_checkable
class STTProvider(Protocol):
    """Voz a texto."""

    def transcribe(self, audio: bytes, filename: str) -> TranscriptionResult: ...


@runtime_checkable
class TTSProvider(Protocol):
    """Texto a voz."""

    def synthesize(self, text: str) -> SpeechResult: ...


@runtime_checkable
class ImageProvider(Protocol):
    """Texto a imagen (infografía)."""

    def generate(self, prompt: str) -> ImageResult: ...


@dataclass(frozen=True)
class Providers:
    """Conjunto de proveedores que recibe el orquestador (reales o simulados)."""

    llm: LLMProvider
    vision: VisionProvider
    stt: STTProvider
    tts: TTSProvider
    image: ImageProvider
    is_demo: bool = False
