"""Mide latencia y coste por análisis sobre los casos de `samples/` y genera el informe de viabilidad.

Uso:
    python scripts/medir.py                          # casos de samples/, APIs reales si hay claves
    python scripts/medir.py --demo                   # prueba en seco con proveedores simulados
    python scripts/medir.py -n 3 --salida docs/medidas.md
    python scripts/medir.py --robustez               # entradas inválidas (caso 3 de la demo)

Cada caso es una carpeta con `informe.pdf` y, opcionalmente, `grafico.(png|jpg)`,
`audio.(wav|mp3|...)` (conferencia) o `pregunta_voz.*` (pregunta por voz) y `pregunta.txt`.
Con APIs reales el script GASTA crédito: pruébalo antes con --demo y con un solo caso.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from finlens.config import get_settings  # noqa: E402
from finlens.domain.cost import Tariffs  # noqa: E402
from finlens.logging_config import configure_logging  # noqa: E402
from finlens.orchestration.metrics import RunRecord, summarize, to_markdown  # noqa: E402
from finlens.orchestration.pipeline import (  # noqa: E402
    AnalysisInput,
    MediaResult,
    PipelineError,
    analyze,
    generate_media,
)
from finlens.providers.base import Providers  # noqa: E402
from finlens.providers.registry import build_mock_providers, build_providers  # noqa: E402

AUDIO_EXT = (".wav", ".mp3", ".m4a", ".ogg", ".webm")
IMAGEN_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _primero(carpeta: Path, nombre: str, extensiones) -> Path | None:
    return next((carpeta / f"{nombre}{e}" for e in extensiones if (carpeta / f"{nombre}{e}").exists()), None)


def cargar_caso(carpeta: Path) -> AnalysisInput | None:
    """Construye la entrada de un caso, o None si la carpeta no tiene `informe.pdf`."""
    pdf = carpeta / "informe.pdf"
    if not pdf.exists():
        return None
    grafico = _primero(carpeta, "grafico", IMAGEN_EXT)
    voz_pregunta = _primero(carpeta, "pregunta_voz", AUDIO_EXT)
    audio = voz_pregunta or _primero(carpeta, "audio", AUDIO_EXT)
    pregunta = carpeta / "pregunta.txt"
    return AnalysisInput(
        pdf=pdf.read_bytes(),
        question=pregunta.read_text(encoding="utf-8").strip() if pregunta.exists() else "",
        chart=grafico.read_bytes() if grafico else None,
        chart_mime=IMAGEN_EXT[grafico.suffix] if grafico else "image/png",
        audio=audio.read_bytes() if audio else None,
        audio_name=audio.name if audio else "audio",
        audio_role="pregunta" if voz_pregunta else "conferencia",
    )


def medir(providers: Providers, tariffs: Tariffs, casos: dict[str, AnalysisInput], n: int,
          con_medios: bool, max_chars: int) -> list[RunRecord]:
    registros = []
    for nombre, entrada in casos.items():
        for i in range(n):
            try:
                analisis = analyze(providers, tariffs, entrada, max_pdf_chars=max_chars)
                medios = generate_media(providers, tariffs, analisis) if con_medios else None
            except PipelineError as exc:
                print(f"  ✗ {nombre} #{i + 1}: {exc.message}")
                continue
            medios = medios or MediaResult(None, None, None, (), (), 0.0)
            registro = RunRecord.from_results(nombre, analisis, medios)
            registros.append(registro)
            print(f"  ✓ {nombre} #{i + 1}: informe {registro.report_seconds:.2f} s · "
                  f"total {registro.total_seconds:.2f} s · {sum(p.cost_usd for p in registro.steps):.4f} USD")
    return registros


def probar_robustez(providers: Providers, tariffs: Tariffs, carpeta: Path) -> None:
    """Pasa las entradas inválidas por el pipeline y muestra cómo responde (sin excepciones)."""
    pdf_valido = cargar_caso(carpeta.parent / "00_demo_ficticio")
    if pdf_valido is None:
        print("Falta samples/00_demo_ficticio para la prueba de robustez.")
        return
    casos = {
        "PDF sin texto": AnalysisInput(pdf=(carpeta / "sin_texto.pdf").read_bytes()),
        "Fichero que no es PDF": AnalysisInput(pdf=(carpeta / "no_es_un_pdf.pdf").read_bytes()),
        "Audio vacío (con PDF válido)": AnalysisInput(pdf=pdf_valido.pdf, audio=(carpeta / "audio_vacio.wav").read_bytes()),
        "Imagen corrupta (con PDF válido)": AnalysisInput(pdf=pdf_valido.pdf, chart=(carpeta / "imagen_corrupta.png").read_bytes()),
    }
    for nombre, entrada in casos.items():
        try:
            resultado = analyze(providers, tariffs, entrada)
            print(f"- {nombre}: informe entregado con avisos -> {list(resultado.warnings)}")
        except PipelineError as exc:
            print(f"- {nombre}: error controlado -> {exc.message}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # Windows: la consola cp1252 no admite ✓/✗
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--casos", type=Path, default=Path("samples"), help="carpeta con los casos")
    ap.add_argument("-n", "--repeticiones", type=int, default=1, help="repeticiones por caso")
    ap.add_argument("--demo", action="store_true", help="proveedores simulados (cifras no válidas)")
    ap.add_argument("--sin-medios", action="store_true", help="omite TTS e infografía")
    ap.add_argument("--salida", type=Path, help="escribe el informe Markdown en este fichero")
    ap.add_argument("--robustez", action="store_true", help="prueba las entradas inválidas y sale")
    args = ap.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level)
    providers = build_mock_providers() if args.demo else build_providers(settings)
    demo = providers.is_demo
    if demo and not args.demo:
        print(f"Modo demo automático: {settings.demo_reason or 'todas las capacidades están simuladas.'}")
    elif providers.mock_capabilities:
        print(
            "AVISO: capacidades SIMULADAS (sus cifras de coste y latencia no son reales): "
            + ", ".join(providers.mock_capabilities)
        )
    for aviso in providers.warnings:
        print(f"Aviso: {aviso}")
    if not demo:
        resumen = ", ".join(f"{i.capability}={i.backend}:{i.model}" for i in providers.info)
        print(f"Proveedores: {resumen}")
    tariffs = Tariffs.from_settings(settings)

    if args.robustez:
        probar_robustez(providers, tariffs, args.casos / "04_entradas_invalidas")
        return 0

    casos = {c.name: e for c in sorted(args.casos.iterdir()) if c.is_dir() and (e := cargar_caso(c))}
    if not casos:
        print(f"No hay casos en {args.casos}/ (cada uno necesita un informe.pdf). Ver samples/README.md.")
        return 1
    if not demo:
        print(f"APIs REALES: {len(casos)} caso(s) x {args.repeticiones} repetición(es). Esto consume crédito.")
    registros = medir(providers, tariffs, casos, args.repeticiones, not args.sin_medios, settings.max_pdf_chars)
    if not registros:
        print("Ninguna ejecución terminó correctamente.")
        return 1

    etiquetas = {"image": "imagen"}
    modelos = {etiquetas.get(i.capability, i.capability): f"{i.model} ({i.backend})" for i in providers.info}
    informe = to_markdown(summarize(registros), demo=demo, models=modelos, tariffs=tariffs,
                          date=date.today().isoformat())
    print("\n" + informe)
    if args.salida:
        args.salida.write_text(informe, encoding="utf-8")
        print(f"Informe guardado en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
