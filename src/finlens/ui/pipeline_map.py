"""Mapa del pipeline: qué nodo es qué modelo y en qué estado está. Solo presentación.

El estado de cada nodo sale de la traza (`TraceStep`) cuando la fase ha terminado, o del
seguimiento en vivo de las llamadas a proveedores (`ui.live`) mientras se ejecuta.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from finlens.orchestration.trace import TraceStep
from finlens.providers.base import Providers
from finlens.ui.components import esc

Status = Literal["pendiente", "en_curso", "ok", "simulado", "fallo", "omitido"]
CAPABILITIES = ("llm", "vision", "stt", "tts", "image", "embeddings")
CAP_LABEL = {"llm": "LLM", "vision": "VISIÓN", "stt": "STT", "tts": "TTS", "image": "IMAGEN",
             "embeddings": "EMBED", None: "LOCAL"}
STATUS_LABEL: dict[str, str] = {
    "pendiente": "pendiente", "en_curso": "en curso", "ok": "ok", "simulado": "simulado",
    "fallo": "fallo", "omitido": "omitido",
}


@dataclass(frozen=True)
class NodeSpec:
    """Nodo del diagrama: título, capacidad (None = paso local) y palabras para casar la traza."""

    key: str
    title: str
    capability: str | None
    keywords: tuple[str, ...]
    phase: int
    local_model: str = ""
    alt_capability: str | None = None  # capacidad que lo atiende si existe (p.ej. embeddings)


@dataclass(frozen=True)
class Stage:
    label: str
    lanes: tuple[tuple[str, ...], ...]  # carriles en paralelo, cada uno con nodos en serie

    @property
    def parallel(self) -> bool:
        return len(self.lanes) > 1


NODES: dict[str, NodeSpec] = {
    n.key: n
    for n in (
        NodeSpec("ingest", "Ingesta e índice", None, ("ingesta",), 1, "pypdf + TF-IDF", "embeddings"),
        NodeSpec("market", "Datos de mercado", None, ("datos de mercado",), 1, "Yahoo · Hyperliquid"),
        NodeSpec("technicals", "Indicadores técnicos", None, ("indicadores",), 1, "numpy"),
        NodeSpec("chartgen", "Gráfico generado", None, ("grafico generado",), 1, "matplotlib"),
        NodeSpec("sec", "Fundamentales SEC", None, ("fundamentales",), 1, "SEC EDGAR XBRL"),
        NodeSpec("contrast", "Contraste visión ↔ datos", None, ("contraste",), 1, "reglas deterministas"),
        NodeSpec("vision", "Lectura del gráfico", "vision", ("grafico",), 1),
        NodeSpec("stt", "Transcripción", "stt", ("transcrip",), 1),
        NodeSpec("retrieve", "Recuperación", None, ("recuperacion",), 1, "TF-IDF", "embeddings"),
        NodeSpec("analysis", "Análisis con citas", "llm", ("analisis",), 1),
        NodeSpec("verify", "Verificación de cifras", None, ("verificacion",), 1, "reglas deterministas"),
        NodeSpec("guard", "Guardrails compliance", None, ("guardrail",), 1, "reglas deterministas"),
        NodeSpec("tts", "Resumen hablado", "tts", ("resumen en audio", "tts", "sintesis"), 2),
        NodeSpec("prompt", "Prompt de ilustración", "llm", ("prompt",), 2),
        NodeSpec("compose", "Composición", None, ("composicion",), 2, "matplotlib + Pillow"),
        NodeSpec("image", "Ilustración", "image", ("infografia", "ilustracion", "imagen"), 2),
    )
}
# Orden de casado: el primero que coincide gana (p.ej. «prompt de infografía» antes que «infografía»).
_MATCH_ORDER = ("chartgen", "market", "technicals", "sec", "contrast", "ingest", "vision", "stt", "retrieve", "analysis", "verify", "guard", "tts", "prompt",
                "compose", "image")

PHASE_1 = (
    Stage("", (("ingest",),)),
    Stage("en paralelo", (("vision",), ("stt",))),
    Stage("", (("retrieve",),)),
    Stage("", (("analysis",),)),
    Stage("", (("verify",),)),
    Stage("", (("guard",),)),
)


# Con datos de mercado (spec 06 §10.3) la percepción va toda en paralelo y el razonamiento después.
PERCEPTION_MARKET = (
    Stage("en paralelo", (("ingest",), ("market", "technicals", "chartgen", "vision", "contrast"), ("stt",), ("sec",))),
)
REASONING = (
    Stage("", (("retrieve",),)),
    Stage("", (("analysis",),)),
    Stage("", (("verify",),)),
    Stage("", (("guard",),)),
)
MARKET_NODES = frozenset({"market", "technicals", "chartgen", "sec", "contrast"})


def phase_2(with_compose: bool) -> tuple[Stage, ...]:
    imagen = ("prompt", "image", "compose") if with_compose else ("prompt", "image")
    return (Stage("en paralelo", (("tts",), imagen)),)


def phases(with_compose: bool, with_market: bool) -> list[tuple[str, tuple[Stage, ...]]]:
    """Filas del diagrama: (etiqueta, etapas)."""
    if with_market:
        return [("Fase I · percepción", PERCEPTION_MARKET), ("Fase I · razonamiento", REASONING),
                ("Fase II · medios", phase_2(with_compose))]
    return [("Fase I · análisis", PHASE_1), ("Fase II · medios", phase_2(with_compose))]


@dataclass(frozen=True)
class NodeView:
    spec: NodeSpec
    status: Status
    backend: str
    model: str
    seconds: float | None = None
    cost: float | None = None
    note: str = ""


# --- Proveedores ----------------------------------------------------------------------------


def _backend_from_object(obj: object) -> str:
    nombre = type(obj).__name__.lower()
    for backend in ("openrouter", "anthropic", "openai", "mock"):
        if backend in nombre:
            return backend
    return nombre or "?"


def provider_info(providers: Providers) -> dict[str, tuple[str, str]]:
    """capacidad → (backend, modelo). Usa `Providers.info` si existe; si no, lo deduce."""
    info = getattr(providers, "info", None)
    if info:
        return {i.capability: (i.backend, i.model) for i in info}
    salida = {}
    for cap in CAPABILITIES:
        obj = getattr(providers, cap, None)
        if obj is None:
            continue
        backend = "mock" if providers.is_demo else _backend_from_object(obj)
        salida[cap] = (backend, str(getattr(obj, "model", "?")))
    return salida


def mock_capabilities(providers: Providers) -> tuple[str, ...]:
    """Capacidades simuladas (contrato `Providers.mock_capabilities`, con respaldo)."""
    caps = getattr(providers, "mock_capabilities", None)
    if caps is not None:
        return tuple(caps)
    return tuple(c for c, (backend, _) in provider_info(providers).items() if backend == "mock")


# --- Estado ---------------------------------------------------------------------------------


def _fold(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.lower()


def match_steps(steps: Sequence[TraceStep]) -> dict[str, TraceStep]:
    """Asigna cada paso de la traza al primer nodo cuyas palabras clave aparecen en su nombre."""
    casados: dict[str, TraceStep] = {}
    for paso in steps:
        nombre = _fold(paso.step)
        for clave in _MATCH_ORDER:
            if clave not in casados and any(k in nombre for k in NODES[clave].keywords):
                casados[clave] = paso
                break
    return casados


def _live_status(key: str, live: Mapping[str, str]) -> Status:
    """Estado deducido de las llamadas en curso de la fase (capacidad → en_curso/ok/fallo)."""
    spec = NODES[key]
    if spec.capability:
        return live.get(spec.capability, "pendiente")  # type: ignore[return-value]
    if key == "ingest":
        return "ok" if live else "en_curso"
    if key == "retrieve":
        if "llm" in live:
            return "ok"
        return "en_curso" if live and all(v != "en_curso" for v in live.values()) else "pendiente"
    if key in ("verify", "guard"):
        return "en_curso" if live.get("llm") == "ok" else "pendiente"
    if key == "compose":
        return "en_curso" if live.get("image") == "ok" else "pendiente"
    return "pendiente"


def build_nodes(
    info: Mapping[str, tuple[str, str]],
    mocks: Sequence[str],
    *,
    steps1: Sequence[TraceStep] | None = None,
    steps2: Sequence[TraceStep] | None = None,
    live: Mapping[str, str] | None = None,
    live_phase: int | None = None,
    skipped: frozenset[str] = frozenset(),
) -> dict[str, NodeView]:
    """Vista de cada nodo. `stepsN=None` significa que la fase N no ha terminado."""
    casados1 = match_steps(steps1) if steps1 is not None else {}
    casados2 = match_steps(steps2) if steps2 is not None else {}
    vistas: dict[str, NodeView] = {}
    for key, spec in NODES.items():
        cap = spec.capability or (spec.alt_capability if spec.alt_capability in info else None)
        backend, modelo = info.get(cap or "", ("local", spec.local_model))
        terminada = (steps1 if spec.phase == 1 else steps2) is not None
        paso = (casados1 if spec.phase == 1 else casados2).get(key)
        segundos = coste = None
        nota = ""
        status: Status
        if paso is not None:
            status = "ok" if paso.ok else "fallo"
            if paso.model and paso.model != "—":
                modelo = paso.model
            segundos, coste = paso.seconds, paso.cost_usd
            nota = paso.note
        elif key in skipped:
            status = "omitido"
        elif terminada:
            imagen = casados2.get("image")
            status = "ok" if key == "compose" and imagen is not None and imagen.ok else "omitido"
        elif live is not None and live_phase == spec.phase:
            status = _live_status(key, live)
        else:
            status = "pendiente"
        if status == "ok" and cap in mocks:
            status = "simulado"
        vistas[key] = NodeView(spec, status, backend, modelo, segundos, coste, nota)
    return vistas


# --- HTML -----------------------------------------------------------------------------------


def _node_html(v: NodeView, idx: int) -> str:
    metricas = ""
    if v.seconds is not None:
        metricas = f"{v.seconds:.2f} s"
        if v.cost:
            metricas += f" · ${v.cost:.4f}"
    local = v.backend == "local"
    origen = v.model if local else f"{v.backend} · {v.model}"
    tag = CAP_LABEL[v.spec.capability] if v.spec.capability else ("LOCAL" if local else "EMBED")
    error = f'<div class="fl-node__err">{esc(v.note)}</div>' if v.status == "fallo" and v.note else ""
    etiqueta = STATUS_LABEL[v.status]
    return (
        f'<div class="fl-node st-{v.status}" role="listitem" '
        f'aria-label="{esc(v.spec.title)}: {etiqueta}" style="animation-delay:{idx * 40}ms">'
        f'<div class="fl-node__top"><span>{idx:02d}</span>'
        f'<span class="fl-node__cap">{tag}</span></div>'
        f'<div class="fl-node__t">{esc(v.spec.title)}</div>'
        f'<div class="fl-node__m" title="{esc(origen)}">{esc(origen)}</div>'
        f'<div class="fl-node__f"><span class="fl-node__s">{etiqueta}</span>'
        f'<span class="fl-node__x">{esc(metricas)}</span></div>{error}</div>'
    )


def _phase_html(label: str, stages: Sequence[Stage], vistas: Mapping[str, NodeView], start: int) -> tuple[str, int]:
    partes, idx = [], start
    flecha = '<span class="fl-arrow" aria-hidden="true"></span>'
    for i, etapa in enumerate(stages):
        carriles = []
        for carril in etapa.lanes:
            nodos = []
            for clave in carril:
                idx += 1
                nodos.append(_node_html(vistas[clave], idx))
            carriles.append(f'<div class="fl-lane">{flecha.join(nodos)}</div>')
        clases = "fl-stage" + (" is-par" if etapa.parallel else "")
        clases += " is-wide" if max(len(c) for c in etapa.lanes) > 1 else ""
        tag = f'<div class="fl-stage__tag">‖ {esc(etapa.label)}</div>' if etapa.label else ""
        partes.append(f'<li class="{clases}">{tag}{"".join(carriles)}</li>')
        if i < len(stages) - 1:
            partes.append(flecha)
    html = (
        f'<div class="fl-phase"><div class="fl-phase__label">{esc(label)}</div>'
        f'<ol class="fl-flow" role="list">{"".join(partes)}</ol></div>'
    )
    return html, idx


def map_html(vistas: Mapping[str, NodeView], *, headline: str, live: bool, with_compose: bool,
             with_market: bool = False) -> str:
    """Diagrama completo (fases en filas) listo para `st.markdown(..., unsafe_allow_html=True)`."""
    filas, n = [], 0
    for etiqueta, etapas in phases(with_compose, with_market):
        fila, n = _phase_html(etiqueta, etapas, vistas, n)
        filas.append(fila)
    estado = '<span class="is-live">● en ejecución</span>' if live else "<span>traza registrada</span>"
    leyenda = (
        '<div class="fl-legend" aria-hidden="true"><span><i class="lg-ok"></i>modelo real</span>'
        '<span><i class="lg-sim"></i>simulado</span><span><i class="lg-run"></i>en curso</span>'
        '<span><i class="lg-fail"></i>fallo</span><span><i class="lg-pend"></i>pendiente / omitido</span></div>'
    )
    return (
        '<section class="fl-map" lang="es" aria-label="Cadena de modelos">'
        f'<div class="fl-map__head"><b>{esc(headline)}</b>{estado}</div>'
        f"{''.join(filas)}{leyenda}</section>"
    )
