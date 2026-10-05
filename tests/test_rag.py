"""Tests de la recuperación TF-IDF."""
import pytest

from finlens.domain.ingest import Chunk
from finlens.domain.rag import Retriever

CHUNKS = [
    Chunk(1, "El margen operativo mejoró hasta el 18 por ciento gracias a los costes."),
    Chunk(2, "La deuda neta se redujo y el flujo de caja libre aumentó."),
    Chunk(3, "Perspectivas: la dirección mantiene la guía de ingresos para el próximo ejercicio."),
]


def test_recupera_el_fragmento_relevante_primero() -> None:
    resultados = Retriever(CHUNKS).search("¿Cómo evolucionó el margen operativo?")
    assert resultados[0].chunk.page == 1 and resultados[0].score > 0


def test_ignora_acentos_y_mayusculas() -> None:
    resultados = Retriever(CHUNKS).search("PERSPECTIVAS DIRECCION GUIA")
    assert resultados[0].chunk.page == 3


def test_respeta_k_y_excluye_fragmentos_sin_coincidencias() -> None:
    assert len(Retriever(CHUNKS).search("margen deuda guía", k=2)) == 2
    assert Retriever(CHUNKS).search("astronomía cuántica") == []


def test_consulta_solo_de_palabras_vacias_no_devuelve_nada() -> None:
    assert Retriever(CHUNKS).search("de la el y") == []


def test_sin_fragmentos_falla_con_claridad() -> None:
    with pytest.raises(ValueError):
        Retriever([])
