# Caso 02 - Inditex (pregunta por voz)

Mismo informe y grafico que el caso 01 (ver `../01_inditex/FUENTE.md`; se copian con `scripts/preparar_casos.py`).

## Informe (real)
- Documento: *Inditex Group Annual Report 2025* (cuentas anuales consolidadas, informe de gestión y estado de información no financiera), ejercicio cerrado el 31/01/2026. En inglés.
- URL: https://www.inditex.com/itxcomweb/api/media/59f58f71-301d-4a50-85a6-0441fb9f37c5/ENGL-CCAAeIGGrupo2025.pdf?t=1773650984481 (enlazado desde https://annualreport.inditex.com/anrpxxvui/en/download-centre, web oficial de Inditex). Descargado el 2026-10-06 (200 paginas, 27 MB).
- Paginas extraidas (numeracion del PDF original): 1, 3, 14-24 y 74-82 (portada, indice, cuentas anuales consolidadas: cuenta de resultados, balance, flujos y patrimonio; informe de gestion consolidado: resultados, caja, riesgos y perspectivas). Total 22 paginas, 1,5 MB. Las imagenes de fondo se reducen de tamano; el texto sigue siendo seleccionable (verificado con pypdf: ~56.800 caracteres).
- Licencia: documento publico corporativo de Inditex; uso academico, sin licencia explicita verificada. No se redistribuye con fines comerciales.
- Nota: el PDF no contiene carta del presidente; las declaraciones de la direccion salen del informe de gestion («Business performance», «Information on the outlook for the Group»).

## Grafico (real)
- Velas diarias de ITX.MC (Bolsa de Madrid), del 2025-08-01 al 2026-01-30 (ultimos 6 meses del ejercicio). Datos en `cotizacion_ITX.csv` (128 sesiones).
- Fuente: API publica de graficos de Yahoo Finance, `https://query1.finance.yahoo.com/v8/finance/chart/ITX.MC?interval=1d`, consultada el 2026-10-06. Condiciones: datos de Yahoo/Bolsa de Madrid sujetos a sus terminos de uso; aqui solo uso academico, sin redistribucion comercial. (stooq.com se probo primero y exige verificacion anti-bot por JavaScript, asi que no se uso.)
- El PNG (1400x900) lo dibuja `scripts/preparar_casos.py` con matplotlib.

## Pregunta por voz (SINTETICA)
- `pregunta_voz.mp3` (9 s) es voz **sintetica** (OpenRouter `hexgrad/kokoro-82m`, voz `em_alex`) leyendo `pregunta_voz_texto.txt`: «¿Cómo evolucionaron las ventas y el margen bruto de Inditex en 2025, y qué dijo la dirección sobre las perspectivas para 2026?».
- No hay audio de conferencia en este caso. El equipo puede sustituirla por una grabacion propia (`pregunta_voz.mp3`/`.wav`).
