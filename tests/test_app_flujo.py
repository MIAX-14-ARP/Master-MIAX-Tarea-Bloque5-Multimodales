"""Flujo completo de la app de Streamlit en modo demo (sin red ni claves)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from finlens.config import get_settings
from finlens.ui import demo_samples

APP = str(Path(__file__).resolve().parents[1] / "app.py")
PESTANAS = ["Informe", "Entradas leídas", "Audio e infografía", "Chat", "Traza de modelos"]


@pytest.fixture(autouse=True)
def entorno_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")
    for nombre in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(nombre, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def arrancar() -> AppTest:
    return AppTest.from_file(APP, default_timeout=60).run()


def boton_analizar(at: AppTest):
    return next(b for b in at.button if b.label == "Analizar")


def analizar(at: AppTest) -> AppTest:
    return boton_analizar(at).click().run()


def textos(at: AppTest) -> str:
    """Todo el texto (y HTML propio) de la página, para buscar contenido."""
    partes = [e.value for e in (*at.markdown, *at.caption, *at.warning, *at.error, *at.info)]
    for tabla in at.table:
        partes.append(tabla.value.to_string())
    return "\n".join(partes)


def test_la_pantalla_inicial_ofrece_tres_ranuras_y_ejemplos_en_modo_demo() -> None:
    at = arrancar()
    assert not at.exception
    contenido = textos(at)
    assert "Modo demo" in contenido
    assert all(r in contenido for r in ("Informe anual", "Gráfico de cotización", "Audio"))
    assert at.toggle[0].value is True  # materiales de ejemplo activados por defecto en demo
    assert boton_analizar(at).label == "Analizar"
    assert not at.tabs and 'class="fl-map"' not in contenido  # sin resultados ni mapa todavía


def test_flujo_completo_muestra_mapa_informe_traza_y_medios() -> None:
    at = analizar(arrancar())
    assert not at.exception
    assert [t.label for t in at.tabs] == PESTANAS
    contenido = textos(at)
    # Mapa del pipeline: un nodo por paso, con estado y modelo real de cada capacidad.
    assert 'class="fl-map"' in contenido and "st-simulado" in contenido
    assert "mock-vision" in contenido and "mock-stt" in contenido and "Fase II" in contenido
    # Nota de research con cifras grandes, sellos de verificación y citas.
    assert "Cifras clave" in contenido and "Margen operativo" in contenido
    assert "fl-stamp v" in contenido and "verificada" in contenido
    assert "documento p.3" in contenido  # las afirmaciones citan su fuente (chip con etiqueta completa)
    assert "Correlación entre modalidades" in contenido
    # Traza y medios.
    assert "Análisis (LLM)" in contenido and "Lectura del gráfico" in contenido
    assert "Resumen en audio" in contenido and "Generación de infografía" in contenido
    assert "no constituye asesoramiento" in contenido.lower()
    media = at.session_state["media"]
    assert media.audio is not None and media.image is not None
    assert len(at.get("audio")) == 1
    assert at.get("vega_lite_chart") or at.get("arrow_vega_lite_chart")  # Gantt de la traza


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
    contenido = textos(at)
    assert "Chat de seguimiento" in contenido and "fl-chip" in contenido


def test_las_preguntas_sugeridas_lanzan_el_chat() -> None:
    at = analizar(arrancar())
    sugerida = next(b for b in at.button if b.label.startswith("¿Cuál fue el margen"))
    at = sugerida.click().run()
    assert not at.exception
    assert [m.name for m in at.chat_message] == ["user", "assistant"]


def test_repetir_el_mismo_analisis_usa_la_cache() -> None:
    at = analizar(arrancar())
    assert at.session_state["desde_cache"] is False
    at = analizar(at)
    assert at.session_state["desde_cache"] is True
    assert "Recuperado de la caché" in textos(at)
    assert at.session_state["media"] is not None  # los medios también salen de caché


def test_sin_pdf_se_pide_el_informe() -> None:
    at = arrancar()
    at.toggle[0].set_value(False).run()
    at = analizar(at)
    assert not at.exception
    assert "al menos el informe" in textos(at)
    assert not at.tabs


def test_un_pdf_invalido_muestra_el_error_y_la_traza_hasta_el_fallo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_samples, "demo_pdf", lambda: b"esto no es un PDF")
    at = analizar(arrancar())
    assert not at.exception
    contenido = textos(at)
    assert "Análisis interrumpido" in contenido and "st-fallo" in contenido
    assert at.session_state["error"] is not None and not at.tabs


def test_con_claves_la_app_arranca_con_apis_reales_y_pide_los_archivos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    get_settings.cache_clear()
    at = arrancar()
    assert not at.exception
    contenido = textos(at)
    assert "Modo demo" not in contenido and "fl-prov__cell is-mock" not in contenido
    assert [t.label for t in at.toggle][1:] == ["Generar resumen en audio", "Generar infografía"]
    assert at.toggle[0].value is False  # con APIs reales los ejemplos no se usan por defecto
    at = analizar(at)  # sin PDF no se llama a ninguna API
    assert "al menos el informe" in textos(at)


def test_la_traza_muestra_los_tokens_de_los_pasos_con_llm() -> None:
    at = analizar(arrancar())
    filas = {f["Paso"]: f for f in at.table[-1].value.to_dict("records")}
    assert filas["Análisis (LLM)"]["Tokens ent./sal."] != "—"
    assert filas["Ingesta e índice"]["Tokens ent./sal."] == "—"


def test_se_puede_omitir_el_audio_y_la_infografia() -> None:
    at = arrancar()
    at.toggle[1].set_value(False)  # audio
    at.toggle[2].set_value(False)  # infografía
    at = analizar(at)
    assert not at.exception
    media = at.session_state["media"]
    assert media.audio is None and media.image is None and media.audio_skipped and media.image_skipped
    assert media.trace == () and not at.get("audio")
    assert any(c.value == "No solicitado." for c in at.caption)
    assert "st-omitido" in textos(at)  # el mapa marca los nodos no solicitados


def test_omitir_solo_la_infografia_mantiene_el_audio() -> None:
    at = arrancar()
    at.toggle[2].set_value(False)
    media = analizar(at).session_state["media"]
    assert media.audio is not None and media.image is None and media.image_skipped
    assert [s.step for s in media.trace] == ["Resumen en audio"] and not media.trace[0].parallel
