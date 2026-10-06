"""Seguimiento en vivo del pipeline para el mapa: espía las llamadas a proveedores.

No toca la lógica del pipeline: envuelve cada proveedor para anotar «en curso / ok / fallo» por
capacidad y ejecuta la fase en un hilo mientras el hilo de Streamlit repinta el mapa.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, TypeVar

from finlens.providers.base import Providers

T = TypeVar("T")
POLL_S = 0.15


class Tracker:
    """Estado por capacidad, seguro entre hilos."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._activas: dict[str, int] = {}
        self._estado: dict[str, str] = {}

    def start(self, cap: str) -> None:
        with self._lock:
            self._activas[cap] = self._activas.get(cap, 0) + 1
            self._estado[cap] = "en_curso"

    def finish(self, cap: str, ok: bool) -> None:
        with self._lock:
            self._activas[cap] = max(0, self._activas.get(cap, 1) - 1)
            if not ok:
                self._estado[cap] = "fallo"
            elif self._activas[cap] == 0 and self._estado.get(cap) != "fallo":
                self._estado[cap] = "ok"

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(self._estado)


class _Spy:
    """Proveedor envuelto: delega todo y anota inicio/fin de cada llamada."""

    def __init__(self, inner: Any, cap: str, tracker: Tracker) -> None:
        self._inner, self._cap, self._tracker = inner, cap, tracker

    def __getattr__(self, nombre: str) -> Any:
        return getattr(self._inner, nombre)

    def _call(self, metodo: str, *args: Any, **kwargs: Any) -> Any:
        self._tracker.start(self._cap)
        try:
            salida = getattr(self._inner, metodo)(*args, **kwargs)
        except BaseException:
            self._tracker.finish(self._cap, ok=False)
            raise
        self._tracker.finish(self._cap, ok=True)
        return salida

    def complete(self, *a: Any, **k: Any) -> Any:
        return self._call("complete", *a, **k)

    def describe_image(self, *a: Any, **k: Any) -> Any:
        return self._call("describe_image", *a, **k)

    def transcribe(self, *a: Any, **k: Any) -> Any:
        return self._call("transcribe", *a, **k)

    def synthesize(self, *a: Any, **k: Any) -> Any:
        return self._call("synthesize", *a, **k)

    def generate(self, *a: Any, **k: Any) -> Any:
        return self._call("generate", *a, **k)

    def embed(self, *a: Any, **k: Any) -> Any:
        return self._call("embed", *a, **k)


def instrument(providers: Providers, tracker: Tracker) -> Providers:
    """Copia de `providers` con cada capacidad espiada (conserva `info` y `warnings`)."""
    return Providers(
        llm=_Spy(providers.llm, "llm", tracker),
        vision=_Spy(providers.vision, "vision", tracker),
        stt=_Spy(providers.stt, "stt", tracker),
        tts=_Spy(providers.tts, "tts", tracker),
        image=_Spy(providers.image, "image", tracker),
        embeddings=_Spy(providers.embeddings, "embeddings", tracker),
        info=providers.info,
        warnings=providers.warnings,
    )


def run_live(fn: Callable[[Providers], T], providers: Providers,
             on_tick: Callable[[dict[str, str], float], None]) -> T:
    """Ejecuta `fn(proveedores_espiados)` en un hilo y llama a `on_tick` hasta que termina."""
    tracker = Tracker()
    espiados = instrument(providers, tracker)
    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=1) as pool:
        futuro = pool.submit(fn, espiados)
        while not futuro.done():
            on_tick(tracker.snapshot(), time.perf_counter() - inicio)
            wait([futuro], timeout=POLL_S)  # vuelve antes si la fase termina
        return futuro.result()
