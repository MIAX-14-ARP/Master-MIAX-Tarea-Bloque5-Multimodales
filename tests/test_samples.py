"""Los materiales de samples/ y el script de medición se mantienen coherentes con el pipeline."""
import importlib.util
import sys
from pathlib import Path

import pytest

from finlens.domain.cost import Tariffs
from finlens.orchestration.metrics import summarize
from finlens.orchestration.pipeline import PipelineError, analyze
from finlens.providers.registry import build_mock_providers

RAIZ = Path(__file__).resolve().parents[1]
SAMPLES = RAIZ / "samples"
TARIFAS = Tariffs(2.0, 10.0, 0.006, 15.0, 0.04)


@pytest.fixture(scope="module")
def medir():
    """Importa scripts/medir.py como módulo (scripts/ no es un paquete)."""
    spec = importlib.util.spec_from_file_location("medir", RAIZ / "scripts" / "medir.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["medir"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_el_caso_de_demo_se_carga_completo(medir) -> None:
    entrada = medir.cargar_caso(SAMPLES / "00_demo_ficticio")
    assert entrada and entrada.pdf and entrada.chart and entrada.audio
    assert entrada.chart_mime == "image/png" and entrada.audio_role == "conferencia"
    assert "margen operativo" in entrada.question


def test_carpetas_sin_informe_se_ignoran(medir) -> None:
    assert medir.cargar_caso(SAMPLES / "04_entradas_invalidas") is None


def test_el_caso_de_demo_se_mide_de_extremo_a_extremo(medir) -> None:
    providers = build_mock_providers()
    casos = {"demo": medir.cargar_caso(SAMPLES / "00_demo_ficticio")}
    registros = medir.medir(providers, TARIFAS, casos, 2, True, 300_000)
    assert len(registros) == 2
    assert summarize(registros).step("Generación de infografía").runs_ok == 2


def test_voz_como_pregunta_se_detecta_por_el_nombre(medir, tmp_path) -> None:
    caso = tmp_path / "c"
    caso.mkdir()
    (caso / "informe.pdf").write_bytes((SAMPLES / "00_demo_ficticio" / "informe.pdf").read_bytes())
    (caso / "pregunta_voz.mp3").write_bytes(b"audio")
    entrada = medir.cargar_caso(caso)
    assert entrada.audio_role == "pregunta" and entrada.audio_name == "pregunta_voz.mp3"
    assert entrada.chart is None


def test_las_entradas_invalidas_dan_errores_controlados_y_no_excepciones() -> None:
    providers = build_mock_providers()
    invalidas = SAMPLES / "04_entradas_invalidas"
    from finlens.orchestration.pipeline import AnalysisInput

    with pytest.raises(PipelineError, match="no contiene texto"):
        analyze(providers, TARIFAS, AnalysisInput(pdf=(invalidas / "sin_texto.pdf").read_bytes()))
    with pytest.raises(PipelineError, match="dañado o no es un PDF"):
        analyze(providers, TARIFAS, AnalysisInput(pdf=(invalidas / "no_es_un_pdf.pdf").read_bytes()))
    pdf = (SAMPLES / "00_demo_ficticio" / "informe.pdf").read_bytes()
    resultado = analyze(
        providers, TARIFAS, AnalysisInput(pdf=pdf, audio=(invalidas / "audio_vacio.wav").read_bytes())
    )
    assert resultado.report.summary and any("audio está vacío" in w for w in resultado.warnings)
    resultado = analyze(
        providers, TARIFAS, AnalysisInput(pdf=pdf, chart=(invalidas / "imagen_corrupta.png").read_bytes())
    )
    assert resultado.report.summary and resultado.chart is None
    assert any("dañada o no es PNG" in w for w in resultado.warnings)


def test_el_informe_de_robustez_del_script_no_lanza(medir, capsys) -> None:
    medir.probar_robustez(build_mock_providers(), TARIFAS, SAMPLES / "04_entradas_invalidas")
    salida = capsys.readouterr().out
    assert salida.count("error controlado") == 2 and salida.count("informe entregado con avisos") == 2
