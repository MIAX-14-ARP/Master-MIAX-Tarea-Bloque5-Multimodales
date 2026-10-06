"""Caché en memoria por hash de los archivos de entrada (palanca de coste; sin persistencia)."""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Sequence

from finlens.orchestration.pipeline import AnalysisInput, AnalysisResult, MediaResult
from finlens.providers.base import ProviderInfo

DEFAULT_MAX_ENTRIES = 16  # análisis en memoria; los más antiguos sin uso se descartan


def cache_key(
    inp: AnalysisInput,
    *,
    demo: bool,
    max_pdf_chars: int,
    providers_info: Sequence[ProviderInfo] = (),
) -> str:
    """Hash estable de todo lo que influye en el resultado de un análisis.

    `providers_info` (backend y modelo por capacidad) evita servir un resultado generado con otros modelos.
    """
    h = hashlib.sha256()
    partes = [
        inp.pdf, inp.chart or b"", inp.audio or b"",
        inp.question.strip().encode(), inp.audio_role.encode(),
        str(demo).encode(), str(max_pdf_chars).encode(),
        "|".join(f"{i.capability}:{i.backend}:{i.model}" for i in providers_info).encode(),
    ]
    for parte in partes:
        h.update(len(parte).to_bytes(8, "big"))  # evita colisiones por concatenación
        h.update(parte)
    return h.hexdigest()


class AnalysisCache:
    """Guarda análisis y medios ya generados para no repetir llamadas de pago."""

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries debe ser al menos 1")
        self._max = max_entries
        self._lock = threading.RLock()  # Streamlit puede ejecutar sesiones en hilos distintos
        self._analisis: OrderedDict[str, AnalysisResult] = OrderedDict()
        self._medios: OrderedDict[str, MediaResult] = OrderedDict()

    @staticmethod
    def _guardar(almacen: OrderedDict, clave: str, valor: object, maximo: int) -> None:
        almacen[clave] = valor
        almacen.move_to_end(clave)
        while len(almacen) > maximo:
            almacen.popitem(last=False)  # expulsa la menos usada recientemente

    def get_analysis(self, key: str) -> AnalysisResult | None:
        with self._lock:
            resultado = self._analisis.get(key)
            if resultado is not None:
                self._analisis.move_to_end(key)
            return resultado

    def put_analysis(self, key: str, result: AnalysisResult) -> None:
        with self._lock:
            self._guardar(self._analisis, key, result, self._max)

    @staticmethod
    def _media_key(key: str, with_audio: bool, with_image: bool) -> str:
        return f"{key}|audio={with_audio}|imagen={with_image}"

    def get_media(self, key: str, with_audio: bool = True, with_image: bool = True) -> MediaResult | None:
        clave = self._media_key(key, with_audio, with_image)
        with self._lock:
            medios = self._medios.get(clave)
            if medios is not None:
                self._medios.move_to_end(clave)
            return medios

    def put_media(
        self, key: str, media: MediaResult, with_audio: bool = True, with_image: bool = True
    ) -> None:
        # los medios admiten hasta 4 variantes por análisis (audio/imagen solicitados)
        with self._lock:
            self._guardar(self._medios, self._media_key(key, with_audio, with_image), media, self._max * 4)
