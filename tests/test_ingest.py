"""Tests de ingesta de PDF y troceado."""
import io

import pytest
from pypdf import PdfWriter

from finlens.domain.ingest import IngestError, ingest_pdf, split_text
from finlens.ui.demo_samples import make_pdf


def test_extrae_texto_con_su_pagina() -> None:
    doc = ingest_pdf(make_pdf(["Resultados del primer trimestre", "Margen operativo del 18 por ciento"]))
    assert doc.n_pages == 2 and not doc.truncated
    assert [c.page for c in doc.chunks] == [1, 2]
    assert "Margen operativo" in doc.chunks[1].text
    assert doc.chunks[1].location == "p.2"


def test_conserva_acentos_y_enie() -> None:
    doc = ingest_pdf(make_pdf(["Dirección: previsión de año positiva"]))
    assert "Dirección" in doc.chunks[0].text and "año" in doc.chunks[0].text


def test_pagina_larga_se_divide_en_varios_fragmentos_de_la_misma_pagina() -> None:
    texto = " ".join(f"palabra{i}" for i in range(400))
    doc = ingest_pdf(make_pdf([texto]), chunk_chars=300, overlap=50)
    assert len(doc.chunks) > 1 and {c.page for c in doc.chunks} == {1}
    assert all(len(c.text) <= 300 for c in doc.chunks)


def test_limite_de_entrada_trunca_y_lo_indica() -> None:
    doc = ingest_pdf(make_pdf(["a" * 50, "b" * 50, "c" * 50]), max_chars=70)
    assert doc.truncated
    assert sum(len(c.text) for c in doc.chunks) == 70
    assert {c.page for c in doc.chunks} == {1, 2}


def test_pdf_sin_texto_da_error_claro() -> None:
    escritor = PdfWriter()
    escritor.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    escritor.write(buffer)
    with pytest.raises(IngestError, match="no contiene texto"):
        ingest_pdf(buffer.getvalue())


@pytest.mark.parametrize("basura", [b"", b"esto no es un pdf", b"%PDF-1.4\nbasura"])
def test_entradas_invalidas_dan_error_claro(basura: bytes) -> None:
    with pytest.raises(IngestError):
        ingest_pdf(basura)


def test_pdf_cifrado_da_error_claro() -> None:
    escritor = PdfWriter()
    escritor.add_blank_page(width=200, height=200)
    escritor.encrypt("clave")
    buffer = io.BytesIO()
    escritor.write(buffer)
    with pytest.raises(IngestError, match="contraseña"):
        ingest_pdf(buffer.getvalue())


def test_split_text_solapa_fragmentos_contiguos() -> None:
    palabras = [f"p{i:03d}" for i in range(100)]
    trozos = split_text(" ".join(palabras), size=100, overlap=30)
    assert len(trozos) > 2
    for anterior, siguiente in zip(trozos, trozos[1:], strict=False):
        assert anterior.split()[-1] in siguiente.split()
    assert set(" ".join(trozos).split()) == set(palabras)


def test_split_text_valida_parametros() -> None:
    with pytest.raises(ValueError):
        split_text("hola", size=10, overlap=10)
