# Materiales de prueba

Cada carpeta es un **caso** que el script de medición (`python scripts/medir.py`) y los tests reconocen
si contiene un `informe.pdf`. Archivos admitidos por caso:

| Archivo | Obligatorio | Descripción |
|---|---|---|
| `informe.pdf` | sí | Informe anual con texto seleccionable (no un escaneo) |
| `grafico.png` / `.jpg` | no | Gráfico de velas de la cotización |
| `audio.wav` / `.mp3` / `.m4a` / `.ogg` / `.webm` | no | Extracto de la conferencia de resultados (máx. 25 MB) |
| `pregunta_voz.*` | no | Pregunta por voz (en lugar de `audio.*`) |
| `pregunta.txt` | no | Pregunta por escrito |

## Qué hay ahora

- `00_demo_ficticio/`: informe, gráfico y audio **ficticios** generados en código. Sirve para probar el
  flujo y las pruebas automáticas. **El audio es silencio**: con la API real de transcripción dará
  «No se detectó voz». No se debe usar para medir costes reales.
- `04_entradas_invalidas/`: PDF sin texto, un fichero que no es un PDF y un audio vacío, para demostrar
  la robustez (caso 3 de la spec). `python scripts/medir.py --demo --robustez` los recorre.

- `01_inditex/`: caso real. Informe anual 2025 de Inditex (22 paginas, 1,5 MB), grafico de velas de ITX.MC
  (ago 2025 - ene 2026), `audio.mp3` de 83 s (**sintetico**) y `pregunta.txt`. Detalle en `01_inditex/FUENTE.md`.
- `02_inditex_voz/`: mismo informe y grafico + `pregunta_voz.mp3` de 9 s (**sintetica**), sin audio de conferencia.
  Detalle en `02_inditex_voz/FUENTE.md`.

## Origen, licencia y qué es sintético (casos 01 y 02)

| Material | Origen | Fecha de descarga | Condiciones | Real / sintético |
|---|---|---|---|---|
| `informe.pdf` | Inditex Group Annual Report 2025, <https://www.inditex.com/itxcomweb/api/media/59f58f71-301d-4a50-85a6-0441fb9f37c5/ENGL-CCAAeIGGrupo2025.pdf?t=1773650984481> (enlazado desde <https://annualreport.inditex.com/anrpxxvui/en/download-centre>); paginas 1, 3, 14-24, 74-82 | 2026-10-06 | Documento publico corporativo; uso academico, sin licencia explicita verificada | Real (recorte; imagenes reescaladas) |
| `grafico.png` | Precios diarios ITX.MC de la API publica de graficos de Yahoo Finance (`query1.finance.yahoo.com/v8/finance/chart/ITX.MC`), dibujado con matplotlib | 2026-10-06 | Terminos de uso de Yahoo/Bolsa de Madrid; solo uso academico. stooq.com no se pudo usar (verificacion anti-bot) | Datos reales, imagen generada por nosotros |
| `audio.mp3` (caso 01) | Voz generada con OpenRouter `hexgrad/kokoro-82m` (`em_alex`), leyendo `audio_texto.txt`, resumen propio de cifras y perspectivas del informe de gestion | 2026-10-06 | Texto derivado del informe; voz sin persona real | **Sintético**. No es una earnings call: esas grabaciones tienen copyright y no se han descargado |
| `pregunta_voz.mp3` (caso 02) | Misma voz sintetica leyendo `pregunta_voz_texto.txt` | 2026-10-06 | Sin persona real | **Sintético**. El equipo puede sustituirla por una grabacion propia (mismo nombre) |

Coste de generar los dos audios: unos centimos de USD en OpenRouter. El informe no incluye carta del presidente,
asi que las «declaraciones de la direccion» salen del informe de gestion.

## Regenerar

`python scripts/preparar_casos.py` (idempotente; `--forzar` rehace, `--pasos pdf grafico audio` elige pasos,
`--ayuda` con `-h`). Descarga el PDF a `samples/.cache/` (ignorado por git), recorta paginas con pypdf, baja los
precios, dibuja el grafico y, si hay `OPENROUTER_API_KEY`, genera los audios. Cada caso pesa ~2 MB, por eso se versionan.

## Casos futuros

Para añadir otra empresa: crea `samples/NN_<empresa>/` con `informe.pdf` y los demas ficheros de la tabla de arriba.
Usa **material público y respeta las licencias**; no incluyas datos personales.
