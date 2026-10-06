"""Piezas puras de la UI: escape anti-XSS, mapa del pipeline, línea de tiempo y seguimiento en vivo."""
from __future__ import annotations

from types import SimpleNamespace

from finlens.domain.schemas import Citation, Finding, KeyFigure
from finlens.orchestration.trace import TraceStep
from finlens.providers.registry import build_mock_providers
from finlens.ui import components as ui
from finlens.ui import pipeline_map as pm
from finlens.ui.gantt import gantt_chart, timeline
from finlens.ui.live import Tracker, run_live

XSS = '<script>alert(1)</script><img src=x onerror="x()">'
INFO = {c: ("openrouter", f"modelo-{c}") for c in pm.CAPABILITIES}


def test_esc_neutraliza_html_y_no_deja_lineas_en_blanco() -> None:
    salida = ui.esc(XSS + "\n\nsegunda")
    assert "<script>" not in salida and "<img" not in salida
    assert "\n" not in salida and "<br><br>" in salida


def test_el_texto_de_los_modelos_se_escapa_en_todos_los_fragmentos() -> None:
    cita = Citation(origin="documento", location=XSS)
    hallazgo = Finding(statement=XSS, citations=[cita])
    cifra = KeyFigure(name=XSS, value=XSS, period=XSS, citations=[cita])
    fragmentos = [
        ui.findings_html([hallazgo]), ui.correlations_html([hallazgo]), ui.figures_html([cifra], ()),
        ui.limitations_html([XSS]), ui.editor_note(XSS), ui.slot("A", XSS, XSS, nombre=XSS),
        ui.masthead("hoy", {"llm": (XSS, XSS)}, (), XSS), ui.read_card(XSS, XSS, XSS),
    ]
    for html in fragmentos:
        assert "<script>" not in html and "<img src=x" not in html
        assert "\n" not in html  # una sola línea: el Markdown de Streamlit no rompe el bloque


def test_sellos_de_verificacion() -> None:
    check = lambda status, page=None: SimpleNamespace(status=status, page=page)  # noqa: E731
    assert "verificada p.3" in ui.stamp(check("verificada", 3))
    assert "no encontrada en p.5" in ui.stamp(check("no_encontrada", 5))
    assert "sin fuente documental" in ui.stamp(check("sin_fuente_documental"))
    assert "sin verificar" in ui.stamp(None)


def test_las_comprobaciones_se_emparejan_por_nombre_y_valor() -> None:
    cita = [Citation(origin="documento", location="p.1")]
    cifras = [KeyFigure(name="A", value="1", citations=cita), KeyFigure(name="B", value="2", citations=cita)]
    cb = SimpleNamespace(figure_name="B", value="2", status="verificada", page=1)
    assert ui.pair_checks(cifras, [cb]) == [None, cb]


def test_modo_honesto_total_parcial_y_real() -> None:
    assert ui.mode_summary(INFO, pm.CAPABILITIES)[1] == "Modo demo"
    clase, etiqueta, frase = ui.mode_summary(INFO, ("stt", "tts"))
    assert etiqueta == "Demo parcial" and "STT, TTS" in frase
    assert ui.mode_summary(INFO, ())[1] == "Modelos reales"


def test_info_de_proveedores_desde_el_contrato() -> None:
    providers = build_mock_providers()
    info = pm.provider_info(providers)
    assert set(info) == set(pm.CAPABILITIES) and all(b == "mock" for b, _ in info.values())
    assert set(pm.mock_capabilities(providers)) == set(pm.CAPABILITIES)


def test_los_pasos_de_la_traza_se_casan_con_su_nodo() -> None:
    pasos = [TraceStep(n, "m", 0.1) for n in (
        "Ingesta e índice", "Lectura del gráfico", "Transcripción de audio", "Recuperación", "Análisis (LLM)",
        "Guardrails de compliance", "Verificación de cifras", "Resumen en audio", "Prompt de infografía",
        "Generación de infografía", "Composición de infografía",
    )]
    casados = pm.match_steps(pasos)
    assert {k: v.step for k, v in casados.items()} == {
        "ingest": "Ingesta e índice", "vision": "Lectura del gráfico", "stt": "Transcripción de audio",
        "retrieve": "Recuperación", "analysis": "Análisis (LLM)", "guard": "Guardrails de compliance",
        "verify": "Verificación de cifras", "tts": "Resumen en audio", "prompt": "Prompt de infografía",
        "image": "Generación de infografía", "compose": "Composición de infografía",
    }


def test_estados_del_mapa_final_fallo_simulado_y_omitido() -> None:
    fase1 = [TraceStep("Ingesta e índice", "pypdf + TF-IDF", 0.1),
             TraceStep("Lectura del gráfico", "—", 0.2, "imagen dañada", ok=False),
             TraceStep("Análisis (LLM)", "modelo-llm", 1.0, cost_usd=0.01)]
    vistas = pm.build_nodes(INFO, ("llm",), steps1=fase1, steps2=(), skipped=frozenset({"tts"}))
    assert vistas["ingest"].status == "ok"
    assert vistas["vision"].status == "fallo" and vistas["vision"].note == "imagen dañada"
    assert vistas["analysis"].status == "simulado" and vistas["analysis"].cost == 0.01
    assert vistas["stt"].status == "omitido" and vistas["tts"].status == "omitido"
    html = pm.map_html(vistas, headline="x", live=False, with_compose=True)
    assert html.count('class="fl-node ') == 11 and "imagen dañada" in html


def test_estados_en_vivo_durante_la_fase_1() -> None:
    hechos = [TraceStep("Transcripción de audio", "modelo-stt", 1.2)]
    vistas = pm.build_nodes(INFO, (), live=["Lectura del gráfico"], live_steps=hechos, live_phase=1)
    assert vistas["vision"].status == "en_curso"
    assert vistas["stt"].status == "ok" and vistas["stt"].seconds == 1.2
    assert vistas["analysis"].status == "pendiente" and vistas["tts"].status == "pendiente"


def test_linea_de_tiempo_reconstruye_el_paralelismo() -> None:
    pasos = [
        TraceStep("Ingesta e índice", "pypdf", 1.0),
        TraceStep("Lectura del gráfico", "v", 2.0, parallel=True),
        TraceStep("Transcripción de audio", "s", 3.0, parallel=True),
        TraceStep("Análisis (LLM)", "l", 1.0),
        TraceStep("Resumen en audio", "t", 2.0, parallel=True),
        TraceStep("Prompt de infografía", "l", 1.0, parallel=True),
        TraceStep("Generación de infografía", "i", 1.5, parallel=True),
    ]
    barras = {b.step: (b.start, b.end) for b in timeline(pasos)}
    assert barras["Lectura del gráfico"] == (1.0, 3.0) and barras["Transcripción de audio"] == (1.0, 4.0)
    assert barras["Análisis (LLM)"] == (4.0, 5.0)
    assert barras["Resumen en audio"] == (5.0, 7.0)
    assert barras["Prompt de infografía"] == (5.0, 6.0) and barras["Generación de infografía"] == (6.0, 7.5)
    assert gantt_chart(pasos).to_dict()["layer"]  # el gráfico se construye


def test_tracker_y_ejecucion_en_vivo_con_on_step() -> None:
    tracker = Tracker()
    tracker("Análisis (LLM)", "start", None)
    assert tracker.snapshot() == (("Análisis (LLM)",), ())
    paso = TraceStep("Análisis (LLM)", "m", 0.1)
    tracker("Análisis (LLM)", "end", paso)
    assert tracker.snapshot() == ((), (paso,))

    ticks: list[tuple] = []

    def fase(on_step):  # así llama el pipeline al callback
        on_step("Ingesta e índice", "start", None)
        on_step("Ingesta e índice", "end", TraceStep("Ingesta e índice", "pypdf", 0.01))
        return "hecho"

    assert run_live(fase, lambda en_curso, hechos, t: ticks.append((en_curso, hechos))) == "hecho"


def test_sello_con_texto_hallado_y_contradicciones() -> None:
    check = SimpleNamespace(status="verificada", page=5, matched="39,864")
    assert "verificada p.5 · «39,864»" in ui.stamp(check)
    cita = [Citation(origin="audio", location="")]
    html = ui.correlations_html([Finding(statement="El audio contradice", citations=cita)], tension=True)
    assert "Contradicción entre fuentes" in html and "is-tension" in html
