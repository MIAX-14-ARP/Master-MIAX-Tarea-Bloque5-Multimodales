"""Contratos (Protocols) de la capa de modelos de IA.

La lógica de negocio (domain/, orchestration/) solo depende de este módulo;
los SDK (anthropic, openai) viven únicamente en las implementaciones de providers/.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


class ProviderError(Exception):
    """Fallo controlado de un proveedor (red, cuota, respuesta inválida...).

    `cost_usd` recoge el coste real si la llamada se cobró pese a fallar (p.ej. respuesta cortada).
    """

    def __init__(self, message: str = "", cost_usd: float | None = None) -> None:
        super().__init__(message)
        self.cost_usd = cost_usd


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
    cost_usd: float | None = None  # coste real si el proveedor lo informa (p.ej. OpenRouter)
    reasoning_tokens: int = 0  # tokens de razonamiento (incluidos en tokens_out), si se informan


@dataclass(frozen=True)
class TranscriptionResult:
    """Resultado de transcribir un audio."""

    text: str
    model: str
    duration_s: float = 0.0
    cost_usd: float | None = None
    notes: tuple[str, ...] = ()  # incidencias para la traza (p.ej. reintento por truncado)
    warnings: tuple[str, ...] = ()  # avisos para el usuario


@dataclass(frozen=True)
class SpeechResult:
    """Audio sintetizado a partir de un texto."""

    audio: bytes
    mime: str
    model: str
    chars: int = 0
    cost_usd: float | None = None


@dataclass(frozen=True)
class ImageResult:
    """Imagen generada a partir de un prompt."""

    image: bytes
    mime: str
    model: str
    cost_usd: float | None = None


@dataclass(frozen=True)
class EmbeddingResult:
    """Vectores de embeddings (uno por texto, en el mismo orden) y su consumo."""

    vectors: list[list[float]]
    model: str
    tokens: int = 0
    cost_usd: float | None = None


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


Capability = Literal["llm", "vision", "stt", "tts", "image", "embeddings"]
Backend = Literal["openrouter", "anthropic", "openai", "mock"]


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Embeddings multilingües para la recuperación semántica."""

    def embed(
        self, texts: Sequence[str], kind: Literal["query", "document"] = "document"
    ) -> EmbeddingResult: ...


@dataclass(frozen=True)
class ProviderInfo:
    """Qué backend y modelo atiende una capacidad (para mostrarlo en la UI)."""

    capability: str
    backend: str
    model: str


@dataclass(frozen=True)
class Providers:
    """Conjunto de proveedores que recibe el orquestador (reales o simulados)."""

    llm: LLMProvider
    vision: VisionProvider
    stt: STTProvider
    tts: TTSProvider
    image: ImageProvider
    embeddings: EmbeddingProvider
    info: tuple[ProviderInfo, ...] = ()
    warnings: tuple[str, ...] = ()  # capacidades degradadas a simulado por configuración

    def _backends(self) -> dict[str, str]:
        """Backend por capacidad: de `info` o, si falta, inferido del módulo de cada proveedor."""
        if self.info:
            return {i.capability: i.backend for i in self.info}
        objetos = {
            "llm": self.llm, "vision": self.vision, "stt": self.stt, "tts": self.tts,
            "image": self.image, "embeddings": self.embeddings,
        }
        return {
            c: "mock" if type(o).__module__ == "finlens.providers.mock" else "real"
            for c, o in objetos.items()
        }

    @property
    def mock_capabilities(self) -> tuple[str, ...]:
        """Capacidades atendidas por proveedores simulados."""
        return tuple(c for c, b in self._backends().items() if b == "mock")

    @property
    def is_demo(self) -> bool:
        """True solo si todas las capacidades son simuladas."""
        backends = self._backends()
        return len(self.mock_capabilities) == len(backends)
