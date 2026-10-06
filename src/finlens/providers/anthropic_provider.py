"""Proveedores reales de Anthropic: LLM de texto y modelo de visión (SDK `anthropic`).

Notas de uso de la API (verificar en la documentación oficial; cambian con los modelos):
- Los modelos recientes no admiten `temperature`/`top_p` ni prefill, por lo que no se envían.
- El pensamiento comparte presupuesto con la respuesta: se reserva un mínimo de `max_tokens`
  y una respuesta cortada por límite se trata como error, no como JSON a medias.
"""
from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

import anthropic

from finlens.providers.base import Message, ProviderError, TextResult
from finlens.providers.media import detect_image_mime

DEFAULT_MIN_OUTPUT_TOKENS = 4000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
TIMEOUT_S = 120.0


def translate_error(exc: anthropic.APIError, model: str) -> ProviderError:
    """Convierte un error del SDK en un ProviderError con mensaje claro (sin datos sensibles)."""
    if isinstance(exc, anthropic.AuthenticationError):
        return ProviderError("Clave de Anthropic no válida. Revisa ANTHROPIC_API_KEY.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return ProviderError("La clave de Anthropic no tiene permisos para esta operación.")
    if isinstance(exc, anthropic.NotFoundError):
        return ProviderError(f"Modelo de Anthropic no encontrado: revisa LLM_MODEL/VISION_MODEL ({model}).")
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderError("Límite de uso de Anthropic alcanzado: inténtalo de nuevo en unos segundos.")
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderError("Anthropic no respondió a tiempo.")
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderError("No se pudo conectar con Anthropic. Revisa tu conexión a internet.")
    if isinstance(exc, anthropic.BadRequestError):
        return ProviderError(f"Anthropic rechazó la petición: {exc.message}")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:
            return ProviderError(f"Error del servicio de Anthropic (código {exc.status_code}).")
        return ProviderError(f"Error de Anthropic (código {exc.status_code}): {exc.message}")
    return ProviderError("Error inesperado al llamar a Anthropic.")


class _AnthropicBase:
    """Lógica común: construcción del cliente, envío, y validación de la respuesta."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        effort: str = "medium",
        refusal_fallback: bool = False,
        min_output_tokens: int = DEFAULT_MIN_OUTPUT_TOKENS,
        client: Any = None,
    ) -> None:
        self.model = model
        self._effort = effort.strip()
        self._refusal_fallback = refusal_fallback
        self._min_output_tokens = min_output_tokens
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=TIMEOUT_S)

    def _send(self, system: str, messages: list[dict[str, Any]], max_tokens: int) -> TextResult:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max(max_tokens, self._min_output_tokens),
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if self._effort:
            kwargs["output_config"] = {"effort": self._effort}
        try:
            if self._refusal_fallback:
                respuesta = self._client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **kwargs
                )
            else:
                respuesta = self._client.messages.create(**kwargs)
        except anthropic.APIError as exc:
            raise translate_error(exc, self.model) from exc
        return self._to_result(respuesta)

    @staticmethod
    def _to_result(respuesta: Any) -> TextResult:
        if respuesta.stop_reason == "refusal":
            raise ProviderError("El modelo rechazó la solicitud por sus políticas de seguridad.")
        if respuesta.stop_reason == "max_tokens":
            raise ProviderError("La respuesta del modelo se cortó por límite de tokens.")
        texto = "".join(b.text for b in respuesta.content if b.type == "text")
        if not texto.strip():
            raise ProviderError("El modelo devolvió una respuesta vacía.")
        uso = respuesta.usage
        entrada = (
            (uso.input_tokens or 0)
            + (getattr(uso, "cache_creation_input_tokens", 0) or 0)
            + (getattr(uso, "cache_read_input_tokens", 0) or 0)
        )
        return TextResult(texto, respuesta.model, entrada, uso.output_tokens or 0)


class AnthropicLLM(_AnthropicBase):
    """LLM de razonamiento y síntesis (también el chat de seguimiento)."""

    def complete(
        self, system: str, messages: Sequence[Message], max_tokens: int = 2048
    ) -> TextResult:
        mensajes = [{"role": m.role, "content": m.content} for m in messages]
        return self._send(system, mensajes, max_tokens)


class AnthropicVision(_AnthropicBase):
    """Lectura de un gráfico con el modelo multimodal."""

    def describe_image(self, image: bytes, mime: str, prompt: str) -> TextResult:
        if not image:
            raise ProviderError("La imagen está vacía.")
        real = detect_image_mime(image)  # la firma manda: el tipo declarado puede ser erróneo
        if real is None:
            raise ProviderError("La imagen está dañada o no es PNG, JPEG, GIF ni WebP.")
        contenido = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": real,
                    "data": base64.standard_b64encode(image).decode("ascii"),
                },
            },
            {"type": "text", "text": prompt},
        ]
        return self._send("", [{"role": "user", "content": contenido}], 2048)
