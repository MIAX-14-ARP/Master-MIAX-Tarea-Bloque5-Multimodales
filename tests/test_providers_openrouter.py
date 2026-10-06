"""Tests de los proveedores de OpenRouter con clientes falsos (sin red ni claves)."""
import base64
from types import SimpleNamespace

import httpx2 as httpx
import openai
import pytest

from finlens.providers import base
from finlens.providers.base import Message, ProviderError
from finlens.providers.media import solid_png
from finlens.providers.openrouter_provider import (
    BASE_URL,
    OpenRouterImage,
    OpenRouterLLM,
    OpenRouterSTT,
    OpenRouterTTS,
    OpenRouterVision,
    make_client,
)
from finlens.ui.demo_samples import demo_audio_wav


def error_estado(estado: int):
    return openai.APIStatusError(
        "fallo", response=httpx.Response(estado, request=httpx.Request("POST", "https://x")), body=None
    )


class Espia:
    def __init__(self, resultado=None, error=None):
        self.llamadas: list[dict] = []
        self.resultado, self.error = resultado, error

    def __call__(self, *args, **kwargs):
        self.llamadas.append({"args": args, **kwargs})
        if self.error:
            raise self.error
        return self.resultado


def respuesta_chat(texto="{}", finish="stop", uso=None, modelo="vendor/modelo"):
    uso = uso if uso is not None else SimpleNamespace(prompt_tokens=100, completion_tokens=50, cost=0.0123)
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=texto))],
        usage=uso, model=modelo,
    )


def cliente_chat(resultado=None, error=None):
    espia = Espia(resultado or respuesta_chat(), error)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=espia))), espia


def cliente_tts(resultado=None, error=None):
    espia = Espia(resultado, error)
    return SimpleNamespace(audio=SimpleNamespace(speech=SimpleNamespace(create=espia))), espia


# --- LLM y visión ---------------------------------------------------------------------------


def test_llm_envia_system_y_mensajes_y_max_tokens_tal_cual() -> None:
    cliente, espia = cliente_chat()
    llm = OpenRouterLLM("k", "anthropic/claude-sonnet-5.5", client=cliente)
    mensajes = [Message("user", "hola"), Message("assistant", "buenas")]
    resultado = llm.complete("sistema", mensajes, max_tokens=777)
    llamada = espia.llamadas[0]
    assert llamada["model"] == "anthropic/claude-sonnet-5.5" and llamada["max_tokens"] == 777
    assert llamada["messages"] == [
        {"role": "system", "content": "sistema"},
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "buenas"},
    ]
    assert "response_format" not in llamada and "extra_body" not in llamada
    assert (resultado.text, resultado.tokens_in, resultado.tokens_out) == ("{}", 100, 50)
    assert resultado.cost_usd == 0.0123 and resultado.model == "vendor/modelo"
    assert isinstance(llm, base.LLMProvider)


def test_llm_sin_system_no_envia_mensaje_de_sistema() -> None:
    cliente, espia = cliente_chat()
    OpenRouterLLM("k", "m", client=cliente).complete("", [Message("user", "x")])
    assert espia.llamadas[0]["messages"] == [{"role": "user", "content": "x"}]


def test_sin_coste_informado_cost_usd_es_none() -> None:
    cliente, _ = cliente_chat(respuesta_chat(uso=SimpleNamespace(prompt_tokens=1, completion_tokens=2)))
    resultado = OpenRouterLLM("k", "m", client=cliente).complete("s", [Message("user", "x")])
    assert resultado.cost_usd is None


def test_el_uso_puede_ser_un_dict() -> None:
    cliente, _ = cliente_chat(respuesta_chat(uso={"prompt_tokens": 3, "completion_tokens": 4, "cost": 0.5}))
    r = OpenRouterLLM("k", "m", client=cliente).complete("s", [Message("user", "x")])
    assert (r.tokens_in, r.tokens_out, r.cost_usd) == (3, 4, 0.5)


def test_finish_reason_length_y_respuesta_vacia_son_error() -> None:
    casos = (
        (respuesta_chat(finish="length"), "límite de tokens"),
        (respuesta_chat(texto="  "), "vacía"),
        (respuesta_chat(texto=None), "vacía"),
        (SimpleNamespace(choices=[], usage=None, model="m"), "vacía"),
    )
    for resp, patron in casos:
        cliente, _ = cliente_chat(resp)
        with pytest.raises(ProviderError, match=patron):
            OpenRouterLLM("k", "m", client=cliente).complete("s", [Message("user", "x")])


def test_vision_envia_la_imagen_como_data_url_con_el_tipo_real() -> None:
    cliente, espia = cliente_chat()
    png = solid_png(4, 4, (1, 2, 3))
    vision = OpenRouterVision("k", "google/gemini-3.8-flash", client=cliente)
    vision.describe_image(png, "image/jpeg", "describe")
    (mensaje,) = espia.llamadas[0]["messages"]
    texto, imagen = mensaje["content"]
    assert texto == {"type": "text", "text": "describe"}
    assert imagen["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(png).decode()
    assert isinstance(vision, base.VisionProvider)


def test_vision_rechaza_imagen_vacia_o_corrupta_sin_llamar() -> None:
    cliente, espia = cliente_chat()
    vision = OpenRouterVision("k", "m", client=cliente)
    with pytest.raises(ProviderError, match="vacía"):
        vision.describe_image(b"", "image/png", "p")
    with pytest.raises(ProviderError, match="dañada"):
        vision.describe_image(b"basura", "image/png", "p")
    assert espia.llamadas == []


# --- STT ------------------------------------------------------------------------------------


def cliente_stt(resultado=None, error=None):
    por_defecto = SimpleNamespace(text="hola", duration=12.5, usage=SimpleNamespace(cost=0.001))
    espia = Espia(resultado or por_defecto, error)
    return SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=espia))), espia


def test_stt_pide_espanol_y_verbose_json() -> None:
    cliente, espia = cliente_stt()
    stt = OpenRouterSTT("k", "openai/whisper-large-v3-turbo", client=cliente)
    r = stt.transcribe(b"audio", "a.mp3")
    llamada = espia.llamadas[0]
    assert llamada["language"] == "es" and llamada["response_format"] == "verbose_json"
    assert llamada["file"] == ("a.mp3", b"audio") and llamada["model"] == "openai/whisper-large-v3-turbo"
    assert (r.text, r.duration_s, r.cost_usd) == ("hola", 12.5, 0.001)
    assert isinstance(stt, base.STTProvider)


def test_stt_estima_la_duracion_si_no_viene() -> None:
    cliente, _ = cliente_stt(SimpleNamespace(text="x"))
    r = OpenRouterSTT("k", "m", client=cliente).transcribe(demo_audio_wav(), "demo.wav")
    assert r.duration_s == pytest.approx(2.0) and r.cost_usd is None


def test_stt_valida_audio_vacio_y_grande() -> None:
    cliente, espia = cliente_stt()
    stt = OpenRouterSTT("k", "m", client=cliente)
    with pytest.raises(ProviderError, match="vacío"):
        stt.transcribe(b"", "a.wav")
    with pytest.raises(ProviderError, match="25 MB"):
        stt.transcribe(b"x" * (25 * 1024 * 1024 + 1), "a.wav")
    assert espia.llamadas == []


# --- TTS ------------------------------------------------------------------------------------


def test_tts_pide_mp3_y_devuelve_audio_mpeg() -> None:
    cliente, espia = cliente_tts(SimpleNamespace(content=b"ID3"))
    tts = OpenRouterTTS("k", "hexgrad/kokoro-82m", "ef_dora", client=cliente)
    r = tts.synthesize("Hola")
    assert espia.llamadas[0] == {
        "args": (), "model": "hexgrad/kokoro-82m", "voice": "ef_dora", "input": "Hola",
        "response_format": "mp3",
    }
    assert (r.audio, r.mime, r.chars) == (b"ID3", "audio/mpeg", 4)
    assert isinstance(tts, base.TTSProvider)
    with pytest.raises(ProviderError, match="texto"):
        tts.synthesize(" ")


def test_tts_con_audio_vacio_es_error() -> None:
    cliente, _ = cliente_tts(SimpleNamespace(content=b""))
    with pytest.raises(ProviderError, match="vacío"):
        OpenRouterTTS("k", "m", "v", client=cliente).synthesize("x")


# --- Imagen ---------------------------------------------------------------------------------


def cliente_img(resultado=None, error=None):
    espia = Espia(resultado, error)
    return SimpleNamespace(post=espia), espia


def test_imagen_usa_images_con_aspect_ratio_y_decodifica() -> None:
    cuerpo = {
        "data": [{"b64_json": base64.b64encode(b"\x89PNGx").decode(), "media_type": "image/png"}],
        "usage": {"cost": 0.04},
    }
    cliente, espia = cliente_img(cuerpo)
    img = OpenRouterImage("k", "black-forest-labs/flux.2-klein-4b", client=cliente)
    r = img.generate("ilustración")
    llamada = espia.llamadas[0]
    assert llamada["args"] == ("/images",) and llamada["cast_to"] is object
    assert llamada["body"] == {
        "model": "black-forest-labs/flux.2-klein-4b", "prompt": "ilustración", "n": 1,
        "aspect_ratio": "4:3", "output_format": "png",
    }
    assert (r.image, r.mime, r.cost_usd) == (b"\x89PNGx", "image/png", 0.04)
    assert isinstance(img, base.ImageProvider)


def test_imagen_sin_datos_es_error() -> None:
    for cuerpo in ({"data": []}, {"data": [{"b64_json": ""}]}, {}):
        cliente, _ = cliente_img(cuerpo)
        with pytest.raises(ProviderError, match="ninguna imagen"):
            OpenRouterImage("k", "m", client=cliente).generate("p")


# --- Errores y cliente ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "fragmento"),
    [
        (error_estado(401), "OPENROUTER_API_KEY"),
        (error_estado(402), "Saldo de OpenRouter insuficiente"),
        (error_estado(403), "denegó"),
        (error_estado(404), "no encontrado"),
        (error_estado(413), "demasiado grande"),
        (error_estado(429), "Límite de uso"),
        (error_estado(400), "código 400"),
        (error_estado(503), "código 503"),
        (openai.APIConnectionError(request=httpx.Request("POST", "https://x")), "conectar"),
        (openai.APITimeoutError(request=httpx.Request("POST", "https://x")), "a tiempo"),
    ],
)
def test_los_errores_http_se_traducen_en_los_cinco_proveedores(error: Exception, fragmento: str) -> None:
    png = solid_png(2, 2, (0, 0, 0))
    llamadas = [
        lambda: OpenRouterLLM("k", "m", client=cliente_chat(error=error)[0]).complete(
            "s", [Message("user", "x")]),
        lambda: OpenRouterVision("k", "m", client=cliente_chat(error=error)[0]).describe_image(
            png, "image/png", "p"),
        lambda: OpenRouterSTT("k", "m", client=cliente_stt(error=error)[0]).transcribe(b"a", "a.wav"),
        lambda: OpenRouterTTS("k", "m", "v", client=cliente_tts(error=error)[0]).synthesize("hola"),
        lambda: OpenRouterImage("k", "m", client=cliente_img(error=error)[0]).generate("p"),
    ]
    for llamada in llamadas:
        with pytest.raises(ProviderError, match=fragmento) as info:
            llamada()
        assert "sk-" not in str(info.value)


def test_make_client_apunta_a_openrouter_con_cabecera_de_atribucion() -> None:
    cliente = make_client("clave-falsa")
    assert str(cliente.base_url).rstrip("/") == BASE_URL
    assert cliente.default_headers["X-Title"] == "FinLens"
    sentinela = object()
    assert make_client("k", sentinela) is sentinela
