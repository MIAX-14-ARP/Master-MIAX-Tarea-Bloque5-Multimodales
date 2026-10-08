# FinLens · Pitch técnico

**Research financiero multimodal con cifras verificadas.** Informe anual, gráfico, conferencia de resultados y
datos de mercado en una nota donde cada cifra cita su fuente y la verifica el código.

> Piettro Rodrigues · Alonso Díaz · Raúl Rodríguez — Taller B5-T4, Máster MIAX (Instituto BME) · 8 de octubre de 2026.
> Startup ficticia (práctica de máster). Cifras medidas con APIs reales el 7-oct-2026 (`docs/medidas.md`).

---

## 1. El problema

El analista cruza a mano **cuatro fuentes que nada conecta**: el informe anual en PDF (a menudo en inglés),
el gráfico de cotización, la conferencia de resultados en audio y los datos de mercado. Lo valioso —¿lo que
dice la dirección encaja con las cifras y con el mercado?— no queda ni trazado ni citado. Y los asistentes de
IA genéricos **inventan cifras**.

**Público:** analistas junior y *sell-side*, EAFI, gestoras boutique, relación con inversores (B2B);
brokers (B2B2C).

## 2. La solución

**FinLens convierte esos materiales en una nota de research citada y verificada en ~30 segundos.**
Escribe un ticker (`ITX.MC`, `AAPL`, `BTC`) o sube el informe, el gráfico y el audio: obtienes cifras con su
fuente y **sello de verificación**, la lectura del gráfico **contrastada con los datos reales**,
declaraciones de la dirección, correlaciones y contradicciones, resumen en audio, infografía y chat.

*Demo:* <https://108-128-114-211.sslip.io> (con contraseña).

## 3. Por qué multimodal (y no «un chat con un PDF»)

Seis modelos especializados encadenados, más verificación determinista en Python:

| Paso | Modelo |
|---|---|
| Recuperación multilingüe | `baai/bge-m3` + TF-IDF (fusión RRF) |
| Lectura del gráfico | `google/gemini-3.8-flash` |
| Transcripción | `openai/whisper-large-v3-turbo` (+ respaldo si trunca) |
| Análisis y chat | `anthropic/claude-sonnet-5.5` |
| Resumen en audio | `hexgrad/kokoro-82m` |
| Ilustración | `black-forest-labs/flux.2-klein-4b` (cifras dibujadas por Python) |
| Datos | Yahoo Finance · Hyperliquid (on-chain) · SEC EDGAR |

Diferencial: **«La IA vio · los datos dicen»** (contraste visión↔datos) y **cifras verificadas** contra la
página, la SEC o los indicadores.

## 4. Arquitectura

Capas separadas y proveedores **intercambiables por capacidad**: `providers/` (IA) · `sources/` (datos) ·
`domain/` (negocio) · `orchestration/` · `ui/`; un test hace cumplir las fronteras. Ramas en paralelo, render
progresivo, degradación elegante, modo demo sin claves. Más de 800 tests, CI en GitHub Actions y despliegue continuo
a AWS (ECR + EC2, OIDC, Secrets Manager).

## 5. Viabilidad y negocio

- **Coste medido:** **0,060 USD** por análisis completo (99 % coste real informado por el proveedor);
  ≈0,027 USD solo con ticker. **Latencia:** nota en pantalla en **21,9 s**, todo en **31,4 s**. 0 fallos en 6
  ejecuciones.
- **Compliance por diseño:** informa, no asesora (MiFID II / CNMV); guardrail que retira frases de
  recomendación en español e inglés; sin almacenar documentos (RGPD); contenido marcado como IA y citado
  (AI Act).
- **Monetización (hipótesis):** Free · **Pro 49 €/mes** (150 análisis, margen bruto ≈83 %) ·
  **Team 390 €/mes** (5 usuarios, 1.000 análisis, ≈86 %) · **API 0,25 €/análisis** (≈78 %).

## 6. Tracción potencial y hoja de ruta

**Tracción:** equipos de research de boutiques y EAFI que hoy hacen este cruce a mano; integración con
plataformas de brokers.

**Hoja de ruta:** vídeo-análisis de webinars · OCR · *streaming* · comparación entre empresas · alertas por
ticker · multiusuario · evaluación sistemática de precisión.
