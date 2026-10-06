"""§0 Cerebro: la cadena de modelos de FinLens dibujada como una red neuronal 3D.

Metáfora, no arquitectura inventada: cada neurona etiquetada es una entrada aportada, un modelo
real (`Providers.info`) o un paso local que aparece en la traza, y una salida entregada. Las
neuronas sin etiqueta del fondo son decorativas (densidad visual) y se dibujan mucho más tenues.

- Antes de analizar: la red «respira» (pulsos tenues) con las entradas elegidas encendidas.
- Tras analizar: reproduce la traza real (orden y paralelismo de `TraceStep`, `started_s` si
  existe) con pulsos por las aristas activas y las salidas producidas resaltadas en latón.

Render: Three.js (cdnjs) en `st.components.v1.html`; si WebGL o el CDN fallan, Canvas 2D con la
misma proyección. `prefers-reduced-motion` → fotograma final estático. Los datos van como JSON con
`</` escapado; el JS solo escribe texto con `textContent`/canvas (nunca HTML con datos).
"""
from __future__ import annotations

import dataclasses
import json
from collections.abc import Collection, Sequence
from pathlib import Path
from typing import Any

from finlens.orchestration.trace import TraceStep, total_cost
from finlens.ui import pipeline_map as pm
from finlens.ui.gantt import timeline

THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
FONTS_URL = "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap"
PLAYBACK_S = 7.0  # la ejecución real se reescala a esta duración de reproducción
HEIGHT = 470
_JS = (Path(__file__).parent / "static" / "brain.js").read_text(encoding="utf-8")

INPUTS = (
    ("in_pdf", "pdf", "Informe PDF"), ("in_chart", "chart", "Gráfico"), ("in_audio", "audio", "Audio"),
    ("in_question", "question", "Pregunta"), ("in_ticker", "ticker", "Mercado"), ("in_sec", "sec", "SEC EDGAR"),
)
OUTPUTS = (
    ("out_report", "Informe citado"), ("out_figures", "Cifras verificadas"),
    ("out_contrast", "Contraste visión↔datos"), ("out_audio", "Resumen hablado"),
    ("out_infographic", "Infografía"), ("out_chat", "Chat con citas"),
)
_HIDDEN = (
    ("Percepción", ("ingest", "market", "chartgen", "vision", "stt", "sec")),
    ("Razonamiento", ("retrieve", "technicals", "analysis")),
    ("Control", ("verify", "contrast", "guard")),
    ("Generación", ("tts", "prompt", "image", "compose")),
)
_EDGES = (
    ("in_pdf", "ingest"), ("in_chart", "vision"), ("in_audio", "stt"), ("in_question", "retrieve"),
    ("in_question", "analysis"), ("in_ticker", "market"), ("in_sec", "sec"),
    ("ingest", "retrieve"), ("market", "chartgen"), ("market", "technicals"), ("chartgen", "vision"),
    ("vision", "analysis"), ("vision", "contrast"), ("technicals", "contrast"), ("technicals", "analysis"),
    ("stt", "analysis"), ("sec", "analysis"), ("sec", "verify"), ("retrieve", "analysis"),
    ("analysis", "verify"), ("analysis", "guard"), ("guard", "tts"), ("guard", "prompt"),
    ("prompt", "image"), ("image", "compose"), ("verify", "compose"),
    ("guard", "out_report"), ("verify", "out_figures"), ("contrast", "out_contrast"), ("tts", "out_audio"),
    ("compose", "out_infographic"), ("image", "out_infographic"), ("analysis", "out_chat"),
)
_MARKET_ONLY = pm.MARKET_NODES | {"in_ticker", "in_sec", "out_contrast"}


def _schedule(steps: Sequence[TraceStep]) -> dict[str, tuple[float, float]]:
    """Paso → (inicio, fin) en segundos de reproducción. Duraciones mínimas para que se vean."""
    if not steps:
        return {}
    total = sum(s.seconds for s in steps) or 1.0
    minimo = max(total * 0.05, 1e-3)
    inicios = [getattr(s, "started_s", None) for s in steps]
    if all(isinstance(x, int | float) for x in inicios):
        barras = [(s.step, float(x), float(x) + max(s.seconds, minimo)) for s, x in zip(steps, inicios, strict=True)]
    else:
        ajustados = [dataclasses.replace(s, seconds=max(s.seconds, minimo)) for s in steps]
        barras = [(b.step, b.start, b.end) for b in timeline(ajustados)]
    fin = max(b[2] for b in barras) or 1.0
    escala = (PLAYBACK_S - 1.6) / fin
    return {nombre: (0.6 + a * escala, 0.6 + b * escala) for nombre, a, b in barras}


def build_brain(
    providers: Any,
    *,
    aportes: Collection[str],
    result: Any = None,
    media: Any = None,
    with_market: bool = False,
    with_compose: bool = True,
) -> dict[str, Any]:
    """Datos de la escena (JSON-serializables). Sin `result` (o sin medios aún) → modo reposo."""
    info = pm.provider_info(providers)
    mocks = set(pm.mock_capabilities(providers))
    replay = result is not None and media is not None
    pasos: list[TraceStep] = [*(result.trace if replay else ()), *(media.trace if replay else ())]
    horario = _schedule(pasos)
    casados = pm.match_steps(pasos)

    def incluido(clave: str) -> bool:
        return with_market or clave not in _MARKET_ONLY


    capas: list[dict[str, Any]] = []
    nodos: dict[str, dict[str, Any]] = {}

    def nodo(id_: str, label: str, kind: str, **extra: Any) -> dict[str, Any]:
        n = {"id": id_, "label": label, "kind": kind, "sub": "", "value": "", "state": "idle", "t0": 0.0, "t1": 0.0}
        n.update(extra)
        nodos[id_] = n
        return n

    entradas = []
    for id_, clave, label in INPUTS:
        if not incluido(id_):
            continue
        activo = clave in aportes
        entradas.append(nodo(id_, label, "input", value="1.000" if activo else "0.000",
                             sub="aportado" if activo else "no aportado",
                             state="on" if activo else "off", t0=0.1, t1=0.6))
    capas.append({"title": "Capa 0 · Entrada", "nodes": entradas})

    for i, (titulo, claves) in enumerate(_HIDDEN, start=1):
        lista = []
        for clave in claves:
            if not incluido(clave) or (clave == "compose" and not with_compose):
                continue
            spec = pm.NODES[clave]
            cap = spec.capability or (spec.alt_capability if spec.alt_capability in info else None)
            backend, modelo = info.get(cap or "", ("local", spec.local_model))
            paso = casados.get(clave)
            extra: dict[str, Any] = {"sub": modelo if backend == "local" else f"{backend} · {modelo}",
                                     "mock": cap in mocks}
            if paso is not None:
                if paso.model and paso.model != "—":
                    extra["sub"] = paso.model if backend == "local" else f"{backend} · {paso.model}"
                t0, t1 = horario.get(paso.step, (0.0, 0.0))
                estado = "fail" if not paso.ok else ("sim" if cap in mocks else "ok")
                extra.update(state=estado, t0=round(t0, 3), t1=round(t1, 3), value=f"{paso.seconds:.2f} s")
            elif replay:
                extra.update(state="off", value="—")
            lista.append(nodo(clave, spec.title, "local" if cap is None else "model", **extra))
        capas.append({"title": f"Capa {i} · {titulo}", "nodes": lista})

    salidas = []
    for id_, label in OUTPUTS:
        if not incluido(id_):
            continue
        salidas.append(nodo(id_, label, "output", value="—"))
    capas.append({"title": f"Capa {len(capas)} · Salida", "nodes": salidas})

    aristas = [[a, b] for a, b in _EDGES if a in nodos and b in nodos]
    if replay:
        _fill_outputs(nodos, aristas, result, media)
    for capa in capas:
        capa["subtitle"] = f"Neuronas: {len(capa['nodes'])}"

    reales = sum(1 for c in info if c not in mocks)
    if replay:
        segundos = result.total_seconds + media.total_seconds
        headline = f"Ejecución reproducida · {len(pasos)} pasos · {segundos:.2f} s · {total_cost(pasos):.4f} USD"
    else:
        headline = f"Red en reposo · {reales} modelos reales · {len(info) - reales} simulados"
    return {"mode": "replay" if replay else "idle", "duration": PLAYBACK_S, "headline": headline,
            "layers": capas, "edges": aristas}


def _fill_outputs(nodos: dict[str, dict[str, Any]], aristas: list[list[str]], result: Any, media: Any) -> None:
    """Salidas producidas: estado, instante (al acabar su fuente) y métrica."""
    informe = result.report
    citas = sum(len(f.citations) for f in [*informe.key_figures, *informe.management_statements, *informe.correlations])
    checks = getattr(result, "figure_checks", ()) or ()
    verificadas = sum(1 for c in checks if getattr(c, "status", "") == "verificada")
    mercado = getattr(result, "market", None)
    contraste = getattr(mercado, "chart_check", None) if mercado is not None else None
    producido = {
        "out_report": (True, f"{citas} citas"),
        "out_figures": (bool(checks), f"{verificadas}/{len(checks)} ✓" if checks else "—"),
        "out_contrast": (contraste is not None,
                         f"{getattr(contraste, 'agreement_score', 0):.0%} acuerdo" if contraste is not None else "—"),
        "out_audio": (media.audio is not None, f"{media.audio.chars} car." if media.audio else "—"),
        "out_infographic": (media.image is not None, "PNG" if media.image else "—"),
        "out_chat": (True, "listo"),
    }
    for id_, (ok, valor) in producido.items():
        if id_ not in nodos:
            continue
        fuentes = [nodos[a] for a, b in aristas if b == id_ and nodos[a]["state"] not in ("off", "idle")]
        t0 = max((f["t1"] for f in fuentes), default=PLAYBACK_S - 1.0) + 0.15
        nodos[id_].update(state="on" if ok else "off", value=valor, t0=round(t0, 3), t1=round(t0 + 0.5, 3),
                          winner=id_ == "out_report")


def brain_html(data: dict[str, Any]) -> str:
    """Documento HTML autocontenido del iframe."""
    datos = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="stylesheet" href="{FONTS_URL}">
<style>
html,body{{margin:0;height:100%;background:#0c1416;overflow:hidden;font-family:'IBM Plex Mono',Consolas,monospace}}
#brain{{position:absolute;inset:0;background:radial-gradient(120% 90% at 55% 40%,#11292e 0%,#0c1719 55%,#12110e 100%)}}
#brain canvas{{display:block;width:100%;height:100%}}
.hud{{position:absolute;left:16px;right:16px;display:flex;justify-content:space-between;gap:12px;pointer-events:none;
  font-size:10.5px;letter-spacing:.14em;text-transform:uppercase;color:#bdb4a2}}
.top{{top:12px}} .bot{{bottom:12px;align-items:flex-end}}
.hud b{{color:#c8a24a;font-weight:600}} #hud-h{{color:#ede6d6}}
#replay{{pointer-events:auto;font:600 10.5px/1 'IBM Plex Mono',monospace;letter-spacing:.16em;text-transform:uppercase;
  color:#12110e;background:#c8a24a;border:0;padding:8px 12px;cursor:pointer}}
#replay:hover{{background:#d8b45c}} #replay:focus-visible{{outline:2px solid #ede6d6;outline-offset:2px}}
#replay[hidden]{{display:none}}
.leg span{{margin-right:14px;white-space:nowrap}} .leg i{{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;vertical-align:1px}}
#bar{{position:absolute;left:0;bottom:0;height:2px;background:#c8a24a;width:0}}
@media (max-width:560px){{.leg{{display:none}} .hud{{font-size:9.5px}}}}
</style></head><body>
<div id="brain" role="img" aria-label="Red de modelos de FinLens: entradas, modelos y salidas de esta sesión"></div>
<div class="hud top"><div><b>§0 Cerebro</b> · <span id="hud-h"></span></div><div id="hud-t"></div></div>
<div class="hud bot"><div class="leg"><span><i style="background:#ede6d6"></i>entrada / modelo</span>
<span><i style="background:#c8a24a"></i>en curso · salida</span><span><i style="background:#58aeb9"></i>simulado</span>
<span><i style="background:#e8716a"></i>fallo</span></div><button id="replay" type="button" hidden>Reproducir ▸</button></div>
<div id="bar"></div>
<script type="application/json" id="fl-data">{datos}</script>
<script>window.FL_THREE_URL = {json.dumps(THREE_URL)};</script>
<script>{_JS}</script>
</body></html>"""


def render(data: dict[str, Any]) -> None:
    """Pinta el cerebro (iframe). Mismos datos → Streamlit no recrea el iframe."""
    import streamlit.components.v1 as components

    components.html(brain_html(data), height=HEIGHT)
