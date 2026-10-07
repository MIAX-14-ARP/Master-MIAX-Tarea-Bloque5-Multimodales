# Mediciones de FinLens (2026-10-07)

Ejecuciones medidas: **6**. Modelos: llm=`anthropic/claude-sonnet-5.5 (openrouter)`, vision=`google/gemini-3.8-flash (openrouter)`, stt=`openai/whisper-large-v3-turbo (openrouter)`, tts=`hexgrad/kokoro-82m (openrouter)`, imagen=`black-forest-labs/flux.2-klein-4b (openrouter)`, embeddings=`baai/bge-m3 (openrouter)`

Tarifas aplicadas (USD, orientativas; verificar en las páginas oficiales): LLM 2.0/10.0 por millón de tokens (entrada/salida), STT 0.006/min, TTS 0.62 por millón de caracteres, imagen 0.04/unidad.

## Coste medio por análisis (USD)

| Componente | Uso medio | Coste |
|---|---|---|
| LLM (tokens ent./sal.) | 8,849 / 3,092 | 0.0446 |
| STT | 0.7 min | 0.0001 |
| TTS | 710.3 caracteres | 0.0004 |
| Imagen | 1.0 imagen | 0.0150 |
| Embeddings | 21,395.0 tokens | 0.0002 |
| **Total** | | **0.0604** |

Origen del coste: **99% real** (informado por el proveedor, p.ej. `usage.cost` de OpenRouter) y el resto **estimado** con las tarifas indicadas.

## Latencia por paso (s)

| Paso | Modelo | Media | Máx. | Fallos |
|---|---|---|---|---|
| Ingesta e índice | pypdf + TF-IDF | 0.28 | 0.30 | 0 |
| Índice semántico (embeddings) | baai/bge-m3 | 4.21 | 9.21 | 0 |
| Lectura del gráfico | google/gemini-3.8-flash | 4.77 | 5.50 | 0 |
| Transcripción de audio | openai/whisper-large-v3-turbo | 3.66 | 6.98 | 0 |
| Recuperación | TF-IDF + bge-m3 | 1.06 | 3.69 | 0 |
| Análisis (LLM) | anthropic/claude-sonnet-5.5 | 13.86 | 16.80 | 0 |
| Guardrails de compliance | reglas deterministas | 0.00 | 0.00 | 0 |
| Verificación de cifras | reglas deterministas | 0.00 | 0.00 | 0 |
| Resumen en audio | hexgrad/kokoro-82m | 1.75 | 2.47 | 0 |
| Prompt de infografía | anthropic/claude-sonnet-5.5 | 4.76 | 5.15 | 0 |
| Generación de infografía | black-forest-labs/flux.2-klein-4b | 4.60 | 5.46 | 0 |
| Composición de infografía | black-forest-labs/flux.2-klein-4b + composición Python | 0.22 | 0.24 | 0 |

- **Informe en pantalla** (ingesta → guardrails): media 21.86 s, máx. 24.87 s.
- **Todo, incluidos audio e infografía**: media 31.44 s, máx. 35.71 s.
- Visión y STT se ejecutan en paralelo, y también TTS e infografía; por eso los tiempos por paso no suman el total.
