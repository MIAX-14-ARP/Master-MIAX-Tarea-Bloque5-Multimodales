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

## Qué falta: los casos reales (los pones tú)

La spec pide, para la demo y para medir costes y latencias reales:

1. `01_<empresa>/`: informe anual real de una cotizada + gráfico de su cotización + extracto de su
   earnings call (audio).
2. `02_<empresa>_voz/`: el mismo informe con `pregunta_voz.*` (por ejemplo, «¿Cómo evolucionó el margen
   operativo y qué dijo la dirección sobre la guía?»).

Usa **material público y respeta las licencias**; no incluyas datos personales. Si los ficheros pesan
mucho, no los subas al repositorio: añade su carpeta a `.gitignore` y enlázalos desde el README.
