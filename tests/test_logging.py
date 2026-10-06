"""Tests de logging: configuración idempotente y que no se registre contenido ni claves."""
import logging

from finlens.domain.cost import Tariffs
from finlens.logging_config import configure_logging
from finlens.orchestration.pipeline import AnalysisInput, analyze
from finlens.providers.registry import build_mock_providers
from finlens.ui.demo_samples import demo_pdf


def test_configure_logging_es_idempotente_y_respeta_el_nivel() -> None:
    logger = configure_logging("debug")
    configure_logging("WARNING")
    assert logger.name == "finlens" and logger.level == logging.WARNING
    assert sum(getattr(h, "_finlens", False) for h in logger.handlers) == 1
    assert configure_logging("nivel-raro").level == logging.INFO


def test_el_pipeline_registra_pasos_sin_contenido(caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.DEBUG, logger="finlens")
    entrada = AnalysisInput(pdf=demo_pdf(), question="PREGUNTA-SECRETA-123")
    analyze(build_mock_providers(), Tariffs(1, 1, 1, 1, 1), entrada)
    texto = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("finlens"))
    assert "Análisis (LLM)" in texto and "mock-llm" in texto
    assert "PREGUNTA-SECRETA-123" not in texto and "ACME" not in texto and "18,4" not in texto
