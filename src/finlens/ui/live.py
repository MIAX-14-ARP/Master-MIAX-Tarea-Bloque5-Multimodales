"""Seguimiento en vivo del pipeline para el mapa, con el callback `on_step` del orquestador.

La fase se ejecuta en un hilo; el pipeline avisa de cada paso («start»/«end», desde hilos del
pool) y el hilo de Streamlit repinta el mapa con lo que lleva cada paso. Sin lógica de negocio.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Literal, TypeVar

from finlens.orchestration.trace import TraceStep

T = TypeVar("T")
POLL_S = 0.15
OnStep = Callable[[str, Literal["start", "end"], TraceStep | None], None]


class Tracker:
    """Pasos en curso y terminados, seguro entre hilos (es el `on_step` del pipeline)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._en_curso: dict[str, None] = {}
        self._hechos: list[TraceStep] = []

    def __call__(self, step: str, event: Literal["start", "end"], record: TraceStep | None = None) -> None:
        with self._lock:
            if event == "start":
                self._en_curso[step] = None
            else:
                self._en_curso.pop(step, None)
                if record is not None:
                    self._hechos.append(record)

    def snapshot(self) -> tuple[tuple[str, ...], tuple[TraceStep, ...]]:
        """(nombres de pasos en curso, registros de pasos terminados)."""
        with self._lock:
            return tuple(self._en_curso), tuple(self._hechos)


def run_live(fn: Callable[[OnStep], T],
             on_tick: Callable[[tuple[str, ...], tuple[TraceStep, ...], float], None]) -> T:
    """Ejecuta `fn(on_step)` en un hilo y llama a `on_tick(en_curso, hechos, segundos)` hasta que acaba."""
    tracker = Tracker()
    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=1) as pool:
        futuro = pool.submit(fn, tracker)
        while not futuro.done():
            en_curso, hechos = tracker.snapshot()
            on_tick(en_curso, hechos, time.perf_counter() - inicio)
            wait([futuro], timeout=POLL_S)  # vuelve antes si la fase termina
        return futuro.result()
