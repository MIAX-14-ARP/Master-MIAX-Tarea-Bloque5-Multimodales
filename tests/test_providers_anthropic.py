"""Tests del proveedor de Anthropic con un cliente falso (sin red ni claves)."""
import base64
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from finlens.providers.anthropic_provider import (
    FALLBACK_BETA,
    MIN_OUTPUT_TOKENS,
    AnthropicLLM,
    AnthropicVision,
)
from finlens.providers.base import LLMProvider, Message, ProviderError, VisionProvider
from finlens.ui.demo_samples import demo_chart_png


def respuesta(texto="{}", stop="end_turn", entrada=100, salida=50, modelo="claude-x", **extra):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=texto)],
        stop_reason=stop, model=modelo,
        usage=SimpleNamespace(input_tokens=entrada, output_tokens=salida, **extra),
    )


class ClienteFalso:
    """Imita client.messages.create y client.beta.messages.create."""

    def __init__(self, resultado=None, error=None):
        self.llamadas: list[dict] = []
        self._resultado, self._error = resultado or respuesta(), error
        self.messages = SimpleNamespace(create=self._crear)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._crear_beta))

    def _crear(self, **kwargs):
        self.llamadas.append({"beta": False, **kwargs})
        if self._error:
            raise self._error
        return self._resultado

    def _crear_beta(self, **kwargs):
        self.llamadas.append({"beta": True, **kwargs})
        return self._resultado


PNG = demo_chart_png()


def llm(cliente, **kwargs) -> AnthropicLLM:
    return AnthropicLLM("clave", "claude-x", client=cliente, **kwargs)


def error_http(clase, estado, mensaje="fallo"):
    peticion = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return clase(mensaje, response=httpx.Response(estado, request=peticion), body=None)


def test_cumple_los_protocolos() -> None:
    cliente = ClienteFalso()
    assert isinstance(llm(cliente), LLMProvider)
    assert isinstance(AnthropicVision("k", "m", client=cliente), VisionProvider)


def test_envia_system_mensajes_y_esfuerzo_sin_parametros_de_muestreo() -> None:
    cliente = ClienteFalso()
    llm(cliente).complete("sistema", [Message("user", "hola"), Message("assistant", "buenas"), Message("user", "y?")])
    (llamada,) = cliente.llamadas
    assert llamada["system"] == "sistema" and llamada["model"] == "claude-x"
    assert llamada["messages"] == [
        {"role": "user", "content": "hola"}, {"role": "assistant", "content": "buenas"},
        {"role": "user", "content": "y?"},
    ]
    assert llamada["output_config"] == {"effort": "medium"} and llamada["beta"] is False
    for prohibido in ("temperature", "top_p", "top_k", "thinking", "fallbacks"):
        assert prohibido not in llamada


def test_reserva_margen_de_tokens_para_el_pensamiento() -> None:
    cliente = ClienteFalso()
    llm(cliente).complete("s", [Message("user", "x")], max_tokens=2048)
    llm(cliente).complete("s", [Message("user", "x")], max_tokens=20000)
    assert [c["max_tokens"] for c in cliente.llamadas] == [MIN_OUTPUT_TOKENS, 20000]


def test_esfuerzo_vacio_no_se_envia() -> None:
    cliente = ClienteFalso()
    llm(cliente, effort="").complete("s", [Message("user", "x")])
    assert "output_config" not in cliente.llamadas[0]


def test_devuelve_solo_el_texto_y_el_consumo_real() -> None:
    cliente = ClienteFalso(respuesta('{"a": 1}', entrada=10, salida=20, modelo="claude-real",
                                     cache_creation_input_tokens=5, cache_read_input_tokens=None))
    resultado = llm(cliente).complete("s", [Message("user", "x")])
    assert resultado.text == '{"a": 1}' and resultado.model == "claude-real"
    assert (resultado.tokens_in, resultado.tokens_out) == (15, 20)


def test_fallback_por_rechazo_es_opcional_y_usa_la_api_beta() -> None:
    cliente = ClienteFalso()
    llm(cliente, refusal_fallback=True).complete("s", [Message("user", "x")])
    (llamada,) = cliente.llamadas
    assert llamada["beta"] is True and llamada["betas"] == [FALLBACK_BETA] and llamada["fallbacks"] == "default"


@pytest.mark.parametrize(
    ("stop", "fragmento"),
    [("refusal", "políticas de seguridad"), ("max_tokens", "límite de tokens")],
)
def test_paradas_anomalas_son_errores_claros(stop: str, fragmento: str) -> None:
    with pytest.raises(ProviderError, match=fragmento):
        llm(ClienteFalso(respuesta(stop=stop))).complete("s", [Message("user", "x")])


def test_respuesta_vacia_es_error() -> None:
    with pytest.raises(ProviderError, match="vacía"):
        llm(ClienteFalso(respuesta("   "))).complete("s", [Message("user", "x")])


@pytest.mark.parametrize(
    ("error", "fragmento"),
    [
        (error_http(anthropic.AuthenticationError, 401), "ANTHROPIC_API_KEY"),
        (error_http(anthropic.PermissionDeniedError, 403), "permisos"),
        (error_http(anthropic.NotFoundError, 404), "claude-x"),
        (error_http(anthropic.RateLimitError, 429), "Límite de uso"),
        (error_http(anthropic.BadRequestError, 400, "campo inválido"), "campo inválido"),
        (error_http(anthropic.InternalServerError, 500), "código 500"),
        (anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")), "conectar"),
        (anthropic.APITimeoutError(request=httpx.Request("POST", "https://x")), "a tiempo"),
    ],
)
def test_los_errores_del_sdk_se_traducen_a_mensajes_claros(error: Exception, fragmento: str) -> None:
    with pytest.raises(ProviderError, match=fragmento) as info:
        llm(ClienteFalso(error=error)).complete("s", [Message("user", "x")])
    assert "sk-" not in str(info.value)


def test_vision_envia_la_imagen_en_base64_antes_del_texto() -> None:
    cliente = ClienteFalso()
    AnthropicVision("k", "claude-x", client=cliente).describe_image(PNG, "image/png", "describe")
    (llamada,) = cliente.llamadas
    bloques = llamada["messages"][0]["content"]
    assert [b["type"] for b in bloques] == ["image", "text"]
    assert bloques[0]["source"] == {
        "type": "base64", "media_type": "image/png",
        "data": base64.standard_b64encode(PNG).decode(),
    }
    assert bloques[1]["text"] == "describe" and "system" not in llamada


def test_vision_usa_el_tipo_real_de_la_imagen_aunque_el_declarado_sea_otro() -> None:
    cliente = ClienteFalso()
    AnthropicVision("k", "m", client=cliente).describe_image(PNG, "image/jpeg", "d")
    assert cliente.llamadas[0]["messages"][0]["content"][0]["source"]["media_type"] == "image/png"


def test_vision_valida_la_entrada_antes_de_llamar() -> None:
    cliente = ClienteFalso()
    vision = AnthropicVision("k", "m", client=cliente)
    with pytest.raises(ProviderError, match="vacía"):
        vision.describe_image(b"", "image/png", "d")
    for corrupta in (b"no soy una imagen", PNG[:6], b"%PDF-1.4 ..."):
        with pytest.raises(ProviderError, match="dañada o no es PNG"):
            vision.describe_image(corrupta, "image/png", "d")
    assert cliente.llamadas == []


def test_clave_invalida_detiene_el_pipeline_con_un_mensaje_accionable() -> None:
    """Una clave de Anthropic inválida llega a la UI como mensaje claro, no como traza de error."""
    from dataclasses import replace

    from finlens.domain.cost import Tariffs
    from finlens.orchestration.pipeline import AnalysisInput, PipelineError, analyze
    from finlens.providers.registry import build_mock_providers
    from finlens.ui.demo_samples import demo_pdf

    cliente = ClienteFalso(error=error_http(anthropic.AuthenticationError, 401))
    providers = replace(build_mock_providers(), llm=llm(cliente))
    with pytest.raises(PipelineError, match="ANTHROPIC_API_KEY") as info:
        analyze(providers, Tariffs(2, 10, 0.006, 15, 0.04), AnalysisInput(pdf=demo_pdf()))
    assert info.value.trace[-1].step == "Análisis (LLM)" and not info.value.trace[-1].ok
