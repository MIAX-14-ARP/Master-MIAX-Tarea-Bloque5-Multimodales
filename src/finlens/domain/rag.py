"""Recuperación local con TF-IDF (coste 0): selecciona los fragmentos del PDF más relevantes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sklearn.feature_extraction.text import TfidfVectorizer

from finlens.domain.ingest import Chunk

# Palabras vacías frecuentes en español, sin acentos (el vectorizador los elimina antes).
STOPWORDS_ES = frozenset(
    "a al algo ante como con cual cuando de del desde donde el ella ellas ello ellos en entre "
    "era es esa esas ese eso esos esta estas este esto estos fue ha han hay la las le les lo los "
    "mas me mi muy ni no nos o para pero por que se si sin sobre son su sus te tu un una uno unos "
    "y ya".split()
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

    def search(self, query: str, k: int = 4) -> list[Retrieved]:
        """Los `k` fragmentos más similares a `query`. Excluye los que no comparten términos."""
        consulta = self._vectorizer.transform([query])
        puntuaciones = (self._matrix @ consulta.T).toarray().ravel()
        orden = sorted(range(len(self._chunks)), key=lambda i: -puntuaciones[i])
        return [
            Retrieved(self._chunks[i], float(puntuaciones[i]))
            for i in orden[:k]
            if puntuaciones[i] > 0
        ]
