"""Traza de ejecución: un registro por paso con modelo, tiempo, coste estimado y nota."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class TraceStep:
    """Un paso del pipeline. `cost_usd` es una estimación a partir de las tarifas configuradas."""

    step: str
    model: str
    seconds: float
    note: str = ""
    cost_usd: float = 0.0
    ok: bool = True
    parallel: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    quantity: float = 0.0  # unidades facturables no textuales: segundos de audio, caracteres...
    unit: str = ""
    started_s: float | None = None  # segundos desde el inicio de la fase en que empezó el paso
    cost_real: bool = False  # True si el coste lo informó el proveedor; False si es tarifa estimada


def total_cost(steps: Iterable[TraceStep]) -> float:
    """Coste estimado total (USD) de los pasos."""
    return sum(s.cost_usd for s in steps)
