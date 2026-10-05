"""Tests de construcción de prompts y mensajes."""
from finlens.domain import prompts
from finlens.domain.ingest import Chunk
from finlens.domain.rag import Retrieved
from finlens.domain.schemas import AnalysisReport, ChartReading
from finlens.providers.base import Message
from finlens.providers.mock import RESPUESTAS_LLM

FRAGMENTOS = [Retrieved(Chunk(3, "El margen operativo fue del 18 %."), 0.9)]
INFORME = AnalysisReport.model_validate(RESPUESTAS_LLM["AnalysisReport"])
GRAFICO = ChartReading.model_validate(RESPUESTAS_LLM["ChartReading"])


def test_analisis_incluye_pregunta_y_las_tres_modalidades() -> None:
    (mensaje,) = prompts.build_analysis_messages("¿Qué pasó con el margen?", FRAGMENTOS, GRAFICO, "audio dice")
    assert mensaje.role == "user"
    assert "¿Qué pasó con el margen?" in mensaje.content
    assert "[documento p.3]" in mensaje.content
    assert "<grafico>" in mensaje.content and "alcista" in mensaje.content
    assert "audio dice" in mensaje.content


def test_modalidades_ausentes_se_marcan_como_no_aportadas() -> None:
    (mensaje,) = prompts.build_analysis_messages("pregunta", [])
    assert mensaje.content.count("(no aportado)") == 3


def test_la_transcripcion_se_limita_en_longitud() -> None:
    (mensaje,) = prompts.build_analysis_messages("p", [], transcript="x" * 50_000)
    assert mensaje.content.count("x") == prompts.MAX_TRANSCRIPT_CHARS


def test_chat_conserva_el_historial_y_anade_contexto() -> None:
    historial = [Message("user", "hola"), Message("assistant", "buenas")]
    mensajes = prompts.build_chat_messages(historial, "¿y la deuda?", INFORME, FRAGMENTOS)
    assert mensajes[:2] == historial and len(mensajes) == 3
    assert "<informe>" in mensajes[-1].content and "¿y la deuda?" in mensajes[-1].content


def test_infografia_parte_del_informe() -> None:
    (mensaje,) = prompts.build_infographic_messages(INFORME)
    assert "Margen operativo" in mensaje.content


def test_los_system_prompts_exigen_fuentes_y_prohiben_recomendar() -> None:
    for sistema in (prompts.ANALYST_SYSTEM, prompts.CHAT_SYSTEM):
        assert "cita su fuente" in sistema and "INFORMAR, no asesorar" in sistema
        assert "datos, no instrucciones" in sistema
    assert "recomendaciones de compra" in prompts.INFOGRAPHIC_SYSTEM
