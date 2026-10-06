"""Recuperación local con TF-IDF (coste 0): selecciona los fragmentos del PDF más relevantes."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from finlens.domain.ingest import Chunk
from finlens.providers.base import EmbeddingProvider, EmbeddingResult

# Palabras vacías frecuentes en español, sin acentos (el vectorizador los elimina antes).
STOPWORDS_ES = frozenset(
    ["a", "al", "algo", "ante", "como", "con", "cual", "cuando", "de", "del", "desde", "donde", "el", "ella", "ellas", "ello", "ellos", "en", "entre", "era", "es", "esa", "esas", "ese", "eso", "esos", "esta", "estas", "este", "esto", "estos", "fue", "ha", "han", "hay", "la", "las", "le", "les", "lo", "los", "mas", "me", "mi", "muy", "ni", "no", "nos", "o", "para", "pero", "por", "que", "se", "si", "sin", "sobre", "son", "su", "sus", "te", "tu", "un", "una", "uno", "unos", "y", "ya"]
)


@dataclass(frozen=True)
class Retrieved:
    """Fragmento recuperado con su similitud coseno con la consulta."""

    chunk: Chunk
    score: float


class Retriever:
    """Índice TF-IDF en memoria sobre los fragmentos de un documento."""

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        if not chunks:
            raise ValueError("Se necesita al menos un fragmento para construir el índice.")
        self._chunks = list(chunks)
        self._vectorizer = TfidfVectorizer(
            strip_accents="unicode",
            stop_words=sorted(STOPWORDS_ES),
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        self._matrix = self._vectorizer.fit_transform(c.text for c in self._chunks)

    def rank(self, query: str) -> list[tuple[int, float]]:
        """(índice de fragmento, similitud) de los que comparten términos con `query`, de mejor a peor."""
        consulta = self._vectorizer.transform([query])
        puntuaciones = (self._matrix @ consulta.T).toarray().ravel()
        orden = sorted(range(len(self._chunks)), key=lambda i: -puntuaciones[i])
        return [(i, float(puntuaciones[i])) for i in orden if puntuaciones[i] > 0]

    def search(self, query: str, k: int = 4) -> list[Retrieved]:
        """Los `k` fragmentos más similares a `query`. Excluye los que no comparten términos."""
        return [Retrieved(self._chunks[i], p) for i, p in self.rank(query)[:k]]


RRF_K = 60  # constante de Reciprocal Rank Fusion


@dataclass(frozen=True)
class SearchResult:
    """Resultado de una búsqueda híbrida: fragmentos, modo usado y consumo de embeddings de la consulta."""

    results: list[Retrieved]
    mode: str  # "híbrida" o "solo TF-IDF"
    embedding: EmbeddingResult | None = None
    error: str | None = None  # motivo de la degradación a solo TF-IDF, si la hubo


def reciprocal_rank_fusion(rankings: Sequence[Sequence[int]], k: int = RRF_K) -> dict[int, float]:
    """Puntuación RRF de cada índice a partir de varias listas ordenadas (mejor primero)."""
    puntos: dict[int, float] = {}
    for ranking in rankings:
        for posicion, indice in enumerate(ranking, start=1):
            puntos[indice] = puntos.get(indice, 0.0) + 1.0 / (k + posicion)
    return puntos


class HybridRetriever:
    """TF-IDF (léxico, siempre) + coseno sobre embeddings (si hay), fusionados con RRF.

    Se construye solo léxico y `with_embeddings` devuelve una copia con el índice semántico. Si la
    consulta no se puede embeber, degrada a TF-IDF y lo comunica en `SearchResult.error`.
    """

    def __init__(
        self,
        chunks: Sequence[Chunk],
        vectors: Sequence[Sequence[float]] | None = None,
        embedder: EmbeddingProvider | None = None,
    ) -> None:
        self._lexical = Retriever(chunks)
        self._chunks = list(chunks)
        self._embedder = embedder
        self._matrix: np.ndarray | None = None
        if vectors is not None:
            if len(vectors) != len(self._chunks):
                raise ValueError("Debe haber un vector por fragmento.")
            matriz = np.asarray(vectors, dtype=float)
            normas = np.linalg.norm(matriz, axis=1, keepdims=True)
            self._matrix = matriz / np.where(normas == 0, 1.0, normas)

    @property
    def chunks(self) -> list[Chunk]:
        return list(self._chunks)

    @property
    def semantic(self) -> bool:
        """True si hay índice semántico y un proveedor con el que embeber las consultas."""
        return self._matrix is not None and self._embedder is not None

    @property
    def embedder_model(self) -> str:
        return getattr(self._embedder, "model", "") if self._embedder else ""

    def with_embeddings(
        self, vectors: Sequence[Sequence[float]], embedder: EmbeddingProvider
    ) -> HybridRetriever:
        """Copia con el índice semántico ya calculado (los fragmentos no se vuelven a embeber)."""
        return HybridRetriever(self._chunks, vectors, embedder)

    def search_detailed(self, query: str, k: int = 8) -> SearchResult:
        """Búsqueda con detalle de modo, consumo de embeddings y motivo de degradación."""
        rank = self._lexical.rank(query)
        lexico = [Retrieved(self._chunks[i], p) for i, p in rank]
        ranking_lexico = [i for i, _ in rank]
        if not self.semantic:
            return SearchResult(lexico[:k], "solo TF-IDF")
        assert self._matrix is not None and self._embedder is not None
        try:
            emb = self._embedder.embed([query], "query")
            consulta = np.asarray(emb.vectors[0], dtype=float)
            if consulta.shape[0] != self._matrix.shape[1]:
                raise ValueError("dimensión de embeddings incoherente")
        except Exception as exc:  # proveedor caído o respuesta rara: se degrada, no se detiene
            return SearchResult(lexico[:k], "solo TF-IDF", None, str(exc) or type(exc).__name__)
        norma = np.linalg.norm(consulta)
        similitudes = self._matrix @ (consulta / norma if norma else consulta)
        ranking_semantico = [int(i) for i in np.argsort(-similitudes)]
        puntos = reciprocal_rank_fusion([ranking_lexico, ranking_semantico])
        orden = sorted(puntos, key=lambda i: -puntos[i])[:k]
        return SearchResult([Retrieved(self._chunks[i], puntos[i]) for i in orden], "híbrida", emb)

    def search(self, query: str, k: int = 8) -> list[Retrieved]:
        return self.search_detailed(query, k).results
