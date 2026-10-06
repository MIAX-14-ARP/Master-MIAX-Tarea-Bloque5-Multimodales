"""Esquemas Pydantic de las salidas estructuradas del LLM. Toda afirmación cita su fuente."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Origin = Literal["documento", "grafico", "audio", "mercado", "sec"]


class Citation(BaseModel):
    """Referencia a la fuente de una afirmación, p.ej. «documento p.3», «grafico», «audio», «mercado» o «sec»."""

    origin: Origin
    location: str = ""

    @property
    def label(self) -> str:
        return f"{self.origin} {self.location}".strip()


class Finding(BaseModel):
    """Afirmación respaldada por al menos una cita."""

    statement: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


class KeyFigure(BaseModel):
    """Cifra relevante extraída del informe, con su fuente."""

    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    period: str = ""
    citations: list[Citation] = Field(min_length=1)


class ChartReading(BaseModel):
    """Lectura del gráfico de velas hecha por el modelo de visión."""

    trend: Literal["alcista", "bajista", "lateral", "indeterminada"]
    description: str = Field(min_length=1)
    observations: list[str] = []


class AnalysisReport(BaseModel):
    """Informe estructurado que cruza documento, gráfico y audio."""

    summary: str = Field(min_length=1)
    key_figures: list[KeyFigure] = []
    chart_reading: Finding | None = None
    management_statements: list[Finding] = []
    correlations: list[Finding] = []
    contradictions: list[Finding] = []  # discrepancias entre modalidades (informe/gráfico/audio)
    limitations: list[str] = []
    spoken_summary: str = Field(min_length=1)


class ChatAnswer(BaseModel):
    """Respuesta del chat de seguimiento. Si no hay base en los materiales, grounded=False."""

    answer: str = Field(min_length=1)
    grounded: bool = True
    citations: list[Citation] = []

    @model_validator(mode="after")
    def _exigir_citas_si_hay_base(self) -> ChatAnswer:
        if self.grounded and not self.citations:
            raise ValueError("una respuesta con base en los materiales debe citar sus fuentes")
        return self


class InfographicPrompt(BaseModel):
    """Prompt que el LLM redacta para el modelo de imagen."""

    prompt: str = Field(min_length=1)
