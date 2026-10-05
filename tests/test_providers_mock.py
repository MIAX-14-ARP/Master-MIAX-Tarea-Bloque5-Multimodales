"""Tests de los proveedores simulados y del registry."""
import io
import wave

import pytest

from finlens.config import Settings
from finlens.providers import base
from finlens.providers.base import ProviderError
from finlens.providers.mock import MockImage, MockLLM, MockSTT, MockTTS, MockVision
from finlens.providers.registry import build_providers

PROTOCOLOS = [
    (MockLLM, base.LLMProvider),
    (MockVision, base.VisionProvider),
    (MockSTT, base.STTProvider),
    (MockTTS, base.TTSProvider),
    (MockImage, base.ImageProvider),
]


@pytest.mark.parametrize(("clase", "protocolo"), PROTOCOLOS)
def test_los_mocks_cumplen_su_protocolo(clase: type, protocolo: type) -> None:
    assert isinstance(clase(), protocolo)


def test_tts_devuelve_un_wav_valido() -> None:
    resultado = MockTTS().synthesize("hola")
    with wave.open(io.BytesIO(resultado.audio)) as wav:
        assert wav.getnframes() > 0
    assert resultado.mime == "audio/wav" and resultado.chars == 4


def test_imagen_devuelve_un_png() -> None:
    resultado = MockImage().generate("infografía")
    assert resultado.image.startswith(b"\x89PNG\r\n\x1a\n") and resultado.mime == "image/png"


def test_stt_devuelve_texto_y_duracion() -> None:
    resultado = MockSTT().transcribe(b"audio", "demo.wav")
    assert resultado.text and resultado.duration_s > 0


def test_stt_rechaza_audio_vacio() -> None:
    with pytest.raises(ProviderError, match="audio"):
        MockSTT().transcribe(b"", "vacio.wav")


def test_vision_rechaza_imagen_vacia() -> None:
    with pytest.raises(ProviderError, match="imagen"):
        MockVision().describe_image(b"", "image/png", "describe")


def test_registry_en_modo_demo_devuelve_mocks() -> None:
    providers = build_providers(Settings(_env_file=None, demo_mode=True))
    assert providers.is_demo
    assert isinstance(providers.llm, MockLLM) and isinstance(providers.image, MockImage)


def test_registry_con_claves_construye_los_proveedores_reales() -> None:
    from finlens.providers.anthropic_provider import AnthropicLLM, AnthropicVision
    from finlens.providers.openai_provider import OpenAIImage, OpenAISTT, OpenAITTS

    settings = Settings(
        _env_file=None, anthropic_api_key="sk-ant-x", openai_api_key="sk-x",
        llm_model="modelo-llm", stt_model="modelo-stt", tts_voice="nova", llm_refusal_fallback=True,
    )
    providers = build_providers(settings)
    assert not providers.is_demo
    assert isinstance(providers.llm, AnthropicLLM) and providers.llm.model == "modelo-llm"
    assert isinstance(providers.vision, AnthropicVision) and isinstance(providers.stt, OpenAISTT)
    assert isinstance(providers.tts, OpenAITTS) and isinstance(providers.image, OpenAIImage)
    assert providers.stt.model == "modelo-stt" and providers.llm._refusal_fallback is True


def test_registry_demo_no_carga_los_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    for nombre in [m for m in sys.modules if m.startswith(("anthropic", "openai", "finlens.providers.a", "finlens.providers.o"))]:
        monkeypatch.delitem(sys.modules, nombre)
    build_providers(Settings(_env_file=None, demo_mode=True))
    assert "anthropic" not in sys.modules and "openai" not in sys.modules
