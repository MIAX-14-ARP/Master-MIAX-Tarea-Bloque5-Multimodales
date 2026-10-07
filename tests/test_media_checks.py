"""Validaciones previas a las llamadas de pago (audio decodificable, tamaños)."""
import io
import wave
from dataclasses import replace

import pytest

from _pdf import pdf_minimo
from finlens.domain.cost import Tariffs
from finlens.domain.media_checks import MAX_AUDIO_BYTES, MAX_IMAGE_BYTES, check_audio, check_image
from finlens.orchestration.pipeline import AnalysisInput, analyze
from finlens.providers.media import silent_wav, solid_png
from finlens.providers.registry import build_mock_providers
from finlens.sources.registry import build_sources

TARIFAS = Tariffs(1, 1, 1, 1, 1)


def wav_cero_frames() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
    return buf.getvalue()


def test_audio_valido_pasa() -> None:
    assert check_audio(silent_wav(1), "a.wav") is None


@pytest.mark.parametrize(
    ("audio", "nombre", "fragmento"),
    [
        (b"", "a.wav", "vacío"),
        (wav_cero_frames(), "a.wav", "0 s"),
        (b"esto no es audio", "a.mp3", "decodificable"),
        (b"esto no es audio", "a.wav", "decodificable"),
        (b"x" * (MAX_AUDIO_BYTES + 1), "a.wav", "25 MB"),
    ],
    ids=["vacio", "0_frames", "mp3_roto", "wav_roto", "demasiado_grande"],
)
def test_audio_invalido_se_rechaza_con_motivo(audio: bytes, nombre: str, fragmento: str) -> None:
    assert fragmento in (check_audio(audio, nombre) or "")


def test_formatos_que_no_se_pueden_medir_se_dejan_pasar() -> None:
    assert check_audio(b"datos webm cualquiera", "a.webm") is None


def test_limite_de_imagen() -> None:
    assert check_image(solid_png(4, 4, (0, 0, 0))) is None
    assert "10 MB" in (check_image(b"x" * (MAX_IMAGE_BYTES + 1)) or "")


def test_el_pipeline_no_llama_al_stt_de_pago_con_audio_invalido() -> None:
    llamadas: list[int] = []

    class Espia(type(build_mock_providers().stt)):
        def transcribe(self, audio, filename):
            llamadas.append(1)
            return super().transcribe(audio, filename)

    providers = replace(build_mock_providers(), stt=Espia())
    for audio in (wav_cero_frames(), b"no es audio"):
        r = analyze(providers, TARIFAS, AnalysisInput(pdf=pdf_minimo(), audio=audio, audio_name="a.wav"))
        assert r.transcript is None and any("audio" in w.lower() for w in r.warnings) and r.report.summary
    assert llamadas == []


def test_imagen_enorme_degrada_sin_llamar_a_la_vision() -> None:
    llamadas: list[int] = []

    class Espia(type(build_mock_providers().vision)):
        def describe_image(self, image, mime, prompt):
            llamadas.append(1)
            return super().describe_image(image, mime, prompt)

    providers = replace(build_mock_providers(), vision=Espia())
    enorme = solid_png(4, 4, (0, 0, 0)) + b"0" * (MAX_IMAGE_BYTES + 1)
    r = analyze(
        providers, TARIFAS, AnalysisInput(pdf=pdf_minimo(), chart=enorme), sources=build_sources(demo=True)
    )
    assert r.chart is None and llamadas == [] and any("10 MB" in w for w in r.warnings)
