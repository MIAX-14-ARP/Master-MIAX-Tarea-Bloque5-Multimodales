"""Fragmentos HTML de la UI (funciones puras: texto → HTML). Sin Streamlit ni lógica de negocio.

Todo texto que venga de modelos o usuarios pasa por `esc` (riesgo XSS: el contenido lo escribe
un LLM). El HTML se devuelve en UNA línea: el parser de Markdown de Streamlit trataría una línea en
blanco o una sangría de 4 espacios como fin del bloque HTML o como código.
"""
from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from finlens.domain.schemas import Citation, Finding, KeyFigure

CAP_ORDER = (("llm", "LLM"), ("vision", "Visión"), ("stt", "STT"), ("tts", "TTS"), ("image", "Imagen"),
             ("embeddings", "Embed."))
_ORIGEN_CORTO = {"documento": "DOC", "grafico": "GRÁF", "audio": "AUDIO", "mercado": "MERC", "sec": "SEC"}
_ORIGEN_BASE = ("documento", "grafico", "audio")


def esc(texto: object) -> str:
    """Escapa HTML y convierte saltos de línea en <br> (nunca deja líneas en blanco)."""
    return html.escape(str(texto), quote=True).replace("\r", "").replace("\n", "<br>")


def section(numero: str, titulo: str, aside: str = "") -> str:
    lado = f'<span class="fl-sec__aside">{esc(aside)}</span>' if aside else ""
    return (
        f'<div class="fl-sec"><span class="fl-sec__n">§{esc(numero)}</span>'
        f'<div class="fl-sec__t" role="heading" aria-level="2">{esc(titulo)}</div>{lado}</div>'
    )


def subhead(numero: str, titulo: str) -> str:
    return f'<div class="fl-sub" role="heading" aria-level="3"><b>{esc(numero)}</b><span>{esc(titulo)}</span></div>'


# --- Mancheta y proveedores -----------------------------------------------------------------


def mode_summary(info: Mapping[str, tuple[str, str]], mocks: Sequence[str]) -> tuple[str, str, str]:
    """(clase, etiqueta, frase) del modo de ejecución, con honestidad sobre lo simulado."""
    presentes = [(cap, nombre) for cap, nombre in CAP_ORDER if cap in info] or list(CAP_ORDER[:5])
    nombres = [nombre for cap, nombre in presentes if cap in mocks]
    if len(nombres) == len(presentes):
        return ("is-demo", "Modo demo",
                "Modo demo: todas las respuestas son simuladas, sin coste ni llamadas externas.")
    if nombres:
        lista = ", ".join(nombres)
        return ("is-partial", "Demo parcial",
                f"Demo parcial: {lista} {'van' if len(nombres) > 1 else 'va'} con modelo simulado; "
                "el resto usa modelos reales.")
    return ("is-real", "Modelos reales", "Todas las capacidades usan modelos reales (con coste por llamada).")


def provider_bar(info: Mapping[str, tuple[str, str]], mocks: Sequence[str]) -> str:
    celdas = []
    for cap, nombre in CAP_ORDER:
        if cap not in info and cap == "embeddings":
            continue
        backend, modelo = info.get(cap, ("?", "?"))
        simulado = cap in mocks
        clase = "fl-prov__cell is-mock" if simulado else "fl-prov__cell"
        estado = "SIM" if simulado else "REAL"
        celdas.append(
            f'<div class="{clase}"><div class="fl-prov__cap"><span>{esc(nombre.upper())}</span>'
            f'<span><span class="fl-dot"></span> {estado}</span></div>'
            f'<div class="fl-prov__be">{esc(backend)}</div>'
            f'<div class="fl-prov__model" title="{esc(modelo)}">{esc(modelo)}</div></div>'
        )
    return f'<div class="fl-prov" role="group" aria-label="Proveedores por capacidad">{"".join(celdas)}</div>'


def masthead(fecha: str, info: Mapping[str, tuple[str, str]], mocks: Sequence[str], aviso: str | None) -> str:
    clase, etiqueta, frase = mode_summary(info, mocks)
    extra = f" {esc(aviso)}" if aviso else ""
    return (
        '<header class="fl-mast" lang="es">'
        '<div class="fl-mast__top"><span>Terminal de research multimodal · MIAX</span>'
        f"<span>{esc(fecha)}</span></div>"
        '<div class="fl-mast__row"><div><div class="fl-brand" role="heading" aria-level="1">Fin<em>Lens</em></div>'
        '<p class="fl-tagline">Informe anual, gráfico de velas y earnings call, '
        "leídos a la vez y convertidos en una nota citada.</p></div>"
        f"{provider_bar(info, mocks)}</div>"
        f'<div class="fl-mode"><span class="fl-mode__tag {clase}">{etiqueta}</span>'
        f"<span>{esc(frase)}{extra} Tus documentos se procesan en esta sesión y no se guardan.</span></div>"
        "</header>"
    )


# --- Ranuras de entrada ---------------------------------------------------------------------


def _tamano(n: int) -> str:
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{max(1, round(n / 1024))} KB"


def slot(letra: str, titulo: str, detalle: str, *, nombre: str | None = None, tamano: int | None = None,
         ejemplo: bool = False, vacio: str = "vacío") -> str:
    if ejemplo:
        clase, estado = "fl-slot is-sample", f"ejemplo · {nombre}"
    elif nombre:
        peso = f" · {_tamano(tamano)}" if tamano else ""
        clase, estado = "fl-slot is-ready", f"listo · {nombre}{peso}"
    else:
        clase, estado = "fl-slot", vacio
    return (
        f'<div class="{clase}"><div class="fl-slot__head"><span class="fl-slot__l" aria-hidden="true">{esc(letra)}</span>'
        f'<div><div class="fl-slot__t">{esc(titulo)}</div><div class="fl-slot__d">{esc(detalle)}</div>'
        f'<div class="fl-slot__st">{esc(estado)}</div></div></div></div>'
    )


# --- Nota de research -----------------------------------------------------------------------


def chip(c: Citation) -> str:
    corto = _ORIGEN_CORTO.get(c.origin, c.origin.upper())
    texto = f"{corto} {c.location}".strip()
    return f'<span class="fl-chip o-{esc(c.origin)}" title="{esc(c.label)}" aria-label="Fuente: {esc(c.label)}">{esc(texto)}</span>'


def chips(citations: Iterable[Citation]) -> str:
    return "".join(chip(c) for c in citations)


def stamp(check: Any | None) -> str:
    """Sello de verificación determinista de una cifra (contrato `FigureCheck`)."""
    if check is None:
        return '<span class="fl-stamp u">sin verificar</span>'
    pagina = f" p.{check.page}" if getattr(check, "page", None) else ""
    status = getattr(check, "status", "")
    if status == "verificada":
        return f'<span class="fl-stamp v">✓ verificada{esc(pagina)}</span>'
    if status == "no_encontrada":
        donde = f" en{pagina}" if pagina else ""
        return f'<span class="fl-stamp x">✕ no encontrada{esc(donde)}</span>'
    if status == "sin_fuente_documental":
        return '<span class="fl-stamp s">sin fuente documental</span>'
    return f'<span class="fl-stamp u">{esc(status or "sin verificar")}</span>'


def pair_checks(figures: Sequence[KeyFigure], checks: Sequence[Any]) -> list[Any | None]:
    """Empareja cada cifra con su comprobación (por nombre y valor; si no, por posición)."""
    pendientes = list(checks)
    salida: list[Any | None] = []
    for i, f in enumerate(figures):
        encontrado = next(
            (c for c in pendientes if getattr(c, "figure_name", None) == f.name
             and getattr(c, "value", None) == f.value), None,
        )
        if encontrado is None and len(checks) == len(figures):
            encontrado = checks[i]
        if encontrado is not None and encontrado in pendientes:
            pendientes.remove(encontrado)
        salida.append(encontrado)
    return salida


def figures_html(figures: Sequence[KeyFigure], checks: Sequence[Any]) -> str:
    celdas = []
    for f, check in zip(figures, pair_checks(figures, checks), strict=True):
        periodo = f'<div class="fl-fig__p">{esc(f.period)}</div>' if f.period else ""
        celdas.append(
            f'<div class="fl-fig"><div class="fl-fig__n">{esc(f.name)}</div>'
            f'<div class="fl-fig__v">{esc(f.value)}</div>{periodo}'
            f'<div class="fl-fig__foot">{stamp(check)}{chips(f.citations)}</div></div>'
        )
    return f'<div class="fl-figs">{"".join(celdas)}</div>'


def findings_html(findings: Sequence[Finding]) -> str:
    filas = [
        f'<li class="fl-find"><span class="fl-find__i">{i:02d}</span><div>'
        f'<div class="fl-find__s">{esc(h.statement)}</div><div class="fl-find__c">{chips(h.citations)}</div></div></li>'
        for i, h in enumerate(findings, start=1)
    ]
    return f'<ol class="fl-finds">{"".join(filas)}</ol>'


_TENSION = re.compile(r"contradic|discrep|diverg|no coincide|en cambio|sin embargo|choca|contrast", re.I)


def correlations_html(findings: Sequence[Finding]) -> str:
    """Correlaciones con matriz de modalidades; las que expresan tensión se marcan en rojo."""
    filas = []
    for h in findings:
        origenes = {c.origin for c in h.citations}
        columnas = [o for o in _ORIGEN_CORTO if o in _ORIGEN_BASE or o in origenes]
        celdas = "".join(
            f'<span class="{"on" if o in origenes else ""}">{_ORIGEN_CORTO[o]}</span>' for o in columnas
        )
        tension = bool(_TENSION.search(h.statement))
        etiqueta = "Tensión entre fuentes" if tension else f"Convergencia · {len(origenes)} modalidades"
        filas.append(
            f'<div class="fl-corr{" is-tension" if tension else ""}">'
            f'<div class="fl-matrix" aria-label="Modalidades citadas: {esc(", ".join(sorted(origenes)))}">{celdas}</div>'
            f'<div><div class="fl-corr__tag">{etiqueta}</div><div class="fl-corr__s">{esc(h.statement)}</div>'
            f'<div class="fl-find__c">{chips(h.citations)}</div></div></div>'
        )
    return "".join(filas)


def limitations_html(items: Sequence[str]) -> str:
    return f'<ul class="fl-limits">{"".join(f"<li>{esc(t)}</li>" for t in items)}</ul>'


def editor_note(texto: str, *, error: bool = False, titulo: str | None = None) -> str:
    clase = "fl-editor is-error" if error else "fl-editor"
    k = titulo or ("Error" if error else "Nota del editor")
    return f'<div class="{clase}" role="{"alert" if error else "note"}"><div class="fl-editor__k">{esc(k)}</div><div class="fl-editor__t">{esc(texto)}</div></div>'


def colophon(disclaimer: str) -> str:
    return (
        f'<div class="fl-colophon" role="note"><b>Aviso</b><span>{esc(disclaimer)} '
        "Contenido generado por IA (AI Act): contrasta siempre las fuentes citadas.</span></div>"
    )


def kpis(items: Sequence[tuple[str, str, str]]) -> str:
    celdas = "".join(
        f'<div class="fl-kpi"><div class="fl-kpi__k">{esc(k)}</div><div class="fl-kpi__v">{esc(v)}'
        f'{f"<small>{esc(u)}</small>" if u else ""}</div></div>'
        for k, v, u in items
    )
    return f'<div class="fl-kpis">{celdas}</div>'


def read_card(clave: str, grande: str, texto: str = "", *, tono: str = "", extra: str = "") -> str:
    big = f'<div class="fl-read__big {tono}">{esc(grande)}</div>' if grande else ""
    cuerpo = f'<div class="fl-read__t">{esc(texto)}</div>' if texto else ""
    return f'<div class="fl-read"><div class="fl-read__k">{esc(clave)}</div>{big}{cuerpo}{extra}</div>'


# --- Mercado (spec 06 §10): contraste visión ↔ datos -----------------------------------------

_VEREDICTO = {
    "confirmada": ("v", "✓ confirmada"),
    "discrepa": ("x", "✕ discrepa"),
    "no_verificable": ("s", "no verificable"),
}


def verdict_stamp(verdict: str) -> str:
    clase, texto = _VEREDICTO.get(verdict, ("u", verdict or "sin veredicto"))
    return f'<span class="fl-stamp {clase}">{esc(texto)}</span>'


def contrast_html(check: Any) -> str:
    """«La IA vio X; los datos dicen Y»: cada afirmación del modelo de visión con su veredicto."""
    items = tuple(getattr(check, "items", ()) or ())
    score = getattr(check, "agreement_score", None)
    confirmadas = sum(1 for i in items if getattr(i, "verdict", "") == "confirmada")
    discrepan = sum(1 for i in items if getattr(i, "verdict", "") == "discrepa")
    cifra = f"{score:.0%}" if isinstance(score, int | float) else "—"
    cabecera = (
        f'<div class="fl-contrast__head"><div class="fl-contrast__score">{esc(cifra)}</div>'
        f'<div class="fl-contrast__k">acuerdo visión ↔ datos<br>{confirmadas} confirmadas · {discrepan} discrepan · '
        f"{len(items) - confirmadas - discrepan} no verificables</div></div>"
    )
    filas = "".join(
        f'<li class="fl-contrast__row is-{esc(getattr(i, "verdict", ""))}"><div>{verdict_stamp(getattr(i, "verdict", ""))}</div>'
        f'<div><div class="fl-contrast__saw"><b>La IA vio</b>«{esc(getattr(i, "claim", ""))}»</div>'
        f'<div class="fl-contrast__data"><b>Los datos dicen</b>{esc(getattr(i, "detail", ""))}</div></div></li>'
        for i in items
    )
    return f'<div class="fl-contrast">{cabecera}<ol class="fl-contrast__list">{filas}</ol></div>'


def kv_grid(pares: Sequence[tuple[str, str]]) -> str:
    """Rejilla de indicadores (clave pequeña en mono, valor tabular)."""
    celdas = "".join(
        f'<div class="fl-kv"><div class="fl-kv__k">{esc(k)}</div><div class="fl-kv__v">{esc(v)}</div></div>' for k, v in pares
    )
    return f'<div class="fl-kvs">{celdas}</div>'
