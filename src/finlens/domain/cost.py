"""Estimación del coste por análisis a partir de las tarifas configurables (en USD).

Las tarifas son orientativas: deben verificarse en las páginas oficiales de cada proveedor.
"""
from __future__ import annotations

from dataclasses import dataclass

from finlens.config import Settings
from finlens.providers.base import TextResult

CURRENCY = "USD"


@dataclass(frozen=True)
class Tariffs:
    """Tarifas unitarias de cada modalidad."""

    llm_input_per_mtok: float
    llm_output_per_mtok: float
    stt_per_minute: float
    tts_per_mchar: float
    image_per_unit: float

    @classmethod
    def from_settings(cls, settings: Settings) -> Tariffs:
        return cls(
            settings.price_llm_input_per_mtok,
            settings.price_llm_output_per_mtok,
            settings.price_stt_per_minute,
            settings.price_tts_per_mchar,
            settings.price_image_per_unit,
        )


def llm_cost(tariffs: Tariffs, tokens_in: int, tokens_out: int) -> float:
    """Coste de una llamada de texto o visión según sus tokens."""
    return (
        tokens_in * tariffs.llm_input_per_mtok + tokens_out * tariffs.llm_output_per_mtok
    ) / 1_000_000


def text_result_cost(tariffs: Tariffs, result: TextResult) -> float:
    return llm_cost(tariffs, result.tokens_in, result.tokens_out)


def stt_cost(tariffs: Tariffs, duration_s: float) -> float:
    return duration_s / 60 * tariffs.stt_per_minute


def tts_cost(tariffs: Tariffs, chars: int) -> float:
    return chars / 1_000_000 * tariffs.tts_per_mchar


def image_cost(tariffs: Tariffs, count: int = 1) -> float:
    return count * tariffs.image_per_unit
