"""Configuración de logging de FinLens: logger `finlens`, nivel por LOG_LEVEL.

Se registran pasos, modelos, tiempos y resultado ok/fallo. Nunca contenido de documentos,
transcripciones, respuestas de los modelos ni claves API.
"""
from __future__ import annotations

import logging

FORMATO = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(level: str = "INFO") -> logging.Logger:
    """Configura (una sola vez) el logger `finlens` y lo devuelve. Un nivel desconocido usa INFO."""
    logger = logging.getLogger("finlens")
    nivel = logging.getLevelNamesMapping().get(level.strip().upper(), logging.INFO)
    logger.setLevel(nivel)
    if not any(getattr(h, "_finlens", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(FORMATO))
        handler._finlens = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    return logger
