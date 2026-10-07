"""Tests que hacen cumplir las reglas de capas del proyecto."""
import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "src" / "finlens"
SDK_IA = {"anthropic", "openai"}
HTTP = {"httpx", "httpx2"}  # cliente HTTP: solo providers/ y sources/


def importaciones(ruta: Path) -> set[str]:
    """Módulos importados por un fichero (nombre completo, p.ej. 'finlens.providers.base')."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    modulos: set[str] = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos.update(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            modulos.add(nodo.module)
    return modulos


def ficheros(*capas: str) -> list[Path]:
    return [f for capa in capas for f in (RAIZ / capa).rglob("*.py")]


def test_ningun_sdk_fuera_de_providers() -> None:
    todos = [f for f in RAIZ.rglob("*.py") if "providers" not in f.relative_to(RAIZ).parts]
    infractores = [
        f"{f.relative_to(RAIZ)} importa {m}"
        for f in todos
        for m in importaciones(f)
        if m.split(".")[0] in SDK_IA
    ]
    assert not infractores, infractores


def test_cliente_http_solo_en_providers_y_sources() -> None:
    permitidas = {"providers", "sources"}
    infractores = [
        f"{f.relative_to(RAIZ)} importa {m}"
        for f in RAIZ.rglob("*.py")
        if f.relative_to(RAIZ).parts[0] not in permitidas
        for m in importaciones(f)
        if m.split(".")[0] in HTTP
    ]
    assert not infractores, infractores


def test_sources_no_usa_sdk_de_ia_ni_providers_ni_negocio() -> None:
    infractores = []
    for f in ficheros("sources"):
        for m in importaciones(f):
            raiz = m.split(".")[0]
            if raiz in SDK_IA or m.startswith(("finlens.providers", "finlens.domain", "finlens.orchestration", "finlens.ui")):
                infractores.append(f"{f.relative_to(RAIZ)} importa {m}")
            if raiz == "streamlit":
                infractores.append(f"{f.relative_to(RAIZ)} importa {m}")
    assert not infractores, infractores


def test_negocio_solo_conoce_el_contrato_de_sources() -> None:
    """domain/ y orchestration/ pueden usar `finlens.sources.base` (contrato), nunca los conectores."""
    infractores = [
        f"{f.relative_to(RAIZ)} importa {m}"
        for f in ficheros("domain")
        for m in importaciones(f)
        if m.startswith("finlens.sources") and m != "finlens.sources.base"
    ]
    assert not infractores, infractores


def test_negocio_solo_depende_de_base_y_no_de_la_ui() -> None:
    infractores = []
    for f in ficheros("domain", "orchestration"):
        for m in importaciones(f):
            if m.startswith("finlens.providers") and m != "finlens.providers.base":
                infractores.append(f"{f.relative_to(RAIZ)} importa {m}")
            if m.split(".")[0] == "streamlit" or m.startswith("finlens.ui"):
                infractores.append(f"{f.relative_to(RAIZ)} importa {m}")
    assert not infractores, infractores


def test_export_solo_depende_de_negocio_y_contratos() -> None:
    """export/ puede usar domain, orchestration, providers.base y sources.base; ni SDKs de IA, HTTP ni UI."""
    infractores = []
    for f in ficheros("export"):
        for m in importaciones(f):
            raiz = m.split(".")[0]
            if raiz in SDK_IA or raiz in HTTP or raiz == "streamlit" or m.startswith("finlens.ui"):
                infractores.append(f"{f.relative_to(RAIZ)} importa {m}")
            if m.startswith("finlens.providers") and m != "finlens.providers.base":
                infractores.append(f"{f.relative_to(RAIZ)} importa {m}")
            if m.startswith("finlens.sources") and m != "finlens.sources.base":
                infractores.append(f"{f.relative_to(RAIZ)} importa {m}")
    assert not infractores, infractores


def test_ninguna_capa_inferior_importa_export() -> None:
    """Solo la UI (y la app) consumen export/."""
    infractores = [
        f"{f.relative_to(RAIZ)} importa {m}"
        for f in ficheros("domain", "orchestration", "providers", "sources")
        for m in importaciones(f)
        if m.startswith("finlens.export")
    ]
    assert not infractores, infractores
