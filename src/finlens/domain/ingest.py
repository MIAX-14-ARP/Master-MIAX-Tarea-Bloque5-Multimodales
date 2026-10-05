"""Ingesta de PDF: extracción de texto por página y troceado con solapamiento."""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from pypdf import PdfReader

# pypdf vuelca avisos internos por logging; los errores ya se reportan como IngestError.
logging.getLogger("pypdf").setLevel(logging.ERROR)

DEFAULT_MAX_CHARS = 300_000  # límite de entrada: palanca de coste
DEFAULT_CHUNK_CHARS = 1000
DEFAULT_OVERLAP_CHARS = 150


class IngestError(Exception):
    """El PDF no se puede usar. El mensaje es apto para mostrarlo en la UI."""


@dataclass(frozen=True)
class Chunk:
    """Fragmento de texto del PDF con la página de la que procede (empieza en 1)."""

    page: int
    text: str

    @property
    def location(self) -> str:
        """Localización para citar, p.ej. «p.3»."""
        return f"p.{self.page}"


@dataclass(frozen=True)
class IngestedDocument:
    """Resultado de ingerir un PDF."""

    chunks: tuple[Chunk, ...]
    n_pages: int
    truncated: bool = False


def split_text(
    text: str, size: int = DEFAULT_CHUNK_CHARS, overlap: int = DEFAULT_OVERLAP_CHARS
) -> list[str]:
    """Trocea `text` en fragmentos de ~`size` caracteres cortando en palabras, con solapamiento."""
    if not 0 <= overlap < size:
        raise ValueError("overlap debe estar entre 0 y size - 1")
    trozos: list[str] = []
    actual: list[str] = []
    largo = 0
    for palabra in text.split():
        if actual and largo + 1 + len(palabra) > size:
            trozos.append(" ".join(actual))
            actual = _cola(actual, overlap)
            largo = len(" ".join(actual))
        largo += len(palabra) + (1 if actual else 0)
        actual.append(palabra)
    if actual:
        trozos.append(" ".join(actual))
    return trozos


def _cola(palabras: list[str], overlap: int) -> list[str]:
    """Últimas palabras que caben en `overlap` caracteres (inicio del siguiente fragmento)."""
    cola: list[str] = []
    largo = 0
    for palabra in reversed(palabras):
        if largo + len(palabra) + 1 > overlap:
            break
        cola.insert(0, palabra)
        largo += len(palabra) + 1
    return cola


def _leer_paginas(data: bytes) -> list[str]:
    """Texto de cada página. Cualquier fallo de pypdf se traduce a IngestError."""
    try:
        lector = PdfReader(io.BytesIO(data))
        if lector.is_encrypted:
            raise IngestError("El PDF está protegido con contraseña.")
        return [pagina.extract_text() or "" for pagina in lector.pages]
    except IngestError:
        raise
    except Exception as exc:  # pypdf lanza tipos muy variados con ficheros corruptos
        raise IngestError("No se pudo leer el PDF: el fichero está dañado o no es un PDF.") from exc


def ingest_pdf(
    data: bytes,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    overlap: int = DEFAULT_OVERLAP_CHARS,
) -> IngestedDocument:
    """Extrae y trocea el texto de un PDF, página a página y hasta `max_chars` caracteres."""
    if not data:
        raise IngestError("El PDF está vacío.")
    paginas = _leer_paginas(data)
    chunks: list[Chunk] = []
    restante = max_chars
    truncated = False
    for numero, texto in enumerate(paginas, start=1):
        texto = " ".join(texto.split())
        if not texto:
            continue
        if len(texto) > restante:
            texto, truncated = texto[:restante], True
        chunks += [Chunk(numero, t) for t in split_text(texto, chunk_chars, overlap)]
        restante -= len(texto)
        if truncated:
            break
    if not chunks:
        raise IngestError(
            "El PDF no contiene texto extraíble (puede ser un documento escaneado). "
            "Prueba con un PDF con texto seleccionable."
        )
    return IngestedDocument(tuple(chunks), len(paginas), truncated)
