"""Casos de ejemplo para el primer uso: ficticio (sin red), Inditex real y solo ticker. Sin lógica de negocio."""
from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

from finlens.ui.demo_samples import DEMO_QUESTION, demo_audio_wav, demo_chart_png, demo_pdf

SAMPLES = Path(__file__).resolve().parents[3] / "samples"
INDITEX = SAMPLES / "01_inditex"

# Formatos que acepta cada ranura (lo que valida el backend: domain/media_checks.py y ingest).
FORMATOS = (
    ("A · Informe", "PDF con texto seleccionable (no escaneado). Se leen hasta 300.000 caracteres."),
    ("B · Gráfico", "PNG o JPG de un gráfico de velas · máx. 10 MB."),
    ("C · Audio", "WAV, MP3, M4A, OGG o WEBM · máx. 25 MB · o graba tu pregunta con el micrófono."),
    ("D · Ticker", "Acciones de Yahoo Finance (ITX.MC, SAN.MC, AAPL) o cripto de Hyperliquid (BTC, ETH)."),
)
TICKERS_EJEMPLO = ("ITX.MC", "SAN.MC", "AAPL", "BTC", "ETH")


@dataclass(frozen=True)
class Archivo:
    nombre: str
    datos: bytes
    mime: str


@dataclass(frozen=True)
class Caso:
    """Materiales precargados de un caso de ejemplo."""

    clave: str
    titulo: str
    descripcion: str
    pdf: Archivo | None = None
    chart: Archivo | None = None
    audio: Archivo | None = None
    question: str = ""
    ticker: str = ""

    @property
    def archivos(self) -> tuple[Archivo, ...]:
        return tuple(a for a in (self.pdf, self.chart, self.audio) if a is not None)


def _leer(ruta: Path, mime: str) -> Archivo | None:
    return Archivo(ruta.name, ruta.read_bytes(), mime) if ruta.is_file() else None


@cache
def casos() -> dict[str, Caso]:
    """Casos disponibles (Inditex solo si sus ficheros están en samples/)."""
    salida = {
        "ficticio": Caso(
            "ficticio", "Ficticio · ACME", "Informe ficticio de 4 páginas, gráfico de velas y audio de prueba.",
            Archivo("acme_informe_2025.pdf", demo_pdf(), "application/pdf"),
            Archivo("velas_acme.png", demo_chart_png(), "image/png"),
            Archivo("call_demo.wav", demo_audio_wav(), "audio/wav"),
            DEMO_QUESTION, "ACME",
        ),
    }
    pdf = _leer(INDITEX / "informe.pdf", "application/pdf")
    if pdf is not None:
        pregunta = INDITEX / "pregunta.txt"
        salida["inditex"] = Caso(
            "inditex", "Inditex real", "Informe anual 2025 (22 págs. del original), velas de ITX.MC y audio.",
            pdf, _leer(INDITEX / "grafico.png", "image/png"), _leer(INDITEX / "audio.mp3", "audio/mpeg"),
            pregunta.read_text(encoding="utf-8").strip() if pregunta.is_file() else "", "ITX.MC",
        )
    salida["btc"] = Caso(
        "btc", "Solo ticker · BTC", "Sin documentos: datos de mercado de Hyperliquid, técnicos y contraste.",
        question="¿Qué tendencia y qué riesgos muestran los datos de mercado de BTC en los últimos meses?",
        ticker="BTC",
    )
    return salida
