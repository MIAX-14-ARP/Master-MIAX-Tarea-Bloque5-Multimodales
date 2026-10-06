"""Tests del cálculo de coste."""
import pytest

from finlens.config import Settings
from finlens.domain import cost
from finlens.providers.base import TextResult

TARIFAS = cost.Tariffs(
    llm_input_per_mtok=3.0, llm_output_per_mtok=15.0,
    stt_per_minute=0.006, tts_per_mchar=15.0, image_per_unit=0.04,
)


def test_coste_llm_por_tokens() -> None:
    assert cost.llm_cost(TARIFAS, 1_000_000, 0) == pytest.approx(3.0)
    assert cost.llm_cost(TARIFAS, 10_000, 2_000) == pytest.approx(0.06)


def test_coste_de_un_resultado_de_texto() -> None:
    resultado = TextResult("x", "m", tokens_in=2_000_000, tokens_out=1_000_000)
    assert cost.text_result_cost(TARIFAS, resultado) == pytest.approx(21.0)


def test_coste_stt_tts_e_imagen() -> None:
    assert cost.stt_cost(TARIFAS, 90) == pytest.approx(0.009)
    assert cost.tts_cost(TARIFAS, 2_000) == pytest.approx(0.03)
    assert cost.image_cost(TARIFAS) == pytest.approx(0.04)
    assert cost.image_cost(TARIFAS, 3) == pytest.approx(0.12)


def test_las_tarifas_salen_de_la_configuracion() -> None:
    settings = Settings(_env_file=None, price_stt_per_minute=0.02, price_image_per_unit=0.1)
    tarifas = cost.Tariffs.from_settings(settings)
    assert tarifas.stt_per_minute == 0.02 and tarifas.image_per_unit == 0.1
    assert tarifas.llm_input_per_mtok == settings.price_llm_input_per_mtok


def test_el_coste_real_del_proveedor_prevalece_sobre_las_tarifas() -> None:
    from finlens.domain.cost import image_result_cost, speech_cost, transcription_cost
    from finlens.providers.base import ImageResult, SpeechResult, TranscriptionResult

    t = cost.Tariffs(2.0, 10.0, 0.006, 15.0, 0.04)
    assert cost.text_result_cost(t, TextResult("x", "m", 1_000_000, 0, cost_usd=0.01)) == 0.01
    assert cost.text_result_cost(t, TextResult("x", "m", 1_000_000, 0, cost_usd=0.0)) == 0.0
    assert cost.text_result_cost(t, TextResult("x", "m", 1_000_000, 0)) == pytest.approx(2.0)
    assert transcription_cost(t, TranscriptionResult("x", "m", 60.0, cost_usd=0.5)) == 0.5
    assert transcription_cost(t, TranscriptionResult("x", "m", 60.0)) == pytest.approx(0.006)
    assert speech_cost(t, SpeechResult(b"a", "audio/mpeg", "m", 1_000_000, cost_usd=0.2)) == 0.2
    assert speech_cost(t, SpeechResult(b"a", "audio/mpeg", "m", 1_000_000)) == pytest.approx(15.0)
    assert image_result_cost(t, ImageResult(b"a", "image/png", "m", cost_usd=0.07)) == 0.07
    assert image_result_cost(t, ImageResult(b"a", "image/png", "m")) == 0.04
