"""Materiales de demostración ficticios (PDF, gráfico de velas y audio) generados en código."""
from __future__ import annotations

import random

from finlens.providers.media import encode_png, silent_wav

DEMO_QUESTION = "¿Cómo evolucionó el margen operativo y qué dijo la dirección sobre la guía?"

_PAGINAS_DEMO = [
    "ACME Corp - Informe anual 2025 (documento FICTICIO para demostracion)\n"
    "Carta del presidente: el ejercicio 2025 ha sido solido y estable.\n"
    "Este documento no procede de ninguna empresa real.",
    "Resultados del ejercicio\n"
    "Los ingresos alcanzaron 12.300 millones de euros, un 6 por ciento mas que en 2024.\n"
    "El beneficio neto fue de 1.450 millones de euros.",
    "Rentabilidad y balance\n"
    "El margen operativo se situo en el 18,4 por ciento, frente al 17,1 por ciento del\n"
    "ejercicio anterior, gracias a la eficiencia de costes. La deuda neta se redujo\n"
    "hasta 3.200 millones de euros.",
    "Perspectivas\n"
    "La direccion mantiene la guia de ingresos para 2026, con un crecimiento de un digito\n"
    "medio-alto, y prevé estabilidad del margen operativo.",
]


def _escapar(texto: str) -> bytes:
    return texto.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("cp1252")


def make_pdf(pages: list[str]) -> bytes:
    """PDF mínimo con una página por texto de `pages`; las líneas se separan con saltos de línea."""
    n = len(pages)
    objetos: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + b" ".join(f"{4 + 2 * i} 0 R".encode() for i in range(n))
        + f"] /Count {n} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for i, texto in enumerate(pages):
        lineas = b" T* ".join(b"(" + _escapar(linea) + b") Tj" for linea in texto.split("\n"))
        flujo = b"BT /F1 11 Tf 14 TL 50 750 Td " + lineas + b" ET"
        objetos.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>".encode()
        )
        objetos.append(b"<< /Length %d >>\nstream\n" % len(flujo) + flujo + b"\nendstream")

    salida = bytearray(b"%PDF-1.4\n")
    offsets = []
    for numero, cuerpo in enumerate(objetos, start=1):
        offsets.append(len(salida))
        salida += f"{numero} 0 obj\n".encode() + cuerpo + b"\nendobj\n"
    inicio_xref = len(salida)
    salida += f"xref\n0 {len(objetos) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        salida += f"{offset:010d} 00000 n \n".encode()
    salida += (
        f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\nstartxref\n{inicio_xref}\n%%EOF\n"
    ).encode()
    return bytes(salida)


def demo_pdf() -> bytes:
    """Informe anual ficticio de 4 páginas."""
    return make_pdf(_PAGINAS_DEMO)


def demo_chart_png(width: int = 640, height: int = 360, candles: int = 40) -> bytes:
    """Gráfico de velas ficticio con tendencia alcista (serie aleatoria con semilla fija)."""
    azar = random.Random(7)
    velas, precio = [], 100.0
    for _ in range(candles):
        apertura = precio
        cierre = apertura + azar.gauss(0.6, 2.0)
        alto = max(apertura, cierre) + abs(azar.gauss(0, 1.0))
        bajo = min(apertura, cierre) - abs(azar.gauss(0, 1.0))
        velas.append((apertura, cierre, alto, bajo))
        precio = cierre
    minimo, maximo = min(v[3] for v in velas), max(v[2] for v in velas)
    margen = 20

    def y(valor: float) -> int:
        return int(height - margen - (valor - minimo) / (maximo - minimo) * (height - 2 * margen))

    pixeles = bytearray(b"\xfa" * (width * height * 3))

    def rectangulo(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        for fila in range(max(0, min(y0, y1)), min(height, max(y0, y1) + 1)):
            for columna in range(max(0, x0), min(width, x1 + 1)):
                inicio = (fila * width + columna) * 3
                pixeles[inicio : inicio + 3] = bytes(color)

    paso = (width - 2 * margen) // candles
    for i, (apertura, cierre, alto, bajo) in enumerate(velas):
        color = (38, 166, 91) if cierre >= apertura else (214, 69, 65)
        x = margen + i * paso
        rectangulo(x + paso // 2, y(alto), x + paso // 2, y(bajo), color)
        rectangulo(x + 1, y(max(apertura, cierre)), x + paso - 2, y(min(apertura, cierre)) + 1, color)
    return encode_png(width, height, bytes(pixeles))


def demo_audio_wav() -> bytes:
    """Audio ficticio (silencio): en modo demo la transcripción es simulada."""
    return silent_wav(2)
