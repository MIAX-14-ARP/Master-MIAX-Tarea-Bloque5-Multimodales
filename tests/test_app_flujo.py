"""Flujo completo de la app de Streamlit en modo demo (sin red ni claves)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from finlens.config import get_settings

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture(autouse=True)
def entorno_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def arrancar() -> AppTest:
    return AppTest.from_file(APP, default_timeout=60).run()


def analizar(at: AppTest) -> AppTest:
    return at.button[0].click().run()


def textos(at: AppTest) -> str:
    """Todo el texto visible relevante de la página, para buscar contenido."""
    partes = [e.value for e in (*at.markdown, *at.subheader, *at.caption, *at.warning, *at.error, *at.info)]
    for tabla in at.table:
        partes.append(tabla.value.to_string())
    return "\n".join(partes)


def test_la_pantalla_inicial_ofrece_el_formulario_en_modo_demo() -> None:
    at = arrancar()
    assert not at.exception
    assert any("Modo demo" in w.value for w in at.warning)
    assert at.checkbox[0].value is True and at.button[0].label == "Analizar"
    assert not at.tabs  # aún no hay resultados


def test_flujo_completo_muestra_informe_traza_y_medios() -> None:
    at = analizar(arrancar())
    assert not at.exception
    assert [t.label for t in at.tabs] == [
        "Informe", "Entradas leídas", "Audio e infografía", "Chat", "Traza de modelos",
    ]
    contenido = textos(at)
    assert "Cifras clave" in contenido and "Margen operativo" in contenido
    assert "documento p.3" in contenido  # las afirmaciones citan su fuente
    assert "Análisis (LLM)" in contenido and "Lectura del gráfico" in contenido
    assert "Resumen en audio" in contenido and "Generación de infografía" in contenido
    assert "no constituye asesoramiento" in contenido.lower()
    assert at.session_state["media"].audio is not None and at.session_state["media"].image is not None
    assert len(at.get("audio")) == 1 and len(at.get("image")) == 1


def test_la_traza_de_la_ui_incluye_los_pasos_de_texto_audio_imagen() -> None:
    at = analizar(arrancar())
    filas = {fila["Paso"].replace(" ⇉", "") for fila in at.table[-1].value.to_dict("records")}
    assert {"Ingesta e índice", "Lectura del gráfico", "Transcripción de audio", "Análisis (LLM)",
            "Resumen en audio", "Prompt de infografía", "Generación de infografía"} <= filas


def test_chat_de_seguimiento() -> None:
    at = analizar(arrancar())
    at.chat_input[0].set_value("¿Cuál fue el margen operativo?").run()
    assert not at.exception
    assert [m.name for m in at.chat_message] == ["user", "assistant"]
    assert "Chat de seguimiento" in textos(at)


def test_repetir_el_mismo_analisis_usa_la_cache() -> None:
    at = analizar(arrancar())
    assert at.session_state["desde_cache"] is False
    at = analizar(at)
    assert at.session_state["desde_cache"] is True
    assert any("caché" in i.value for i in at.info)
    assert at.session_state["media"] is not None  # los medios también salen de caché


def test_sin_pdf_se_pide_el_informe() -> None:
    at = arrancar()
    at.checkbox[0].uncheck().run()
    at = analizar(at)
    assert not at.exception
    assert any("al menos el informe" in e.value for e in at.error)
    assert not at.tabs


def test_con_claves_la_app_arranca_con_apis_reales_y_pide_los_archivos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    get_settings.cache_clear()
    at = arrancar()
    assert not at.exception
    assert any("APIs reales" in s.value for s in at.success)
    assert [c.label for c in at.checkbox] == ["Generar resumen en audio", "Generar infografía"]  # sin ejemplos
    at = analizar(at)  # sin PDF no se llama a ninguna API
    assert any("al menos el informe" in e.value for e in at.error)


def test_la_traza_muestra_los_tokens_de_los_pasos_con_llm() -> None:
    at = analizar(arrancar())
    filas = {f["Paso"]: f for f in at.table[-1].value.to_dict("records")}
    assert filas["Análisis (LLM)"]["Tokens ent./sal."] != "—"
    assert filas["Ingesta e índice"]["Tokens ent./sal."] == "—"


def test_se_puede_omitir_el_audio_y_la_infografia() -> None:
    at = arrancar()
    at.checkbox[1].uncheck()  # audio
    at.checkbox[2].uncheck()  # infografía
    at = analizar(at)
    assert not at.exception
    media = at.session_state["media"]
    assert media.audio is None and media.image is None and media.audio_skipped and media.image_skipped
    assert media.trace == () and not at.get("audio") and not at.get("image")
    assert any(c.value == "No solicitado." for c in at.caption)


def test_omitir_solo_la_infografia_mantiene_el_audio() -> None:
    at = arrancar()
    at.checkbox[2].uncheck()
    media = analizar(at).session_state["media"]
    assert media.audio is not None and media.image is None and media.image_skipped
    assert [s.step for s in media.trace] == ["Resumen en audio"] and not media.trace[0].parallel
