"""Caché en memoria por hash de los archivos de entrada (palanca de coste; sin persistencia)."""
from __future__ import annotations

import hashlib

from finlens.orchestration.pipeline import AnalysisInput, AnalysisResult, MediaResult


def cache_key(inp: AnalysisInput, *, demo: bool, max_pdf_chars: int) -> str:
    """Hash estable de todo lo que influye en el resultado de un análisis."""
    h = hashlib.sha256()
    partes = [
        inp.pdf, inp.chart or b"", inp.audio or b"",
        inp.question.strip().encode(), inp.audio_role.encode(),
        str(demo).encode(), str(max_pdf_chars).encode(),
    ]
    for parte in partes:
        h.update(len(parte).to_bytes(8, "big"))  # evita colisiones por concatenación
        h.update(parte)
    return h.hexdigest()


class AnalysisCache:
    """Guarda análisis y medios ya generados para no repetir llamadas de pago."""

    def __init__(self) -> None:
        self._analisis: dict[str, AnalysisResult] = {}
        self._medios: dict[str, MediaResult] = {}

    def get_analysis(self, key: str) -> AnalysisResult | None:
        return self._analisis.get(key)

    def put_analysis(self, key: str, result: AnalysisResult) -> None:
        self._analisis[key] = result

    @staticmethod
    def _media_key(key: str, with_audio: bool, with_image: bool) -> str:
        return f"{key}|audio={with_audio}|imagen={with_image}"

    def get_media(self, key: str, with_audio: bool = True, with_image: bool = True) -> MediaResult | None:
        return self._medios.get(self._media_key(key, with_audio, with_image))

    def put_media(
        self, key: str, media: MediaResult, with_audio: bool = True, with_image: bool = True
    ) -> None:
        self._medios[self._media_key(key, with_audio, with_image)] = media
