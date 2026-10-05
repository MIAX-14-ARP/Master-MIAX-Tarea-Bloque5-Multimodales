"""Selección de proveedores según la configuración: simulados en modo demo, reales si hay claves."""
from __future__ import annotations

from finlens.config import Settings
from finlens.providers.base import Providers
from finlens.providers.mock import MockImage, MockLLM, MockSTT, MockTTS, MockVision


def build_mock_providers() -> Providers:
    """Proveedores simulados (modo demo y tests)."""
    return Providers(MockLLM(), MockVision(), MockSTT(), MockTTS(), MockImage(), is_demo=True)


def build_real_providers(settings: Settings) -> Providers:
    """Proveedores reales: Anthropic (LLM y visión) y OpenAI (STT, TTS e imagen)."""
    # Importación diferida: el modo demo no necesita cargar los SDK.
    from finlens.providers.anthropic_provider import AnthropicLLM, AnthropicVision
    from finlens.providers.openai_provider import OpenAIImage, OpenAISTT, OpenAITTS

    anthropic_key = settings.anthropic_api_key.get_secret_value().strip()
    openai_key = settings.openai_api_key.get_secret_value().strip()
    opciones = {
        "effort": settings.llm_effort,
        "refusal_fallback": settings.llm_refusal_fallback,
    }
    return Providers(
        llm=AnthropicLLM(anthropic_key, settings.llm_model, **opciones),
        vision=AnthropicVision(anthropic_key, settings.vision_model, **opciones),
        stt=OpenAISTT(openai_key, settings.stt_model),
        tts=OpenAITTS(openai_key, settings.tts_model, settings.tts_voice),
        image=OpenAIImage(openai_key, settings.image_model, settings.image_size, settings.image_quality),
        is_demo=False,
    )


def build_providers(settings: Settings) -> Providers:
    """Devuelve los proveedores que corresponden a `settings`."""
    return build_mock_providers() if settings.is_demo else build_real_providers(settings)
