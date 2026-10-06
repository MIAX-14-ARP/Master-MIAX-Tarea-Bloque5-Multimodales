"""Tests del orquestador con proveedores simulados (cero coste)."""
import json
import time
from dataclasses import replace

import pytest

from finlens.domain.cost import Tariffs
from finlens.domain.guardrails import REMOVED_NOTICE
from finlens.orchestration.pipeline import (
    DEFAULT_QUESTION,
    AnalysisInput,
    PipelineError,
    analyze,
    answer_followup,
    generate_media,
)
from finlens.orchestration.trace import total_cost
from finlens.providers.base import Message, ProviderError, TextResult
from finlens.providers.mock import (
    RESPUESTAS_LLM,
    TRANSCRIPCION_DEMO,
    MockImage,
    MockLLM,
    MockSTT,
    MockTTS,
    MockVision,
)
from finlens.providers.registry import build_mock_providers
from finlens.ui.demo_samples import demo_audio_wav, demo_chart_png, demo_pdf

TARIFAS = Tariffs(3.0, 15.0, 0.006, 15.0, 0.04)


def entrada(**kwargs: object) -> AnalysisInput:
    base = dict(
        pdf=demo_pdf(), question="¿Cómo evolucionó el margen operativo?",
        chart=demo_chart_png(), audio=demo_audio_wav(),
    )
    return AnalysisInput(**{**base, **kwargs})  # type: ignore[arg-type]


def pasos(trace) -> dict:  # type: ignore[no-untyped-def]
    return {s.step: s for s in trace}


# --- Flujo completo -------------------------------------------------------------------------


def test_flujo_completo_en_modo_demo() -> None:
    resultado = analyze(build_mock_providers(), TARIFAS, entrada())
    assert resultado.report.summary and not resultado.guard.blocked
    assert resultado.chart is not None and resultado.transcript == TRANSCRIPCION_DEMO
    assert resultado.document.n_pages == 4
    assert list(pasos(resultado.trace)) == [
        "Ingesta e índice", "Lectura del gráfico", "Transcripción de audio",
        "Recuperación", "Análisis (LLM)", "Guardrails de compliance", "Verificación de cifras",
    ]
    assert all(s.ok for s in resultado.trace)


def test_la_traza_registra_modelo_tiempo_nota_y_coste() -> None:
    resultado = analyze(build_mock_providers(), TARIFAS, entrada())
    p = pasos(resultado.trace)
    assert p["Análisis (LLM)"].model == "mock-llm" and p["Análisis (LLM)"].cost_usd > 0
    assert p["Transcripción de audio"].cost_usd == pytest.approx(45 / 60 * 0.006)
    assert "tendencia alcista" in p["Lectura del gráfico"].note
    assert all(s.seconds >= 0 for s in resultado.trace)
    assert resultado.cost_usd == pytest.approx(total_cost(resultado.trace))
    assert resultado.cost_usd > 0
    assert resultado.total_seconds >= max(s.seconds for s in resultado.trace)


def test_solo_pdf_y_pregunta_tambien_funciona() -> None:
    resultado = analyze(build_mock_providers(), TARIFAS, entrada(chart=None, audio=None))
    assert resultado.chart is None and resultado.transcript is None
    assert "Lectura del gráfico" not in pasos(resultado.trace)


def test_sin_pregunta_se_usa_la_de_defecto() -> None:
    assert analyze(build_mock_providers(), TARIFAS, entrada(question="")).question == DEFAULT_QUESTION


def test_audio_como_pregunta_la_sustituye_y_no_va_como_contexto() -> None:
    capturado: list[str] = []

    class Espia(MockLLM):
        def complete(self, system, messages, max_tokens=2048):  # type: ignore[no-untyped-def]
            capturado.append(messages[0].content)
            return super().complete(system, messages, max_tokens)

    providers = replace(build_mock_providers(), llm=Espia())
    resultado = analyze(providers, TARIFAS, entrada(question="", audio_role="pregunta"))
    assert resultado.question == TRANSCRIPCION_DEMO
    assert capturado[0].count(TRANSCRIPCION_DEMO) == 1  # solo en «Pregunta:», no en <audio>
    assert "<audio>\n(no aportado)" in capturado[0]


# --- Paralelismo ----------------------------------------------------------------------------


def test_vision_y_stt_se_ejecutan_en_paralelo() -> None:
    class VisionLenta(MockVision):
        def describe_image(self, image, mime, prompt):  # type: ignore[no-untyped-def]
            time.sleep(0.4)
            return super().describe_image(image, mime, prompt)

    class SttLento(MockSTT):
        def transcribe(self, audio, filename):  # type: ignore[no-untyped-def]
            time.sleep(0.4)
            return super().transcribe(audio, filename)

    providers = replace(build_mock_providers(), vision=VisionLenta(), stt=SttLento())
    resultado = analyze(providers, TARIFAS, entrada())
    p = pasos(resultado.trace)
    assert p["Lectura del gráfico"].parallel and p["Transcripción de audio"].parallel
    assert p["Lectura del gráfico"].seconds >= 0.4 and p["Transcripción de audio"].seconds >= 0.4
    assert resultado.total_seconds < 0.75  # en serie serían >= 0.8 s solo en estos dos pasos


# --- Degradación y errores ------------------------------------------------------------------


class Roto:
    """Proveedor que siempre falla, para probar la degradación."""

    def describe_image(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise ProviderError("visión caída")

    def transcribe(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise ProviderError("STT caído")

    def synthesize(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise ProviderError("TTS caído")

    def generate(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise ProviderError("imagen caída")


def test_si_falla_vision_o_stt_el_informe_se_entrega_con_aviso() -> None:
    providers = replace(build_mock_providers(), vision=Roto(), stt=Roto())
    resultado = analyze(providers, TARIFAS, entrada())
    assert resultado.report.summary and resultado.chart is None and resultado.transcript is None
    p = pasos(resultado.trace)
    assert not p["Lectura del gráfico"].ok and not p["Transcripción de audio"].ok
    assert any("visión caída" in w for w in resultado.warnings)
    assert any("STT caído" in w for w in resultado.warnings)


def test_un_fallo_inesperado_de_un_paso_opcional_tambien_degrada() -> None:
    class Explota(MockVision):
        def describe_image(self, image, mime, prompt):  # type: ignore[no-untyped-def]
            raise RuntimeError("secreto interno")

    resultado = analyze(replace(build_mock_providers(), vision=Explota()), TARIFAS, entrada())
    assert any("error inesperado (RuntimeError)" in w for w in resultado.warnings)
    assert not any("secreto interno" in w for w in resultado.warnings)


def test_pdf_sin_texto_detiene_el_pipeline_con_mensaje_claro() -> None:
    with pytest.raises(PipelineError, match="no es un PDF|dañado") as info:
        analyze(build_mock_providers(), TARIFAS, entrada(pdf=b"basura"))
    assert info.value.trace[0].step == "Ingesta e índice" and not info.value.trace[0].ok


def test_audio_vacio_degrada_sin_detener_el_informe() -> None:
    resultado = analyze(build_mock_providers(), TARIFAS, entrada(audio=b"", chart=None))
    assert resultado.report.summary and resultado.transcript is None
    assert not pasos(resultado.trace)["Transcripción de audio"].ok
    assert any("audio está vacío" in w for w in resultado.warnings)


def test_llm_que_nunca_devuelve_json_valido_da_error_claro() -> None:
    class Basura(MockLLM):
        def complete(self, system, messages, max_tokens=2048):  # type: ignore[no-untyped-def]
            return TextResult("no soy json", "basura")

    with pytest.raises(PipelineError, match="tras 2 intentos") as info:
        analyze(replace(build_mock_providers(), llm=Basura()), TARIFAS, entrada())
    assert info.value.trace[-1].step == "Análisis (LLM)"


def test_el_llm_que_se_recupera_en_el_reintento_se_anota_en_la_traza() -> None:
    class UnaVezMal(MockLLM):
        n = 0

        def complete(self, system, messages, max_tokens=2048):  # type: ignore[no-untyped-def]
            UnaVezMal.n += 1
            if UnaVezMal.n == 1:
                return TextResult("{roto", "m")
            return super().complete(system, messages, max_tokens)

    resultado = analyze(replace(build_mock_providers(), llm=UnaVezMal()), TARIFAS, entrada())
    assert "con reintento" in pasos(resultado.trace)["Análisis (LLM)"].note


def test_pdf_truncado_por_limite_avisa() -> None:
    resultado = analyze(build_mock_providers(), TARIFAS, entrada(), max_pdf_chars=200)
    assert resultado.document.truncated
    assert any("límite de entrada" in w for w in resultado.warnings)


# --- Compliance -----------------------------------------------------------------------------


class LLMConRecomendacion(MockLLM):
    """LLM que se salta la norma: recomienda comprar y fija precio objetivo."""

    def complete(self, system, messages, max_tokens=2048):  # type: ignore[no-untyped-def]
        resultado = super().complete(system, messages, max_tokens)
        if "ESQUEMA: AnalysisReport" in system:
            datos = json.loads(resultado.text)
            datos["summary"] = "Recomiendo comprar la acción."
            datos["spoken_summary"] = "Precio objetivo de 30 euros."
            datos["correlations"][0]["statement"] = "Hay que vender ya."
            return TextResult(json.dumps(datos), resultado.model, 10, 10)
        return resultado


def test_el_guardrail_retira_recomendaciones_y_avisa() -> None:
    resultado = analyze(replace(build_mock_providers(), llm=LLMConRecomendacion()), TARIFAS, entrada())
    assert resultado.guard.blocked
    assert resultado.report.summary == REMOVED_NOTICE
    assert resultado.report.correlations == []
    assert any("recomendación de inversión" in w for w in resultado.warnings)
    assert "retirado" in pasos(resultado.trace)["Guardrails de compliance"].note


# --- Medios opcionales ----------------------------------------------------------------------


def test_medios_en_modo_demo() -> None:
    providers = build_mock_providers()
    resultado = analyze(providers, TARIFAS, entrada())
    medios = generate_media(providers, TARIFAS, resultado)
    assert medios.audio is not None and medios.image is not None and medios.image_prompt
    assert [s.step for s in medios.trace] == [
        "Resumen en audio", "Prompt de infografía", "Generación de infografía", "Composición de infografía",
    ]
    assert all(s.parallel for s in medios.trace) and not medios.warnings
    assert medios.cost_usd > 0
    assert medios.illustration is not None and medios.illustration.model == "mock-image"
    assert medios.image.model == "mock-image + composición Python"
    assert medios.image.image != medios.illustration.image and medios.image.image[:4] == b"\x89PNG"


def test_el_analisis_verifica_las_cifras_contra_el_documento() -> None:
    resultado = analyze(build_mock_providers(), TARIFAS, entrada())
    assert [c.status for c in resultado.figure_checks] == ["verificada", "verificada"]
    paso = pasos(resultado.trace)["Verificación de cifras"]
    assert paso.model == "reglas deterministas" and paso.note == "2/2 cifras verificadas"
    assert not any("no encontradas" in w for w in resultado.warnings)


def test_una_cifra_inventada_genera_aviso() -> None:
    class LLMInventa(MockLLM):
        def complete(self, system, messages, max_tokens=2048):  # type: ignore[no-untyped-def]
            res = super().complete(system, messages, max_tokens)
            if "ESQUEMA: AnalysisReport" in system:
                return TextResult(res.text.replace("18,4 %", "99,9 %"), res.model)
            return res

    providers = replace(build_mock_providers(), llm=LLMInventa())
    resultado = analyze(providers, TARIFAS, entrada())
    assert [c.status for c in resultado.figure_checks] == ["no_encontrada", "verificada"]
    assert any("Margen operativo" in w and "99,9 %" in w for w in resultado.warnings)
    assert pasos(resultado.trace)["Verificación de cifras"].note == "1/2 cifras verificadas"


def test_si_falla_el_tts_se_entrega_la_infografia_con_aviso() -> None:
    providers = replace(build_mock_providers(), tts=Roto())
    medios = generate_media(providers, TARIFAS, analyze(providers, TARIFAS, entrada()))
    assert medios.audio is None and medios.image is not None
    assert any("TTS caído" in w for w in medios.warnings)


def test_si_falla_la_imagen_se_entrega_el_audio_con_aviso() -> None:
    providers = replace(build_mock_providers(), image=Roto())
    medios = generate_media(providers, TARIFAS, analyze(providers, TARIFAS, entrada()))
    # la ilustración falla pero la infografía se compone igualmente con las cifras reales
    assert medios.audio is not None and medios.image is not None and medios.illustration is None
    assert medios.image.model == "composición Python"
    assert any("imagen caída" in w for w in medios.warnings)
    assert any("sin ilustración" in w for w in medios.warnings)


def test_si_fallan_los_dos_medios_el_informe_sigue_disponible() -> None:
    providers = replace(build_mock_providers(), tts=Roto(), image=Roto())
    analisis = analyze(providers, TARIFAS, entrada())
    medios = generate_media(providers, TARIFAS, analisis)
    assert medios.audio is None and medios.image is not None and medios.illustration is None
    assert len(medios.warnings) == 3  # TTS, ilustración y aviso de degradación
    assert analisis.report.summary


def test_el_audio_incluye_el_aviso_legal_hablado() -> None:
    hablado: list[str] = []

    class TtsEspia(MockTTS):
        def synthesize(self, text):  # type: ignore[no-untyped-def]
            hablado.append(text)
            return super().synthesize(text)

    providers = replace(build_mock_providers(), tts=TtsEspia())
    generate_media(providers, TARIFAS, analyze(providers, TARIFAS, entrada()))
    assert "no es asesoramiento" in hablado[0]


def test_audio_omitido_si_el_guion_incumplia_la_norma() -> None:
    providers = replace(build_mock_providers(), llm=LLMConRecomendacion())
    medios = generate_media(providers, TARIFAS, analyze(providers, TARIFAS, entrada()))
    assert medios.audio is None
    assert any("política de no asesoramiento" in w for w in medios.warnings)


def test_imagen_omitida_si_su_prompt_incumplia_la_norma() -> None:
    class PromptMalo(MockLLM):
        def complete(self, system, messages, max_tokens=2048):  # type: ignore[no-untyped-def]
            if "ESQUEMA: InfographicPrompt" in system:
                return TextResult(json.dumps({"prompt": "Infografía con precio objetivo de 30 EUR"}), "m")
            return super().complete(system, messages, max_tokens)

    providers = replace(build_mock_providers(), llm=PromptMalo())
    medios = generate_media(providers, TARIFAS, analyze(providers, TARIFAS, entrada()))
    assert medios.image is not None and medios.illustration is None and medios.image_prompt is None
    assert medios.audio is not None
    assert [s.step for s in medios.trace if not s.ok] == ["Prompt de infografía"]


# --- Chat de seguimiento --------------------------------------------------------------------


def test_chat_de_seguimiento_responde_con_citas_y_traza() -> None:
    providers = build_mock_providers()
    analisis = analyze(providers, TARIFAS, entrada())
    respuesta = answer_followup(providers, TARIFAS, analisis, [], "¿Cuál fue el margen?")
    assert respuesta.answer.grounded and respuesta.answer.citations
    assert respuesta.step.step == "Chat de seguimiento" and respuesta.step.cost_usd > 0


def test_chat_pasa_el_historial_al_llm() -> None:
    longitudes: list[int] = []

    class Espia(MockLLM):
        def complete(self, system, messages, max_tokens=2048):  # type: ignore[no-untyped-def]
            longitudes.append(len(messages))
            return super().complete(system, messages, max_tokens)

    providers = replace(build_mock_providers(), llm=Espia())
    analisis = analyze(providers, TARIFAS, entrada())
    historial = [Message("user", "hola"), Message("assistant", "buenas")]
    answer_followup(providers, TARIFAS, analisis, historial, "¿y la deuda?")
    assert longitudes[-1] == 3


def test_chat_retira_respuestas_con_recomendacion() -> None:
    class ChatMalo(MockLLM):
        def complete(self, system, messages, max_tokens=2048):  # type: ignore[no-untyped-def]
            if "ESQUEMA: ChatAnswer" in system:
                respuesta = {**RESPUESTAS_LLM["ChatAnswer"], "answer": "Te recomiendo comprar ya."}
                return TextResult(json.dumps(respuesta), "m")
            return super().complete(system, messages, max_tokens)

    providers = build_mock_providers()
    analisis = analyze(providers, TARIFAS, entrada())
    respuesta = answer_followup(replace(providers, llm=ChatMalo()), TARIFAS, analisis, [], "¿Compro?")
    assert respuesta.answer.answer == REMOVED_NOTICE and not respuesta.answer.grounded
    assert respuesta.violations


def test_chat_con_llm_invalido_da_error_claro() -> None:
    class Basura(MockLLM):
        def complete(self, system, messages, max_tokens=2048):  # type: ignore[no-untyped-def]
            if "ESQUEMA: ChatAnswer" in system:
                return TextResult("nada", "m")
            return super().complete(system, messages, max_tokens)

    providers = build_mock_providers()
    analisis = analyze(providers, TARIFAS, entrada())
    with pytest.raises(PipelineError, match="tras 2 intentos"):
        answer_followup(replace(providers, llm=Basura()), TARIFAS, analisis, [], "¿?")


def test_omitir_medios_evita_sus_llamadas_y_su_coste() -> None:
    llamadas: list[str] = []

    class TtsEspia(MockTTS):
        def synthesize(self, text):  # type: ignore[no-untyped-def]
            llamadas.append("tts")
            return super().synthesize(text)

    class ImagenEspia(MockImage):
        def generate(self, prompt):  # type: ignore[no-untyped-def]
            llamadas.append("imagen")
            return super().generate(prompt)

    providers = replace(build_mock_providers(), tts=TtsEspia(), image=ImagenEspia())
    analisis = analyze(providers, TARIFAS, entrada())
    ninguno = generate_media(providers, TARIFAS, analisis, with_audio=False, with_image=False)
    assert llamadas == [] and ninguno.trace == () and ninguno.cost_usd == 0

    solo_audio = generate_media(providers, TARIFAS, analisis, with_image=False)
    assert llamadas == ["tts"] and solo_audio.image is None and solo_audio.image_skipped
    assert solo_audio.audio is not None and not solo_audio.trace[0].parallel


def test_si_falla_la_composicion_no_hay_infografia(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from finlens.orchestration import pipeline

    def rota(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("matplotlib roto")

    monkeypatch.setattr(pipeline, "compose_infographic", rota)
    providers = build_mock_providers()
    medios = generate_media(providers, TARIFAS, analyze(providers, TARIFAS, entrada()))
    assert medios.image is None and medios.audio is not None
    assert [s.step for s in medios.trace if not s.ok] == ["Composición de infografía"]


def test_el_coste_real_del_proveedor_sustituye_a_la_tarifa() -> None:
    class LLMConCoste(MockLLM):
        def complete(self, system, messages, max_tokens=2048):  # type: ignore[no-untyped-def]
            res = super().complete(system, messages, max_tokens)
            return replace(res, cost_usd=0.5)

    providers = replace(build_mock_providers(), llm=LLMConCoste())
    resultado = analyze(providers, TARIFAS, entrada())
    assert pasos(resultado.trace)["Análisis (LLM)"].cost_usd == 0.5
