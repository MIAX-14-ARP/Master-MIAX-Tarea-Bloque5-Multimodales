"""Selección de proveedores por capacidad según la configuración.

Regla `auto` de cada capacidad: OpenRouter si hay `OPENROUTER_API_KEY`; si no, el proveedor nativo
(Anthropic para llm/visión, OpenAI para stt/tts/imagen) si hay su clave; si no, simulado.
`DEMO_MODE=true` fuerza simulado en todo. Pedir un proveedor sin clave (o que no ofrece esa
capacidad) deja esa capacidad en simulado y lo avisa en `Providers.warnings`.
"""
from __future__ import annotations

import logging
from typing import Any

from finlens.config import Settings
from finlens.providers.base import ProviderInfo, Providers
from finlens.providers.mock import MockEmbeddings, MockImage, MockLLM, MockSTT, MockTTS, MockVision

log = logging.getLogger("finlens.registry")

CAPABILITIES = ("llm", "vision", "stt", "tts", "image", "embeddings")
_NATIVO = {
    "llm": "anthropic", "vision": "anthropic", "stt": "openai", "tts": "openai", "image": "openai",
    "embeddings": "openai",
}
_VALIDOS = ("auto", "openrouter", "anthropic", "openai", "mock")
_CLAVE_ENV = {"openrouter": "OPENROUTER_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


def _hay_clave(settings: Settings, backend: str) -> bool:
    return {
        "openrouter": settings.has_openrouter_key,
        "anthropic": settings.has_anthropic_key,
        "openai": settings.has_openai_key,
    }[backend]


def resolve_backend(settings: Settings, capability: str) -> tuple[str, str | None]:
    """Backend que atiende `capability` y, si se degrada a simulado, el motivo (aviso)."""
    if settings.demo_mode:
        return "mock", None
    pedido = (getattr(settings, f"{capability}_provider") or "auto").strip().lower()
    if pedido not in _VALIDOS:
        return "mock", f"{capability.upper()}_PROVIDER='{pedido}' no es válido: se usa el modo simulado."
    if pedido == "mock":
        return "mock", None
    if pedido == "auto":
        for candidato in ("openrouter", _NATIVO[capability]):
            if _hay_clave(settings, candidato):
                return candidato, None
        return "mock", None
    if pedido not in ("openrouter", _NATIVO[capability]):
        return "mock", (
            f"{pedido} no ofrece la capacidad «{capability}» en FinLens: se usa el modo simulado."
        )
    if not _hay_clave(settings, pedido):
        return "mock", (
            f"{capability.upper()}_PROVIDER={pedido} pero falta {_CLAVE_ENV[pedido]}: "
            f"«{capability}» usa el modo simulado."
        )
    return pedido, None


def _construir(settings: Settings, capability: str, backend: str) -> tuple[Any, str]:
    """Instancia el proveedor de `capability` para `backend`; devuelve (objeto, modelo)."""
    # Importación diferida: el modo demo no necesita cargar los SDK.
    if backend == "mock":
        mocks: dict[str, Any] = {
            "llm": MockLLM, "vision": MockVision, "stt": MockSTT, "tts": MockTTS, "image": MockImage,
            "embeddings": MockEmbeddings,
        }
        objeto = mocks[capability]()
        return objeto, objeto.model
    if backend == "openrouter":
        from finlens.providers import openrouter_provider as orp

        clave = settings.openrouter_api_key.get_secret_value().strip()
        s = settings
        razonamiento = {
            "reasoning_effort": s.openrouter_reasoning_effort,
            "min_output_tokens": s.openrouter_min_output_tokens,
        }
        if capability == "llm":
            return (
                orp.OpenRouterLLM(clave, s.openrouter_llm_model, **razonamiento),
                s.openrouter_llm_model,
            )
        if capability == "vision":
            return (
                orp.OpenRouterVision(clave, s.openrouter_vision_model, **razonamiento),
                s.openrouter_vision_model,
            )
        if capability == "stt":
            return (
                orp.OpenRouterSTT(
                    clave, s.openrouter_stt_model, fallback_model=s.openrouter_stt_fallback_model,
                    language=s.stt_language,
                ),
                s.openrouter_stt_model,
            )
        if capability == "tts":
            return (
                orp.OpenRouterTTS(clave, s.openrouter_tts_model, s.openrouter_tts_voice),
                s.openrouter_tts_model,
            )
        if capability == "image":
            return orp.OpenRouterImage(clave, s.openrouter_image_model), s.openrouter_image_model
        return orp.OpenRouterEmbeddings(clave, s.openrouter_embeddings_model), s.openrouter_embeddings_model
    if backend == "anthropic":
        from finlens.providers.anthropic_provider import AnthropicLLM, AnthropicVision

        clave = settings.anthropic_api_key.get_secret_value().strip()
        opciones: dict[str, Any] = {
            "effort": settings.llm_effort,
            "refusal_fallback": settings.llm_refusal_fallback,
            "min_output_tokens": settings.llm_min_output_tokens,
        }
        if capability == "llm":
            return AnthropicLLM(clave, settings.llm_model, **opciones), settings.llm_model
        return AnthropicVision(clave, settings.vision_model, **opciones), settings.vision_model
    from finlens.providers.openai_provider import OpenAIEmbeddings, OpenAIImage, OpenAISTT, OpenAITTS

    clave = settings.openai_api_key.get_secret_value().strip()
    if capability == "stt":
        return OpenAISTT(clave, settings.stt_model), settings.stt_model
    if capability == "tts":
        return OpenAITTS(clave, settings.tts_model, settings.tts_voice), settings.tts_model
    if capability == "embeddings":
        return OpenAIEmbeddings(clave, settings.embeddings_model), settings.embeddings_model
    return (
        OpenAIImage(clave, settings.image_model, settings.image_size, settings.image_quality),
        settings.image_model,
    )


def build_mock_providers() -> Providers:
    """Proveedores simulados (modo demo y tests)."""
    llm, vision, stt, tts, image = MockLLM(), MockVision(), MockSTT(), MockTTS(), MockImage()
    emb = MockEmbeddings()
    modelos = (llm.model, vision.model, stt.model, tts.model, image.model, emb.model)
    info = tuple(ProviderInfo(c, "mock", m) for c, m in zip(CAPABILITIES, modelos, strict=True))
    return Providers(llm, vision, stt, tts, image, emb, info=info)


def build_providers(settings: Settings) -> Providers:
    """Proveedores que corresponden a `settings`, elegidos por capacidad."""
    objetos: dict[str, Any] = {}
    info: list[ProviderInfo] = []
    avisos: list[str] = []
    for capacidad in CAPABILITIES:
        backend, aviso = resolve_backend(settings, capacidad)
        if aviso:
            avisos.append(aviso)
            log.warning(aviso)
        objeto, modelo = _construir(settings, capacidad, backend)
        objetos[capacidad] = objeto
        info.append(ProviderInfo(capacidad, backend, modelo))
    return Providers(
        objetos["llm"], objetos["vision"], objetos["stt"], objetos["tts"], objetos["image"], objetos["embeddings"],
        info=tuple(info), warnings=tuple(avisos),
    )


def build_real_providers(settings: Settings) -> Providers:
    """Alias de `build_providers` (se conserva por compatibilidad con scripts y tests)."""
    return build_providers(settings)
