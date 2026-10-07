"""PDF mínimo de una página con texto ficticio para los tests (sin depender de la UI)."""


def pdf_minimo() -> bytes:
    """PDF de una página con texto ficticio, generado a mano (sin depender de la UI)."""
    texto = "BT /F1 12 Tf 72 720 Td (ACME informe ficticio margen 18,4 por ciento) Tj ET"
    objetos = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(texto)} >>\nstream\n{texto}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    salida, offsets = "%PDF-1.4\n", []
    for i, o in enumerate(objetos, start=1):
        offsets.append(len(salida))
        salida += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n"
    salida += "".join(f"{o:010d} 00000 n \n" for o in offsets)
    salida += f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
    return salida.encode("latin-1")
