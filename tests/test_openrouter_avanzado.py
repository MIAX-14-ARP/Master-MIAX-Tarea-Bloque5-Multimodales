"""OpenRouter: razonamiento, STT truncado, embeddings y pruebas a nivel HTTP (httpx2.MockTransport).

El SDK `openai` 3.x usa httpx2, no httpx.
"""
import base64
import json
from types import SimpleNamespace

import httpx2 as httpx
import openai
import pytest

from finlens.providers import base
from finlens.providers.base import Message, ProviderError
from finlens.providers.media import silent_wav
from finlens.providers.openrouter_provider import (
    BASE_URL,
    OpenRouterEmbeddings,
    OpenRouterImage,
    OpenRouterLLM,
    OpenRouterSTT,
    OpenRouterTTS,
    translate_error,
)

AUDIO_20S = silent_wav(20, 8000)  # duración real medible: 20 s


def respuesta_chat(texto="{}", finish="stop", uso=None):
    uso = uso or SimpleNamespace(prompt_tokens=1, completion_tokens=2, cost=0.01)
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=texto))],
        usage=uso, model="vendor/m",
    )


class Registro:
    """Callable que anota las llamadas y devuelve las respuestas en orden (o lanza excepciones)."""

    def __init__(self, *respuestas):
        self.llamadas: list[dict] = []
        self._cola = list(respuestas)

    def __call__(self, **kwargs):
        self.llamadas.append(kwargs)
        r = self._cola.pop(0) if len(self._cola) > 1 else self._cola[0]
        if isinstance(r, Exception):
            raise r
        return r


def cliente_chat(*respuestas):
    registro = Registro(*respuestas)
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=registro))), registro


def cliente_stt(*respuestas):
    registro = Registro(*respuestas)
    return SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=registro))), registro


def estado(codigo, cuerpo=None):
    return openai.APIStatusError(
        "x", response=httpx.Response(codigo, request=httpx.Request("POST", "https://x")), body=cuerpo
    )


# --- Razonamiento ---------------------------------------------------------------------------


def test_envia_reasoning_effort_y_el_minimo_de_max_tokens() -> None:
    cliente, reg = cliente_chat(respuesta_chat())
    llm = OpenRouterLLM("k", "m", client=cliente, reasoning_effort="low", min_output_tokens=4000)
    llm.complete("s", [Message("user", "x")], max_tokens=2048)
    llm.complete("s", [Message("user", "x")], max_tokens=9000)
    assert reg.llamadas[0]["max_tokens"] == 4000 and reg.llamadas[1]["max_tokens"] == 9000
    assert reg.llamadas[0]["extra_body"] == {"reasoning": {"effort": "low"}}


def test_sin_esfuerzo_no_se_envia_extra_body() -> None:
    cliente, reg = cliente_chat(respuesta_chat())
    OpenRouterLLM("k", "m", client=cliente).complete("s", [Message("user", "x")], max_tokens=10)
    assert "extra_body" not in reg.llamadas[0] and reg.llamadas[0]["max_tokens"] == 10


def test_registra_los_tokens_de_razonamiento() -> None:
    uso = SimpleNamespace(
        prompt_tokens=1, completion_tokens=900, cost=0.01,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=700),
    )
    cliente, _ = cliente_chat(respuesta_chat(uso=uso))
    assert OpenRouterLLM("k", "m", client=cliente).complete("s", [Message("user", "x")]).reasoning_tokens == 700


def test_una_respuesta_cortada_conserva_el_coste_ya_cobrado() -> None:
    uso = SimpleNamespace(
        prompt_tokens=1, completion_tokens=50, cost=0.03,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=50),
    )
    cliente, _ = cliente_chat(respuesta_chat(texto="", finish="length", uso=uso))
    with pytest.raises(ProviderError, match="razonamiento: 50") as info:
        OpenRouterLLM("k", "m", client=cliente).complete("s", [Message("user", "x")])
    assert info.value.cost_usd == 0.03


def test_el_detalle_del_error_se_trunca_y_no_vuelca_el_cuerpo() -> None:
    cuerpo = {"error": {"message": "a" * 500, "metadata": {"raw": "secreto-upstream"}}}
    texto = str(translate_error(estado(400, cuerpo), "m"))
    assert len(texto) < 300 and "secreto-upstream" not in texto and texto.endswith("…")
    assert "sin detalle" in str(translate_error(estado(400), "m"))


# --- STT truncado ---------------------------------------------------------------------------


def test_stt_truncado_reintenta_con_el_modelo_de_respaldo() -> None:
    corto = SimpleNamespace(text="hola", duration=2.0, usage=SimpleNamespace(cost=0.01))
    completo = SimpleNamespace(text="x" * 200, usage=SimpleNamespace(cost=0.02, input_tokens=5))
    cliente, reg = cliente_stt(corto, completo)
    stt = OpenRouterSTT(
        "k", "openai/whisper-large-v3", client=cliente, fallback_model="openai/gpt-4o-mini-transcribe"
    )
    r = stt.transcribe(AUDIO_20S, "a.wav")
    assert [c["model"] for c in reg.llamadas] == ["openai/whisper-large-v3", "openai/gpt-4o-mini-transcribe"]
    assert reg.llamadas[0]["response_format"] == "verbose_json" and reg.llamadas[1]["response_format"] == "json"
    assert r.text == "x" * 200 and r.model == "openai/gpt-4o-mini-transcribe"
    assert r.notes == ("reintento por transcripción truncada",) and r.warnings == ()
    assert r.cost_usd == pytest.approx(0.03) and r.duration_s == pytest.approx(20.0)


def test_stt_si_el_respaldo_tambien_es_corto_se_queda_con_la_mejor_y_avisa() -> None:
    cliente, _ = cliente_stt(
        SimpleNamespace(text="hola", duration=2.0), SimpleNamespace(text="hola que tal", duration=3.0)
    )
    r = OpenRouterSTT("k", "m", client=cliente, fallback_model="f").transcribe(AUDIO_20S, "a.wav")
    assert r.text == "hola que tal" and r.model == "f" and "incompleta" in r.warnings[0]


def test_stt_sin_respaldo_o_completo_no_reintenta() -> None:
    cliente, reg = cliente_stt(SimpleNamespace(text="hola", duration=2.0))
    OpenRouterSTT("k", "m", client=cliente, fallback_model="").transcribe(AUDIO_20S, "a.wav")
    assert len(reg.llamadas) == 1
    cliente, reg = cliente_stt(SimpleNamespace(text="y" * 300, duration=20.0))
    r = OpenRouterSTT("k", "m", client=cliente, fallback_model="f").transcribe(AUDIO_20S, "a.wav")
    assert len(reg.llamadas) == 1 and r.notes == ()


def test_stt_detecta_truncado_por_caracteres_aunque_la_duracion_sea_correcta() -> None:
    cliente, reg = cliente_stt(SimpleNamespace(text="poco", duration=20.0), SimpleNamespace(text="z" * 200))
    r = OpenRouterSTT("k", "m", client=cliente, fallback_model="f").transcribe(AUDIO_20S, "a.wav")
    assert len(reg.llamadas) == 2 and r.text == "z" * 200


def test_stt_usa_usage_seconds_si_no_hay_duration() -> None:
    cliente, _ = cliente_stt(SimpleNamespace(text="y" * 300, usage=SimpleNamespace(seconds=20.0)))
    r = OpenRouterSTT("k", "m", client=cliente, fallback_model="f").transcribe(b"no medible", "a.mp3")
    assert r.duration_s == 20.0 and r.notes == ()


def test_stt_el_fallo_del_respaldo_conserva_la_original_con_aviso() -> None:
    cliente, _ = cliente_stt(SimpleNamespace(text="hola", duration=2.0), estado(500))
    r = OpenRouterSTT("k", "m", client=cliente, fallback_model="f").transcribe(AUDIO_20S, "a.wav")
    assert r.text == "hola" and "respaldo" in r.warnings[0]


# --- Embeddings -----------------------------------------------------------------------------


def test_embeddings_en_lotes_de_64_con_coste_y_orden() -> None:
    llamadas = []

    def crear(**kw):
        llamadas.append(kw)
        datos = [
            SimpleNamespace(index=i, embedding=[float(len(t)), 1.0])
            for i, t in reversed(list(enumerate(kw["input"])))
        ]
        return SimpleNamespace(data=datos, usage=SimpleNamespace(prompt_tokens=len(kw["input"]), cost=0.001))

    emb = OpenRouterEmbeddings(
        "k", "baai/bge-m3", client=SimpleNamespace(embeddings=SimpleNamespace(create=crear))
    )
    r = emb.embed(["a" * (i + 1) for i in range(130)], "document")
    assert [len(c["input"]) for c in llamadas] == [64, 64, 2] and llamadas[0]["model"] == "baai/bge-m3"
    assert [v[0] for v in r.vectors] == [float(i + 1) for i in range(130)]  # orden restaurado
    assert r.tokens == 130 and r.cost_usd == pytest.approx(0.003) and r.model == "baai/bge-m3"
    assert isinstance(emb, base.EmbeddingProvider) and emb.embed([]).vectors == []


def test_embeddings_con_numero_de_vectores_incoherente_es_error() -> None:
    crear = Registro(SimpleNamespace(data=[], usage=None))
    with pytest.raises(ProviderError, match="número de vectores"):
        OpenRouterEmbeddings("k", "m", client=SimpleNamespace(embeddings=SimpleNamespace(create=crear))).embed(["a"])


# --- A nivel HTTP (httpx2.MockTransport) -------------------------------------------------------


def cliente_http(manejador):
    http = httpx.Client(transport=httpx.MockTransport(manejador))
    return openai.OpenAI(api_key="clave-falsa", base_url=BASE_URL, http_client=http, max_retries=0)


def test_http_chat_ruta_cuerpo_json_y_cabeceras() -> None:
    vistas = []

    def manejador(peticion):
        vistas.append(peticion)
        return httpx.Response(200, json={
            "id": "x", "object": "chat.completion", "created": 1, "model": "vendor/m",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7, "cost": 0.002,
                      "completion_tokens_details": {"reasoning_tokens": 2}},
        })

    llm = OpenRouterLLM(
        "k", "vendor/m", client=cliente_http(manejador), reasoning_effort="low", min_output_tokens=100
    )
    r = llm.complete("sys", [Message("user", "hola")], max_tokens=10)
    (p,) = vistas
    assert p.url.path == "/api/v1/chat/completions" and p.headers["authorization"] == "Bearer clave-falsa"
    cuerpo = json.loads(p.content)
    assert cuerpo["model"] == "vendor/m" and cuerpo["max_tokens"] == 100
    assert cuerpo["reasoning"] == {"effort": "low"}  # extra_body se fusiona en el JSON
    assert cuerpo["messages"][0] == {"role": "system", "content": "sys"}
    assert (r.cost_usd, r.reasoning_tokens, r.model) == (0.002, 2, "vendor/m")


def test_http_stt_es_multipart_y_tts_pide_mp3() -> None:
    vistas = []

    def manejador(peticion):
        vistas.append(peticion)
        if peticion.url.path.endswith("/audio/transcriptions"):
            return httpx.Response(200, json={"text": "hola", "duration": 1.0})
        return httpx.Response(200, content=b"ID3audio", headers={"content-type": "audio/mpeg"})

    cliente = cliente_http(manejador)
    OpenRouterSTT("k", "openai/whisper-large-v3-turbo", client=cliente, language="es").transcribe(b"audio", "a.mp3")
    voz = OpenRouterTTS("k", "hexgrad/kokoro-82m", "ef_dora", client=cliente).synthesize("Hola")
    stt, tts = vistas
    assert stt.url.path == "/api/v1/audio/transcriptions"
    assert stt.headers["content-type"].startswith("multipart/form-data")
    assert b'name="model"' in stt.content and b"openai/whisper-large-v3-turbo" in stt.content
    assert b'name="language"' in stt.content and b'filename="a.mp3"' in stt.content
    assert tts.url.path == "/api/v1/audio/speech"
    assert json.loads(tts.content) == {
        "model": "hexgrad/kokoro-82m", "input": "Hola", "voice": "ef_dora", "response_format": "mp3",
    }
    assert voz.audio == b"ID3audio"


def test_http_imagen_y_embeddings() -> None:
    vistas = []

    def manejador(peticion):
        vistas.append(peticion)
        if peticion.url.path.endswith("/images"):
            return httpx.Response(200, json={
                "data": [{"b64_json": base64.b64encode(b"\x89PNGz").decode(), "media_type": "image/png"}],
                "usage": {"cost": 0.04},
            })
        return httpx.Response(200, json={
            "object": "list", "model": "baai/bge-m3",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
            "usage": {"prompt_tokens": 2, "total_tokens": 2, "cost": 0.0001},
        })

    cliente = cliente_http(manejador)
    img = OpenRouterImage("k", "black-forest-labs/flux.2-klein-4b", client=cliente).generate("fondo")
    emb = OpenRouterEmbeddings("k", "baai/bge-m3", client=cliente).embed(["hola"], "query")
    imagen, embeddings = vistas
    assert imagen.url.path == "/api/v1/images" and json.loads(imagen.content)["aspect_ratio"] == "4:3"
    assert (img.image, img.cost_usd) == (b"\x89PNGz", 0.04)
    assert embeddings.url.path == "/api/v1/embeddings" and json.loads(embeddings.content)["input"] == ["hola"]
    assert emb.vectors == [[0.1, 0.2]] and emb.cost_usd == 0.0001


def test_http_error_402_se_traduce_sin_filtrar_el_cuerpo() -> None:
    def manejador(peticion):
        return httpx.Response(402, json={"error": {"message": "x", "metadata": {"raw": "secreto-upstream"}}})

    with pytest.raises(ProviderError, match="Saldo") as info:
        OpenRouterLLM("k", "m", client=cliente_http(manejador)).complete("s", [Message("user", "x")])
    assert "secreto-upstream" not in str(info.value)


def test_imagen_y_tts_se_construyen_con_pocos_reintentos() -> None:
    assert OpenRouterImage("k", "m")._client.max_retries == 0
    assert OpenRouterTTS("k", "m", "v")._client.max_retries == 1
