"""Tests de logging: configuración idempotente y que no se registre contenido ni claves."""
import logging

from finlens.domain.cost import Tariffs
from finlens.logging_config import configure_logging
from finlens.orchestration.pipeline import AnalysisInput, analyze
from finlens.providers.registry import build_mock_providers


def pdf_minimo() -> bytes:
    """PDF de una página con texto ficticio, generado a mano (sin depender de la UI)."""
    texto = "BT /F1 12 Tf 72 720 Td (ACME informe ficticio margen 18,4 por ciento) Tj ET"
    objetos = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(texto)} >>\nstream\n{texto}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    salida, offsets = "%PDF-1.4\n", []
    for i, o in enumerate(objetos, start=1):
        offsets.append(len(salida))
        salida += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n"
    salida += "".join(f"{o:010d} 00000 n \n" for o in offsets)
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
    return salida.encode("latin-1")


def test_configure_logging_es_idempotente_y_respeta_el_nivel() -> None:
    logger = configure_logging("debug")
    configure_logging("WARNING")
    assert logger.name == "finlens" and logger.level == logging.WARNING
    assert sum(getattr(h, "_finlens", False) for h in logger.handlers) == 1
    assert configure_logging("nivel-raro").level == logging.INFO


def test_el_pipeline_registra_pasos_sin_contenido(caplog) -> None:  # type: ignore[no-untyped-def]
    caplog.set_level(logging.DEBUG, logger="finlens")
    entrada = AnalysisInput(pdf=pdf_minimo(), question="PREGUNTA-SECRETA-123")
    analyze(build_mock_providers(), Tariffs(1, 1, 1, 1, 1), entrada)
    texto = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("finlens"))
    assert "Análisis (LLM)" in texto and "mock-llm" in texto
    assert "PREGUNTA-SECRETA-123" not in texto and "ACME" not in texto and "18,4" not in texto
