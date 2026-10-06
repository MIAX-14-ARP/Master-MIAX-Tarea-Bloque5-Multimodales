"""Tests que hacen cumplir las reglas de capas del proyecto."""
import ast
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1] / "src" / "finlens"
SDK = {"anthropic", "openai", "httpx", "httpx2"}


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
        if m.split(".")[0] in SDK
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
