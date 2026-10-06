"""Tests de los proveedores de OpenAI con clientes falsos (sin red ni claves)."""
import base64
from types import SimpleNamespace

import httpx2 as httpx
import openai
import pytest

from finlens.providers import base
from finlens.providers.base import ProviderError
from finlens.providers.openai_provider import (
    MAX_AUDIO_BYTES,
    OpenAIImage,
    OpenAISTT,
    OpenAITTS,
    estimate_duration_s,
)
from finlens.ui.demo_samples import demo_audio_wav


def error_http(clase, estado, mensaje="fallo"):
    peticion = httpx.Request("POST", "https://api.openai.com/v1/x")
    return clase(mensaje, response=httpx.Response(estado, request=peticion), body=None)


class Espia:
    """Registra llamadas y devuelve/lanza lo configurado."""

    def __init__(self, resultado=None, error=None):
        self.llamadas: list[dict] = []
        self.resultado, self.error = resultado, error

    def __call__(self, **kwargs):
        self.llamadas.append(kwargs)
        if self.error:
            raise self.error
        return self.resultado


def cliente_stt(resultado=None, error=None):
    espia = Espia(resultado or SimpleNamespace(text="hola mundo", duration=12.5), error)
    return SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=espia))), espia


def cliente_tts(resultado=None, error=None):
    espia = Espia(resultado or SimpleNamespace(content=b"ID3mp3"), error)
    return SimpleNamespace(audio=SimpleNamespace(speech=SimpleNamespace(create=espia))), espia


def cliente_img(resultado=None, error=None):
    espia = Espia(resultado, error)
    return SimpleNamespace(images=SimpleNamespace(generate=espia)), espia


# --- STT ------------------------------------------------------------------------------------


def test_stt_cumple_el_protocolo() -> None:
    assert isinstance(OpenAISTT("k", "whisper-1", client=cliente_stt()[0]), base.STTProvider)


def test_stt_whisper_pide_verbose_json_y_usa_la_duracion_real() -> None:
    cliente, espia = cliente_stt()
    resultado = OpenAISTT("k", "whisper-1", client=cliente).transcribe(b"audio", "llamada.mp3")
    llamada = espia.llamadas[0]
    assert llamada["file"] == ("llamada.mp3", b"audio") and llamada["response_format"] == "verbose_json"
    assert (resultado.text, resultado.duration_s, resultado.model) == ("hola mundo", 12.5, "whisper-1")


def test_stt_con_otros_modelos_no_fuerza_formato_y_estima_la_duracion() -> None:
    cliente, espia = cliente_stt(SimpleNamespace(text="texto"))
    resultado = OpenAISTT("k", "gpt-transcribe", client=cliente).transcribe(b"x" * 32_000, "a.mp3")
    assert "response_format" not in espia.llamadas[0]
    assert resultado.duration_s == pytest.approx(2.0)


def test_stt_valida_audio_vacio_y_demasiado_grande_sin_llamar() -> None:
    cliente, espia = cliente_stt()
    stt = OpenAISTT("k", "whisper-1", client=cliente)
    with pytest.raises(ProviderError, match="vacío"):
        stt.transcribe(b"", "a.wav")
    with pytest.raises(ProviderError, match="25 MB"):
        stt.transcribe(b"x" * (MAX_AUDIO_BYTES + 1), "a.wav")
    assert espia.llamadas == []


def test_duracion_exacta_de_un_wav() -> None:
    assert estimate_duration_s(demo_audio_wav(), "demo.wav") == pytest.approx(2.0)
    assert estimate_duration_s(b"no es un wav", "roto.wav") == pytest.approx(len(b"no es un wav") / 16_000)


# --- TTS ------------------------------------------------------------------------------------


def test_tts_envia_modelo_voz_y_devuelve_mp3() -> None:
    cliente, espia = cliente_tts()
    resultado = OpenAITTS("k", "tts-1", "nova", client=cliente).synthesize("Hola, mundo")
    assert espia.llamadas[0] == {
        "model": "tts-1", "voice": "nova", "input": "Hola, mundo", "response_format": "mp3",
    }
    assert (resultado.audio, resultado.mime, resultado.chars, resultado.model) == (
        b"ID3mp3", "audio/mpeg", 11, "tts-1",
    )
    assert isinstance(OpenAITTS("k", "m", "v", client=cliente), base.TTSProvider)


def test_tts_rechaza_texto_vacio_y_audio_vacio() -> None:
    with pytest.raises(ProviderError, match="texto"):
        OpenAITTS("k", "tts-1", "alloy", client=cliente_tts()[0]).synthesize("  ")
    with pytest.raises(ProviderError, match="vacío"):
        OpenAITTS("k", "tts-1", "alloy", client=cliente_tts(SimpleNamespace(content=b""))[0]).synthesize("hola")


# --- Imagen ---------------------------------------------------------------------------------


def respuesta_imagen(datos: bytes | None):
    b64 = base64.b64encode(datos).decode() if datos else None
    return SimpleNamespace(data=[SimpleNamespace(b64_json=b64)])


def test_imagen_decodifica_el_base64_y_envia_tamano_y_calidad() -> None:
    cliente, espia = cliente_img(respuesta_imagen(b"\x89PNGfake"))
    resultado = OpenAIImage("k", "gpt-image-1", "1024x1024", "medium", client=cliente).generate("una infografía")
    assert espia.llamadas[0] == {
        "model": "gpt-image-1", "prompt": "una infografía", "n": 1, "size": "1024x1024", "quality": "medium",
    }
    assert (resultado.image, resultado.mime, resultado.model) == (b"\x89PNGfake", "image/png", "gpt-image-1")
    assert isinstance(OpenAIImage("k", "m", "s", "q", client=cliente), base.ImageProvider)


def test_imagen_sin_calidad_no_la_envia_y_sin_datos_es_error() -> None:
    cliente, espia = cliente_img(respuesta_imagen(None))
    imagen = OpenAIImage("k", "m", "1024x1024", "", client=cliente)
    with pytest.raises(ProviderError, match="ninguna imagen"):
        imagen.generate("p")
    assert "quality" not in espia.llamadas[0]


# --- Errores --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "fragmento"),
    [
        (error_http(openai.AuthenticationError, 401), "OPENAI_API_KEY"),
        (error_http(openai.PermissionDeniedError, 403), "no tiene acceso"),
        (error_http(openai.NotFoundError, 404), "no encontrado"),
        (error_http(openai.RateLimitError, 429), "saldo"),
        (error_http(openai.BadRequestError, 400, "formato no soportado"), "formato no soportado"),
        (error_http(openai.InternalServerError, 503), "código 503"),
        (openai.APIConnectionError(request=httpx.Request("POST", "https://x")), "conectar"),
        (openai.APITimeoutError(request=httpx.Request("POST", "https://x")), "a tiempo"),
    ],
)
def test_los_errores_del_sdk_se_traducen_en_los_tres_proveedores(error: Exception, fragmento: str) -> None:
    llamadas = [
        lambda: OpenAISTT("k", "whisper-1", client=cliente_stt(error=error)[0]).transcribe(b"a", "a.wav"),
        lambda: OpenAITTS("k", "tts-1", "alloy", client=cliente_tts(error=error)[0]).synthesize("hola"),
        lambda: OpenAIImage("k", "m", "s", "q", client=cliente_img(error=error)[0]).generate("p"),
    ]
    for llamada in llamadas:
        with pytest.raises(ProviderError, match=fragmento) as info:
            llamada()
        assert "sk-" not in str(info.value)
