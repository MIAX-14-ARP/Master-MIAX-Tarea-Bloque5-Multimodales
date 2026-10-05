"""El pipeline completo pasa por las clases reales con clientes falsos que imitan al SDK.

Comprueba que prompts, esquemas JSON, extracción de texto, consumo y traza encajan de extremo a
extremo sin gastar nada. No sustituye a los tests de humo en vivo (test_providers_vivo.py).
"""
import base64
import json
import re
from types import SimpleNamespace

from finlens.config import Settings
from finlens.domain.cost import Tariffs
from finlens.orchestration.pipeline import AnalysisInput, analyze, answer_followup, generate_media
from finlens.providers.mock import RESPUESTAS_LLM, TRANSCRIPCION_DEMO
from finlens.providers.registry import build_real_providers
from finlens.ui.demo_samples import demo_audio_wav, demo_chart_png, demo_pdf


class AnthropicFalso:
    """Responde con el JSON del esquema pedido, como lo haría un modelo bien portado."""

    def __init__(self) -> None:
        self.peticiones: list[dict] = []
        self.messages = SimpleNamespace(create=self._crear)

    def _crear(self, **kwargs):
        self.peticiones.append(kwargs)
        sistema = kwargs.get("system", "")
        contenido = kwargs["messages"][-1]["content"]
        texto_usuario = contenido if isinstance(contenido, str) else contenido[-1]["text"]
        esquema = re.search(r"ESQUEMA:\s*(\w+)", sistema + texto_usuario).group(1)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(RESPUESTAS_LLM[esquema]))],
            stop_reason="end_turn", model="claude-falso",
            usage=SimpleNamespace(input_tokens=1000, output_tokens=500),
        )


class OpenAIFalso:
    def __init__(self) -> None:
        self.audio = SimpleNamespace(
            transcriptions=SimpleNamespace(
                create=lambda **kw: SimpleNamespace(text=TRANSCRIPCION_DEMO, duration=30.0)
            ),
            speech=SimpleNamespace(create=lambda **kw: SimpleNamespace(content=b"mp3")),
        )
        self.images = SimpleNamespace(
            generate=lambda **kw: SimpleNamespace(
                data=[SimpleNamespace(b64_json=base64.b64encode(b"\x89PNG").decode())]
            )
        )


def proveedores_reales_falsos():
    anthropic_falso, openai_falso = AnthropicFalso(), OpenAIFalso()
    providers = build_real_providers(Settings(_env_file=None, anthropic_api_key="k", openai_api_key="k"))
    for objeto in (providers.llm, providers.vision):
        objeto._client = anthropic_falso
    for objeto in (providers.stt, providers.tts, providers.image):
        objeto._client = openai_falso
    return providers, anthropic_falso


def test_flujo_completo_con_las_clases_reales() -> None:
    providers, anthropic_falso = proveedores_reales_falsos()
    tarifas = Tariffs(2.0, 10.0, 0.006, 15.0, 0.04)
    entrada = AnalysisInput(
        pdf=demo_pdf(), question="¿margen?", chart=demo_chart_png(), audio=demo_audio_wav()
    )
    resultado = analyze(providers, tarifas, entrada)
    assert resultado.report.summary and resultado.chart and resultado.transcript == TRANSCRIPCION_DEMO
    assert all(s.ok for s in resultado.trace)

    pasos = {s.step: s for s in resultado.trace}
    assert pasos["Análisis (LLM)"].model == "claude-falso"
    assert pasos["Análisis (LLM)"].cost_usd == (1000 * 2.0 + 500 * 10.0) / 1_000_000
    assert pasos["Transcripción de audio"].cost_usd == 30 / 60 * 0.006

    medios = generate_media(providers, tarifas, resultado)
    assert medios.audio.audio == b"mp3" and medios.image.image == b"\x89PNG" and not medios.warnings

    respuesta = answer_followup(providers, tarifas, resultado, [], "¿y la deuda?")
    assert respuesta.answer.grounded

    # la visión envió la imagen y el análisis un único mensaje de usuario con las tres modalidades
    con_imagen = [p for p in anthropic_falso.peticiones if isinstance(p["messages"][0]["content"], list)]
    assert len(con_imagen) == 1 and "system" not in con_imagen[0]
    assert all("output_config" in p and "temperature" not in p for p in anthropic_falso.peticiones)
