"""Proveedores simulados para el modo demo y los tests (cero coste, sin red).

Las respuestas del LLM son JSON fijo elegido por el marcador «ESQUEMA: <Clase>» que añade
`domain.structured.ask_structured`. Este módulo no importa `domain`; los tests comprueban que
cada JSON cumple su esquema. Todos los datos son ficticios.
"""
from __future__ import annotations

import json
import re
import unicodedata
import zlib
from collections.abc import Sequence
from typing import Literal

from finlens.providers.base import (
    EmbeddingResult,
    ImageResult,
    Message,
    ProviderError,
    SpeechResult,
    TextResult,
    TranscriptionResult,
)
from finlens.providers.media import detect_image_mime, silent_wav, solid_png

_CITA_DOC = {"origin": "documento", "location": "p.3"}
_CITA_GRAFICO = {"origin": "grafico", "location": ""}
_CITA_AUDIO = {"origin": "audio", "location": ""}

RESPUESTAS_LLM: dict[str, dict] = {
    "AnalysisReport": {
        "summary": "(Simulado) El margen operativo mejoró frente al ejercicio anterior y la "
        "dirección mantiene su guía, mientras el gráfico muestra una tendencia alcista.",
        "key_figures": [
            {"name": "Margen operativo", "value": "18,4 %", "period": "FY2025",
             "citations": [_CITA_DOC]},
            {"name": "Ingresos", "value": "12.300 M EUR", "period": "FY2025",
             "citations": [{"origin": "documento", "location": "p.2"}]},
        ],
        "chart_reading": {
            "statement": "El precio sube de forma sostenida en el periodo mostrado.",
            "citations": [_CITA_GRAFICO],
        },
        "management_statements": [
            {"statement": "La dirección reiteró la guía de resultados para el próximo ejercicio.",
             "citations": [_CITA_AUDIO]},
        ],
        "correlations": [
            {"statement": "La mejora del margen del informe coincide con la tendencia alcista "
             "del gráfico y con el tono positivo de la conferencia.",
             "citations": [_CITA_DOC, _CITA_GRAFICO, _CITA_AUDIO]},
        ],
        "contradictions": [],
        "limitations": ["Datos simulados del modo demo; no proceden de ningún informe real."],
        "spoken_summary": "Resumen simulado. El margen operativo mejoró, la dirección mantiene "
        "su guía y el gráfico muestra una tendencia alcista.",
    },
    "ChartReading": {
        "trend": "alcista",
        "description": "(Simulado) Velas con máximos y mínimos crecientes y volumen estable.",
        "observations": ["Soporte cercano a la zona media del rango.", "Sin huecos relevantes."],
    },
    "ChatAnswer": {
        "answer": "(Simulado) Según el informe, el margen operativo fue del 18,4 % en FY2025.",
        "grounded": True,
        "citations": [_CITA_DOC],
    },
    "InfographicPrompt": {
        "prompt": "Ilustración abstracta y sobria para la cabecera de una infografía financiera: "
        "formas geométricas ascendentes en tonos oscuros con acentos dorados, sin texto ni números."
    },
}

TRANSCRIPCION_DEMO = (
    "(Transcripción simulada) Buenos días. Este trimestre hemos mejorado el margen operativo "
    "y mantenemos la guía de resultados para el próximo ejercicio."
)
DURACION_AUDIO_DEMO_S = 45.0


def _estimar_tokens(texto: str) -> int:
    """Aproximación de ~4 caracteres por token, solo para que el coste demo no sea cero."""
    return max(1, len(texto) // 4)


def _informe_de_mercado(messages: Sequence[Message]) -> dict | None:
    """Sin documento pero con bloques <mercado>/<sec>: cifras clave citadas a esas fuentes (leídas del prompt).

    Así la demo con solo un ticker es coherente: las cifras salen de los datos aportados, no del PDF demo.
    """
    contenido = messages[0].content if messages else ""
    if "<mercado>" not in contenido or "<documento>" + chr(10) + "(no aportado)" not in contenido:
        return None
    cierre = re.search(r"Último cierre: ([\d,.]+)\.", contenido)
    rentab = re.search(r"Rentabilidad del periodo: (-?[\d.]+%)", contenido)
    sec = re.search(r"- Ingresos: FY\d+: ([\d,]+ M USD)", contenido)
    cita_m = [{"origin": "mercado", "location": ""}]
    cifras = []
    if cierre:
        cifras.append({"name": "Último cierre", "value": cierre.group(1), "period": "", "citations": cita_m})
    if rentab:
        cifras.append({"name": "Rentabilidad del periodo", "value": rentab.group(1), "period": "", "citations": cita_m})
    if sec:
        cifras.append({"name": "Ingresos", "value": sec.group(1), "period": "último ejercicio",
                       "citations": [{"origin": "sec", "location": ""}]})
    base = json.loads(json.dumps(RESPUESTAS_LLM["AnalysisReport"]))
    base["key_figures"] = cifras
    base["summary"] = "(Simulado) Resumen de mercado a partir de los datos y fundamentales aportados."
    base["correlations"] = [
        {"statement": "La tendencia calculada coincide con la lectura del gráfico generado.",
         "citations": [{"origin": "mercado", "location": ""}, {"origin": "grafico", "location": ""}]}
    ]
    base["management_statements"] = []
    base["limitations"] = ["Datos simulados del modo demo; sin informe en PDF."]
    return base


class MockLLM:
    """LLM simulado: devuelve el JSON fijo del esquema solicitado en el system prompt."""

    model = "mock-llm"

    def complete(
        self, system: str, messages: Sequence[Message], max_tokens: int = 2048
    ) -> TextResult:
        coincidencia = re.search(r"ESQUEMA:\s*(\w+)", system)
        esquema = coincidencia.group(1) if coincidencia else ""
        respuesta = RESPUESTAS_LLM.get(esquema)
        if esquema == "AnalysisReport" and respuesta is not None:
            respuesta = _informe_de_mercado(messages) or respuesta
        texto = (
            json.dumps(respuesta, ensure_ascii=False)
            if respuesta is not None
            else "(Respuesta simulada sin esquema conocido)"
        )
        entrada = system + "".join(m.content for m in messages)
        return TextResult(texto, self.model, _estimar_tokens(entrada), _estimar_tokens(texto))


class MockVision:
    """Visión simulada: lectura fija de un gráfico alcista."""

    model = "mock-vision"

    def describe_image(self, image: bytes, mime: str, prompt: str) -> TextResult:
        if not image:
            raise ProviderError("La imagen está vacía.")
        if detect_image_mime(image) is None:
            raise ProviderError("La imagen está dañada o no es PNG, JPEG, GIF ni WebP.")
        texto = json.dumps(RESPUESTAS_LLM["ChartReading"], ensure_ascii=False)
        return TextResult(texto, self.model, _estimar_tokens(prompt) + 800, _estimar_tokens(texto))


class MockSTT:
    """STT simulado: transcripción fija; rechaza audio vacío como haría un proveedor real."""

    model = "mock-stt"

    def transcribe(self, audio: bytes, filename: str) -> TranscriptionResult:
        if not audio:
            raise ProviderError("El audio está vacío.")
        return TranscriptionResult(TRANSCRIPCION_DEMO, self.model, DURACION_AUDIO_DEMO_S)


class MockTTS:
    """TTS simulado: devuelve un WAV de silencio."""

    model = "mock-tts"

    def synthesize(self, text: str) -> SpeechResult:
        return SpeechResult(silent_wav(), "audio/wav", self.model, len(text))


class MockImage:
    """Generador de imagen simulado: devuelve un PNG liso."""

    model = "mock-image"

    def generate(self, prompt: str) -> ImageResult:
        return ImageResult(solid_png(640, 360, (30, 58, 95)), "image/png", self.model)


class MockEmbeddings:
    """Embeddings simulados: hashing determinista de palabras (sin acentos) en 256 dimensiones.

    Solo capta coincidencias léxicas (no es multilingüe): sirve para tests y para el modo demo.
    """

    model = "mock-embeddings"
    DIMS = 256

    def embed(
        self, texts: Sequence[str], kind: Literal["query", "document"] = "document"
    ) -> EmbeddingResult:
        vectores = [self._vector(t) for t in texts]
        return EmbeddingResult(vectores, self.model, sum(_estimar_tokens(t) for t in texts))

    def _vector(self, texto: str) -> list[float]:
        plano = "".join(
            c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c)
        )
        v = [0.0] * self.DIMS
        for palabra in re.findall(r"[a-z0-9]+", plano):
            h = zlib.crc32(palabra.encode())
            v[h % self.DIMS] += 1.0 if (h >> 8) & 1 else -1.0
        norma = sum(x * x for x in v) ** 0.5
        return [x / norma for x in v] if norma else v
