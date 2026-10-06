"""Prepara los casos reales de `samples/` (Inditex): recorte del PDF, gráfico de velas y audios sintéticos.

Todos los pasos son idempotentes: si el resultado existe se omite (usa --forzar para regenerar).

    python scripts/preparar_casos.py                      # pdf + grafico (+ audios si hay OPENROUTER_API_KEY)
    python scripts/preparar_casos.py --pasos pdf grafico  # solo algunos pasos
    python scripts/preparar_casos.py --pasos audio --forzar

Fuentes (ver samples/README.md y samples/*/FUENTE.md):
  - PDF: Inditex Group Annual Report 2025 (ejercicio cerrado el 31/01/2026), web oficial de Inditex.
  - Precios: API pública de gráficos de Yahoo Finance (ITX.MC), datos diarios.
  - Audios: voz SINTÉTICA generada con OpenRouter (hexgrad/kokoro-82m).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAMPLES = RAIZ / "samples"
CACHE = SAMPLES / ".cache"

PDF_URL = ("https://www.inditex.com/itxcomweb/api/media/59f58f71-301d-4a50-85a6-0441fb9f37c5/"
           "ENGL-CCAAeIGGrupo2025.pdf?t=1773650984481")
# Páginas (1-based) del PDF completo: portada, índice, cuentas anuales consolidadas (cuenta de resultados,
# balance, flujos, patrimonio) e informe de gestión consolidado (resultados, caja, riesgos, perspectivas).
PAGINAS_DEFECTO = "1,3,14-24,74-82"
UA = {"User-Agent": "Mozilla/5.0 (FinLens academic sample builder)"}


def parsear_paginas(spec: str) -> list[int]:
    paginas: list[int] = []
    for trozo in spec.split(","):
        a, _, b = trozo.strip().partition("-")
        paginas.extend(range(int(a), int(b or a) + 1))
    return paginas


def descargar(url: str, destino: Path) -> Path:
    if destino.exists():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    print(f"  descargando {url[:90]}...")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        destino.write_bytes(r.read())
    return destino


def paso_pdf(args) -> None:
    from pypdf import PdfReader, PdfWriter
    destino = SAMPLES / args.caso_texto / "informe.pdf"
    if destino.exists() and not args.forzar:
        print(f"pdf: ya existe {destino.relative_to(RAIZ)}")
    else:
        completo = descargar(args.pdf_url, CACHE / "informe_completo.pdf")
        lector = PdfReader(str(completo))
        escritor = PdfWriter()
        paginas = parsear_paginas(args.paginas)
        for n in paginas:
            escritor.add_page(lector.pages[n - 1])
        # Las imágenes de fondo/portada pesan >2 MB: se reducen (el texto sigue siendo seleccionable).
        for pagina in escritor.pages:
            for im in pagina.images:
                pil = im.image
                if max(pil.size) > 800:
                    pil = pil.convert("RGB")
                    pil.thumbnail((800, 800))
                    im.replace(pil, quality=50)
        escritor.compress_identical_objects(remove_identicals=True, remove_orphans=True)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("wb") as f:
            escritor.write(f)
        print(f"pdf: {len(paginas)} paginas -> {destino.relative_to(RAIZ)} ({destino.stat().st_size / 1e6:.2f} MB)")
    copia = SAMPLES / args.caso_voz / "informe.pdf"
    if not copia.exists() or args.forzar:
        copia.parent.mkdir(parents=True, exist_ok=True)
        copia.write_bytes(destino.read_bytes())
    texto = "".join((p.extract_text() or "") for p in PdfReader(str(destino)).pages)
    print(f"pdf: verificacion pypdf -> {len(texto)} caracteres de texto extraidos")


def descargar_precios(ticker: str, desde: str, hasta: str) -> list[dict]:
    d = int(datetime.fromisoformat(desde).replace(tzinfo=UTC).timestamp())
    h = int(datetime.fromisoformat(hasta).replace(tzinfo=UTC).timestamp()) + 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={d}&period2={h}&interval=1d&events=history")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        datos = json.load(r)
    res = datos["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    filas = []
    for i, ts in enumerate(res["timestamp"]):
        if None in (q["open"][i], q["high"][i], q["low"][i], q["close"][i]):
            continue
        filas.append({"fecha": datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d"),
                      "open": round(q["open"][i], 4), "high": round(q["high"][i], 4),
                      "low": round(q["low"][i], 4), "close": round(q["close"][i], 4),
                      "volume": q["volume"][i] or 0})
    return filas


def paso_grafico(args) -> None:
    destino = SAMPLES / args.caso_texto / "grafico.png"
    csv_path = SAMPLES / args.caso_texto / "cotizacion_ITX.csv"
    if destino.exists() and not args.forzar:
        print(f"grafico: ya existe {destino.relative_to(RAIZ)}")
    else:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
        if csv_path.exists() and not args.forzar:
            filas = [dict(f) for f in csv.DictReader(csv_path.open(encoding="utf-8"))]
            for f in filas:
                for k in ("open", "high", "low", "close", "volume"):
                    f[k] = float(f[k])
        else:
            filas = descargar_precios(args.ticker, args.desde, args.hasta)
            with csv_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(filas[0]))
                w.writeheader()
                w.writerows(filas)
        fechas = [datetime.fromisoformat(f["fecha"]) for f in filas]
        x = mdates.date2num(fechas)
        fig, (ax, axv) = plt.subplots(2, 1, figsize=(14, 9), dpi=100, sharex=True,
                                      gridspec_kw={"height_ratios": [4, 1], "hspace": 0.05})
        sube, baja = "#2e7d32", "#c62828"
        for xi, f in zip(x, filas, strict=True):
            c = sube if f["close"] >= f["open"] else baja
            ax.vlines(xi, f["low"], f["high"], color=c, linewidth=1)
            ax.bar(xi, abs(f["close"] - f["open"]) or 0.02, bottom=min(f["open"], f["close"]),
                   width=0.6, color=c)
            axv.bar(xi, f["volume"] / 1e6, width=0.6, color=c, alpha=0.8)
        ax.set_title(f"{args.nombre} ({args.ticker}) - velas diarias, {filas[0]['fecha']} a {filas[-1]['fecha']}"
                     f" (EUR)", fontsize=15, loc="left")
        ax.set_ylabel("Precio (EUR)")
        axv.set_ylabel("Volumen (mill.)")
        for a in (ax, axv):
            a.grid(alpha=0.25)
            a.spines[["top", "right"]].set_visible(False)
        axv.xaxis.set_major_locator(mdates.MonthLocator())
        axv.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
        fig.text(0.01, 0.005, "Fuente: Yahoo Finance (API publica de graficos). Grafico generado con matplotlib.",
                 fontsize=9, color="#555")
        fig.subplots_adjust(left=0.07, right=0.98, top=0.94, bottom=0.07)
        fig.savefig(destino)
        plt.close(fig)
        print(f"grafico: {len(filas)} velas -> {destino.relative_to(RAIZ)} ({destino.stat().st_size / 1e3:.0f} KB)")
    copia = SAMPLES / args.caso_voz / "grafico.png"
    if not copia.exists() or args.forzar:
        copia.parent.mkdir(parents=True, exist_ok=True)
        copia.write_bytes(destino.read_bytes())


def clave_openrouter() -> str | None:
    sys.path.insert(0, str(RAIZ / "src"))
    try:
        from finlens.config import get_settings
        valor = getattr(get_settings(), "openrouter_api_key", None)
        if valor:
            return valor.get_secret_value() if hasattr(valor, "get_secret_value") else str(valor)
    except Exception:  # noqa: BLE001 - se prueba el respaldo con dotenv
        pass
    valor = os.environ.get("OPENROUTER_API_KEY")
    if valor:
        return valor
    from dotenv import dotenv_values
    return dotenv_values(RAIZ / ".env").get("OPENROUTER_API_KEY")


def sintetizar(texto: str, destino: Path, modelo: str, voces: list[str], clave: str) -> bool:
    from openai import OpenAI
    cliente = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=clave)
    for voz in voces:
        try:
            with cliente.audio.speech.with_streaming_response.create(
                    model=modelo, voice=voz, input=texto, response_format="mp3") as r:
                r.stream_to_file(destino)
            print(f"audio: {destino.relative_to(RAIZ)} (modelo={modelo}, voz={voz}, {destino.stat().st_size / 1e3:.0f} KB)")
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"audio: voz {voz} fallo ({type(exc).__name__}: {str(exc)[:150]})")
    return False


def paso_audio(args) -> None:
    trabajos = [(SAMPLES / args.caso_texto / "audio_texto.txt", SAMPLES / args.caso_texto / "audio.mp3"),
                (SAMPLES / args.caso_voz / "pregunta_voz_texto.txt", SAMPLES / args.caso_voz / "pregunta_voz.mp3")]
    pendientes = [(t, a) for t, a in trabajos if args.forzar or not a.exists()]
    if not pendientes:
        print("audio: ya existen")
        return
    clave = clave_openrouter()
    if not clave:
        print("audio: sin OPENROUTER_API_KEY; se omite (los casos funcionan sin audio)")
        return
    for texto_path, salida in pendientes:
        texto = texto_path.read_text(encoding="utf-8").strip()
        if not sintetizar(texto, salida, args.modelo_tts, args.voces, clave):
            print(f"audio: NO se pudo generar {salida.name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pasos", nargs="+", choices=["pdf", "grafico", "audio"], default=["pdf", "grafico", "audio"])
    p.add_argument("--forzar", action="store_true", help="regenerar aunque exista")
    p.add_argument("--caso-texto", default="01_inditex")
    p.add_argument("--caso-voz", default="02_inditex_voz")
    p.add_argument("--pdf-url", default=PDF_URL)
    p.add_argument("--paginas", default=PAGINAS_DEFECTO, help="paginas 1-based, p.ej. '1,3,14-24,74-82'")
    p.add_argument("--ticker", default="ITX.MC")
    p.add_argument("--nombre", default="Inditex")
    p.add_argument("--desde", default="2025-08-01")
    p.add_argument("--hasta", default="2026-01-31")
    p.add_argument("--modelo-tts", default="hexgrad/kokoro-82m")
    p.add_argument("--voces", nargs="+", default=["em_alex", "ef_dora"])
    args = p.parse_args()
    for paso in args.pasos:
        {"pdf": paso_pdf, "grafico": paso_grafico, "audio": paso_audio}[paso](args)


if __name__ == "__main__":
    main()
