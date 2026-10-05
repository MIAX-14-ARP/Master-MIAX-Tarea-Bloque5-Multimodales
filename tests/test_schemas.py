"""Tests de los esquemas de salida estructurada."""
import json

import pytest
from pydantic import ValidationError

from finlens.domain import schemas
from finlens.providers.mock import RESPUESTAS_LLM


@pytest.mark.parametrize("nombre", sorted(RESPUESTAS_LLM))
def test_respuestas_mock_cumplen_su_esquema(nombre: str) -> None:
    clase = getattr(schemas, nombre)
    clase.model_validate(json.loads(json.dumps(RESPUESTAS_LLM[nombre])))


def test_cita_genera_etiqueta_legible() -> None:
    assert schemas.Citation(origin="documento", location="p.3").label == "documento p.3"
    assert schemas.Citation(origin="grafico").label == "grafico"


def test_afirmacion_sin_citas_es_invalida() -> None:
    with pytest.raises(ValidationError):
        schemas.Finding(statement="El margen subió", citations=[])


def test_cifra_sin_citas_es_invalida() -> None:
    with pytest.raises(ValidationError):
        schemas.KeyFigure(name="Margen", value="18 %", citations=[])


def test_origen_de_cita_desconocido_es_invalido() -> None:
    with pytest.raises(ValidationError):
        schemas.Citation(origin="rumor", location="p.1")  # type: ignore[arg-type]


def test_respuesta_de_chat_con_base_exige_citas() -> None:
    with pytest.raises(ValidationError):
        schemas.ChatAnswer(answer="Subió un 5 %")


def test_respuesta_de_chat_sin_base_no_exige_citas() -> None:
    respuesta = schemas.ChatAnswer(answer="No consta en los materiales.", grounded=False)
    assert respuesta.citations == []
