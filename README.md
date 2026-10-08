# FinLens – Research financiero multimodal con cifras verificadas

[![CI](https://github.com/piettro/Master-MIAX-Tarea-Bloque5-Multimodales/actions/workflows/ci.yml/badge.svg)](https://github.com/piettro/Master-MIAX-Tarea-Bloque5-Multimodales/actions/workflows/ci.yml)

> Taller B5-T4 · Máster en IA y computación cuantitativa aplicada a mercados financieros (Instituto BME)
> Equipo: **Piettro Rodrigues, Alonso Díaz y Raúl Rodríguez** · Entrega: 8 de octubre de 2026
>
> *Startup ficticia creada como práctica de máster: el modelo de negocio es un ejercicio, no una oferta real.*

**Demo desplegada (AWS):** <https://108-128-114-211.sslip.io> (protegida con contraseña: cada análisis gasta
crédito real; pídela al equipo) · **Vídeo de la demo (2:52):** [`docs/video/FinLens_demo.mp4`](docs/video/FinLens_demo.mp4)
**Propuesta de MVP (PDF, punto 4.1 del enunciado):** [`docs/propuesta_mvpFinlens.pdf`](docs/propuesta_mvpFinlens.pdf)
· **Pitch:** [`docs/pitch.pdf`](docs/pitch.pdf) · **Informe de costes y latencias:** [`docs/medidas.md`](docs/medidas.md)

[![Vídeo de la demo de FinLens (2:52): pulsa para verlo](docs/img/readme/video.jpg)](docs/video/FinLens_demo.mp4)

*▶ Vídeo de la demo (2:52, 1080p, con APIs reales): caso Inditex con PDF, gráfico, audio y ticker, y caso BTC
preguntando por voz. Pulsa la imagen para verlo; si el navegador no lo reproduce, usa «View raw» para
descargarlo. Subtítulos en [`docs/video/FinLens_demo.srt`](docs/video/FinLens_demo.srt).*

**En una frase:** FinLens cruza el informe anual (PDF), el gráfico, el audio de la conferencia y los datos de
mercado de una cotizada en una nota de research donde **cada cifra cita su fuente y la verifica el código**,
no el LLM. Cuesta **0,06 USD** y tarda **≈31 s** por análisis completo (medido con APIs reales).

### Tareas

| Enunciado del taller | Dónde verlo |
|---|---|
| 4.1 Esquema del problema, público (B2B/B2B2C) y propuesta de valor multimodal | [§1](#1-problema-y-propuesta-de-valor) |
| 4.1 Viabilidad: costes de inferencia y consumo de APIs | [§5](#5-viabilidad-técnica-y-económica) y [`docs/medidas.md`](docs/medidas.md) |
| 4.1 Latencias para una experiencia fluida | [§5](#5-viabilidad-técnica-y-económica) |
| 4.1 Marco regulatorio: compliance y privacidad (incluidos datos bancarios) | [§6](#6-compliance-y-privacidad) |
| 4.1 Modelo de monetización | [§7](#7-monetización) |
| 4.2 Diversidad de modalidades y orquestación de varios modelos | [§2](#2-qué-hace-demo-en-30-segundos) y [§3](#3-arquitectura-y-flujo-de-datos-multimodal) |
| 4.3 MVP operativo, UI/UX, robustez y plug-and-play | [§4](#4-instalación-y-ejecución-plug-and-play) y [§9](#9-capturas) |
| 4.4 README con capturas, diagrama de flujo y arquitectura; pitch; modularidad | [§3](#3-arquitectura-y-flujo-de-datos-multimodal), [§8](#8-pitch-técnico), [§9](#9-capturas) |
| 5. Entregables: repositorio y demo funcional | Este repositorio · demo en AWS (enlace arriba) · [vídeo de la demo](docs/video/FinLens_demo.mp4) |

## 1. Problema y propuesta de valor

El analista financiero cruza a mano fuentes que viven en formatos distintos: el **informe anual en PDF**
(cientos de páginas, a menudo en inglés), el **gráfico de cotización**, el **audio de la conferencia de
resultados** y los **datos de mercado**. La parte valiosa —*¿lo que dice la dirección encaja con las cifras y
con lo que descuenta el mercado?*— se hace sin trazabilidad, y los asistentes de IA genéricos **inventan
cifras**.

**Público objetivo (B2B):** analistas junior y *sell-side*, EAFI y asesores independientes, gestoras boutique
y equipos de relación con inversores. Extensión B2B2C: módulo embebido en plataformas de brokers.

**Propuesta de valor:** una sola consulta cruza **texto, imagen, voz y datos de mercado** y devuelve una nota
de research donde **cada cifra lleva su fuente y un sello de verificación** calculado por código, no por el
LLM. Tres diferenciales:

1. **Cifras verificadas:** Python comprueba que cada número aparece en la página citada del PDF, en los
   fundamentales oficiales de la SEC o en los indicadores calculados («✓ VERIFICADA p.5 · «39,864»»).
2. **«La IA vio · los datos dicen»:** el modelo de visión lee el gráfico y Python contrasta cada nivel,
   soporte o tendencia que afirma con la serie real de precios (detector de alucinaciones visuales).
3. **Correlación y contradicciones entre modalidades:** informe ↔ gráfico ↔ dirección ↔ mercado.

```mermaid
flowchart LR
  P["Problema<br/>PDF + gráfico + audio + mercado<br/>dispersos · IA que inventa cifras"] --> S["FinLens<br/>una consulta, 6 modelos encadenados"]
  S --> V1["Cifras con fuente<br/>y sello de verificación"]
  S --> V2["Lectura del gráfico<br/>contrastada con los datos"]
  S --> V3["Declaraciones de la dirección"]
  S --> V4["Correlaciones y contradicciones"]
  V1 & V2 & V3 & V4 --> O["Nota citada · audio · infografía · chat"]
```

## 2. Qué hace (demo en 30 segundos)

1. Eliges un caso de ejemplo (ficticio, **Inditex real** o solo ticker BTC; los ficheros se pueden descargar)
   o aportas cualquier combinación de: informe anual (PDF), gráfico de cotización, audio de la conferencia o
   **tu pregunta por voz** (grabada en el navegador), y un **ticker** (`ITX.MC`, `AAPL`, `BTC`…).
2. Con ticker, FinLens **descarga los datos**: acciones de **Yahoo Finance**, cripto de **Hyperliquid**
   (velas, *funding* y *open interest* on-chain) y fundamentales oficiales de la **SEC EDGAR** (10-K).
3. Obtienes una **nota de análisis** con cifras citadas y verificadas, lectura del gráfico contrastada,
   declaraciones de la dirección, correlaciones y contradicciones, un **resumen en audio** y una
   **infografía** cuyas cifras dibuja Python.
4. Sigues preguntando en el **chat**, que reutiliza el índice del documento, y **descargas la nota completa en
   PDF** (cifras con sello, gráfico, contraste, técnicos, transcripción, infografía, chat y traza de coste).
5. El **cerebro** (red neuronal 3D) y el **mapa de la cadena** muestran qué entra, qué modelo actúa, en qué
   orden y en paralelo, y qué sale; la **traza** da tiempo y coste por paso.

| Entradas (6) | Salidas (7) |
|---|---|
| PDF · imagen de gráfico · audio (conferencia) · voz (pregunta) · texto · ticker → datos de mercado y SEC | Nota citada y verificada · contraste visión↔datos · audio TTS · infografía · chat · **nota en PDF** · traza de coste |

## 3. Arquitectura y flujo de datos multimodal

```mermaid
flowchart LR
  PDF[PDF informe] --> ING["Ingesta y troceado<br/>pypdf"] --> EMB["Embeddings multilingües<br/>bge-m3"] & TF["TF-IDF local"]
  TK[Ticker] --> MD["Datos de mercado<br/>Yahoo · Hyperliquid"] --> TEC["Indicadores técnicos<br/>numpy"] --> GC["Gráfico generado<br/>matplotlib"]
  TK --> SEC["Fundamentales<br/>SEC EDGAR XBRL"]
  IMG[Gráfico subido] --> VIS
  GC --> VIS["Visión<br/>gemini-3.8-flash"] --> CC["Contraste visión ↔ datos<br/>Python"]
  TEC --> CC
  AUD[Audio / voz] --> STT["Voz a texto<br/>whisper-large-v3-turbo"]
  Q[Pregunta] --> RAG["Recuperación híbrida<br/>RRF ponderado"]
  EMB & TF --> RAG
  RAG & VIS & STT & TEC & SEC --> LLM["LLM analista<br/>claude-sonnet-5.5"]
  LLM --> GR["Guardrails compliance<br/>(deterministas)"] --> VER["Verificación de cifras<br/>(determinista)"] --> REP[Nota citada]
  REP --> TTS["Texto a voz<br/>kokoro-82m"]
  REP --> PRM["LLM: prompt de ilustración<br/>(sin cifras)"] --> IGEN["Imagen<br/>flux.2-klein-4b"] --> COMP["Composición Python<br/>cifras verificadas"]
  REP --> CHAT[Chat de seguimiento]
```

**Paralelismo real:** embeddings ‖ (mercado → técnicos → gráfico → visión → contraste) ‖ SEC ‖ STT, y luego
TTS ‖ infografía. La nota aparece en cuanto está lista; audio e infografía llegan después.

### Cadena de modelos (todos vía OpenRouter con una sola clave)

| Paso | Modelo por defecto | Por qué este | Alternativas probadas o configurables |
|---|---|---|---|
| Texto→texto (análisis, chat) | `anthropic/claude-sonnet-5.5` | Mejor seguimiento de JSON con citas; reconoce cuando un dato no consta en vez de inventarlo | `anthropic/claude-opus-5.5` (más caro), `google/gemini-3.8-flash` (más barato) |
| Imagen→texto (gráfico) | `google/gemini-3.8-flash` | Multimodal rápido (≈5 s) y barato (≈0,002 USD); proveedor distinto al LLM | `anthropic/claude-sonnet-5.5` |
| Voz→texto | `openai/whisper-large-v3-turbo` | Abierto, ≈0,0001 USD por audio de 80 s | `openai/whisper-large-v3` **devolvió transcripciones truncadas** en pruebas; `openai/gpt-4o-mini-transcribe` y `mistralai/voxtral-mini-transcribe` completas → el primero es el **respaldo automático** si se detecta truncado |
| Texto→voz | `hexgrad/kokoro-82m` | Modelo abierto de 82 M parámetros con voces en español; 0,0004 USD por resumen | `google/gemini-3.8-flash-tts`, `mistralai/voxtral-mini-tts-2603` |
| Texto→imagen | `black-forest-labs/flux.2-klein-4b` | Abierto y barato (0,015 USD); **solo ilustra**: las cifras las dibuja Python porque los modelos de difusión escriben mal los números | `bytedance-seed/seedream-4.5`, `openai/gpt-image-1-mini` |
| Embeddings | `baai/bge-m3` | Multilingüe y abierto: con la pregunta en español encuentra las páginas en inglés (1,8 s, 0,0002 USD para 78 fragmentos) | `qwen/qwen3-embedding-8b` (6,7 s y peor ranking en nuestra prueba); TF-IDF solo **falla** con pregunta en español y PDF en inglés |
| Datos de mercado | Yahoo Finance · Hyperliquid · SEC EDGAR | Públicos y sin clave; Hyperliquid aporta derivados on-chain (*funding*, OI) | En producción: proveedor con licencia (p. ej. BME Market Data) |

Más los pasos **deterministas en Python**: ingesta, TF-IDF, fusión RRF, indicadores técnicos, gráfico,
contraste visión↔datos, guardrails, verificación de cifras y composición de la infografía. Son el
antídoto contra las alucinaciones: los números que ve el usuario salen de datos o los comprueba el código.

Cada capacidad se elige por separado (`*_PROVIDER=auto|openrouter|anthropic|openai|mock`); también funciona
con claves nativas de Anthropic y OpenAI. Sin claves, **modo demo** completo con modelos simulados.

**Capas** (la separación la hace cumplir `tests/test_arquitectura.py`):

| Capa | Responsabilidad |
|---|---|
| `providers/` | Conexión con los modelos de IA. **Única** capa que importa los SDK. `Protocol`s en `base.py`, implementaciones OpenRouter/Anthropic/OpenAI y *mocks*. |
| `sources/` | Conectores de datos externos (Yahoo, Hyperliquid, SEC). Sin IA. |
| `domain/` | Lógica de negocio pura: ingesta, RAG híbrido, prompts, esquemas Pydantic, guardrails, verificación de cifras, técnicos, contraste, infografía, coste. |
| `orchestration/` | Encadenado, paralelismo, traza, degradación, caché LRU y métricas. |
| `ui/` + `app.py` | Interfaz Streamlit. Sin lógica de negocio. |

**Decisiones de diseño:** salidas del LLM como JSON validado con Pydantic y citas obligatorias (un reintento
con el motivo del fallo); degradación elegante (si falla un paso opcional se entrega el resto con aviso);
contenido de documentos tratado como datos, no instrucciones (*prompt injection*); detección de STT
truncado con reintento; razonamiento del LLM acotado (`OPENROUTER_REASONING_EFFORT`) para no cortar el JSON.

Las especificaciones de cada iteración (producto inicial, OpenRouter y calidad, mercado y cerebro) están en
[`docs/historial/`](docs/historial/README.md).

## 4. Instalación y ejecución (plug-and-play)

Requisitos: **Python 3.11+** (CI en 3.11 y 3.12) o Docker. Sin claves arranca en **modo demo**.

```bash
git clone https://github.com/piettro/Master-MIAX-Tarea-Bloque5-Multimodales.git finlens && cd finlens
cp .env.example .env        # opcional: pon OPENROUTER_API_KEY para usar modelos reales
./run.sh                    # Windows: run.bat
```

**Docker:**

```bash
docker build -t finlens .
docker run -p 8501:8501 --env-file .env finlens
```

**Despliegue en AWS** (EC2 + Caddy HTTPS, imagen en ECR, secretos en Secrets Manager, CI/CD con GitHub
Actions y OIDC, sin claves de AWS en GitHub): ver [`docs/DESPLIEGUE.md`](docs/DESPLIEGUE.md).

**Variables principales** (todas en [`.env.example`](.env.example)):

| Variable | Para qué |
|---|---|
| `OPENROUTER_API_KEY` | Una sola clave para las 6 capacidades de IA |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | Alternativa: proveedores nativos |
| `*_PROVIDER` | `auto` (por defecto), `openrouter`, `anthropic`, `openai` o `mock`, por capacidad |
| `OPENROUTER_*_MODEL`, `OPENROUTER_TTS_VOICE`, `OPENROUTER_STT_FALLBACK_MODEL` | Modelos (slugs del catálogo de OpenRouter) |
| `OPENROUTER_REASONING_EFFORT`, `OPENROUTER_MIN_OUTPUT_TOKENS`, `STT_LANGUAGE` | Razonamiento, mínimo de tokens, idioma de transcripción |
| `SEC_USER_AGENT` | Contacto que exige la SEC para descargar fundamentales |
| `APP_PASSWORD` | Contraseña de la demo pública (vacía = acceso libre en local) |
| `DEMO_MODE`, `MAX_PDF_CHARS`, `LOG_LEVEL`, `PRICE_*` | Modo demo, límite de entrada, logs y tarifas de respaldo |

**Calidad:**

```bash
pip install -r requirements-dev.txt
pytest                                       # más de 800 tests con mocks y datos grabados (cero coste, sin red)
ruff check . && mypy src                     # también en CI (GitHub Actions, 3.11 y 3.12)
FINLENS_LIVE_TESTS=1 pytest -m live -v -s    # humo contra las APIs reales (céntimos)
python scripts/medir.py -n 3 --salida docs/medidas.md   # coste y latencia reales
```

## 5. Viabilidad técnica y económica

Medido con APIs reales el **7-oct-2026** sobre los casos reales de `samples/` (informe anual 2025 de
Inditex, gráfico real de ITX.MC y audio): **6 ejecuciones, 0 fallos**. Informe completo en
[`docs/medidas.md`](docs/medidas.md). El coste es **99 % real** (lo informa OpenRouter en cada respuesta,
`usage.cost`), no una estimación.

| Componente | Uso medio | Coste medio (USD) |
|---|---|---|
| LLM (análisis + prompt de ilustración) | 8.849 tokens entrada / 3.092 salida | 0,0446 |
| Voz a texto | 0,7 min | 0,0001 |
| Texto a voz | 710 caracteres | 0,0004 |
| Imagen | 1 ilustración | 0,0150 |
| Embeddings | 21.395 tokens | 0,0002 |
| **Total por análisis completo** | | **0,060** |

Un análisis **solo con ticker** (sin PDF ni medios) cuesta **≈0,027 USD** y tarda ≈17–20 s (medido con
AAPL y BTC: 11/11 cifras verificadas en ambos).

**Latencia: objetivo y resultado.** FinLens no es un chat en tiempo real, es una herramienta de research: un
analista tarda horas en cruzar estas fuentes a mano. Por eso proponemos como **objetivo del MVP** que la nota
esté en pantalla en **≤ 30 s** y que el análisis completo (con audio e infografía) termine en **≤ 60 s**, con
render progresivo para que la espera sea legible (el mapa de la cadena y la traza muestran cada paso en vivo).

| Latencia (6 ejecuciones) | Objetivo | Media medida | Máx. | ¿Cumple? |
|---|---|---|---|---|
| Nota en pantalla (ingesta → verificación) | ≤ 30 s | **21,9 s** | 24,9 s | ✅ |
| Todo, con audio e infografía | ≤ 60 s | **31,4 s** | 35,7 s | ✅ |
| Análisis LLM (el paso más lento) | — | 13,9 s | 16,8 s | — |
| Lectura del gráfico | — | 4,8 s | 5,5 s | — |
| Transcripción (80 s de audio) | — | 3,7 s | 7,0 s | — |

Para bajar la latencia: modelo más rápido para el análisis (`gemini-3.8-flash`), *streaming* de la respuesta y
caché del índice por documento.

<details>
<summary><b>Informe de costes y latencias completo</b> (mismo contenido que <a href="docs/medidas.md"><code>docs/medidas.md</code></a>)</summary>

**Modelos medidos:** `anthropic/claude-sonnet-5.5` (análisis y prompt de ilustración),
`google/gemini-3.8-flash` (visión), `openai/whisper-large-v3-turbo` (voz a texto), `hexgrad/kokoro-82m`
(texto a voz), `black-forest-labs/flux.2-klein-4b` (imagen) y `baai/bge-m3` (embeddings), todos vía OpenRouter.

**Origen del coste:** 99 % **real** (informado por el proveedor en cada respuesta, `usage.cost` de OpenRouter);
el 1 % restante se **estima** con tarifas de respaldo (USD): LLM 2,0 / 10,0 por millón de tokens
(entrada / salida), STT 0,006 por minuto, TTS 0,62 por millón de caracteres, imagen 0,04 por unidad. Son
orientativas y deben verificarse en las páginas oficiales.

| Paso | Modelo | Media (s) | Máx. (s) | Fallos |
|---|---|---|---|---|
| Ingesta e índice | pypdf + TF-IDF | 0,28 | 0,30 | 0 |
| Índice semántico (embeddings) | baai/bge-m3 | 4,21 | 9,21 | 0 |
| Lectura del gráfico | google/gemini-3.8-flash | 4,77 | 5,50 | 0 |
| Transcripción de audio | openai/whisper-large-v3-turbo | 3,66 | 6,98 | 0 |
| Recuperación | TF-IDF + bge-m3 | 1,06 | 3,69 | 0 |
| Análisis (LLM) | anthropic/claude-sonnet-5.5 | 13,86 | 16,80 | 0 |
| Guardrails de compliance | reglas deterministas | 0,00 | 0,00 | 0 |
| Verificación de cifras | reglas deterministas | 0,00 | 0,00 | 0 |
| Resumen en audio | hexgrad/kokoro-82m | 1,75 | 2,47 | 0 |
| Prompt de infografía | anthropic/claude-sonnet-5.5 | 4,76 | 5,15 | 0 |
| Generación de infografía | black-forest-labs/flux.2-klein-4b | 4,60 | 5,46 | 0 |
| Composición de infografía | flux.2-klein-4b + composición Python | 0,22 | 0,24 | 0 |

Visión y transcripción corren en paralelo, y también audio e infografía, por lo que los tiempos por paso
**no suman** el total. Para reproducir la medición (consume crédito, ≈0,4 USD con 6 ejecuciones):
`python scripts/medir.py -n 3 --salida docs/medidas.md`.

</details>

**Palancas de coste:** recuperación (no se envía el PDF entero), límite de entrada, caché por *hash*, omitir
audio o infografía, esfuerzo de razonamiento acotado y modelos abiertos baratos en TTS, imagen y embeddings.

**Infraestructura de la demo:** EC2 t3.micro + IPv4 + disco ≈ **12 USD/mes** (dentro del presupuesto de
14 USD/mes de la cuenta AWS del máster).

## 6. Compliance y privacidad

- **MiFID II / CNMV — informa, no asesora:** guardrail determinista (`domain/guardrails.py`) que detecta
  recomendaciones en español e inglés (imperativo, condicional, *rating*, precio objetivo de un valor…) en la
  nota, el chat, el guion de audio y el prompt de imagen; **retira solo la frase infractora**, avisa y añade
  un aviso legal a cada salida (también hablado). Normaliza caracteres invisibles para que no se pueda
  esquivar. Es una heurística conservadora; no sustituye la revisión legal.
- **Anti-alucinación:** citas obligatorias + verificación determinista de cifras y del gráfico.
- **RGPD:** no se almacenan documentos; la caché vive en memoria de la sesión. En modo real los datos van a
  los proveedores de IA (se avisa en la interfaz). En producción: DPA y proveedores con residencia en la UE.
- **Datos bancarios (PSD2):** el MVP **no se conecta a cuentas ni solicita datos bancarios de clientes**: solo
  procesa documentos públicos de empresas cotizadas (informes, conferencias) y datos de mercado públicos. Si
  en el futuro se integraran cuentas bancarias, harían falta un proveedor autorizado bajo PSD2 (AISP) o un
  socio que lo sea, consentimiento explícito y revocable del cliente, minimización y cifrado de los datos, y un
  contrato de encargo del tratamiento conforme al RGPD.
- **AI Act:** transparencia: todo se marca como generado por IA y cada afirmación cita su fuente.
- **Seguridad de la demo:** contraseña, secretos en AWS Secrets Manager, OIDC entre GitHub y AWS, IMDSv2,
  sin SSH, HTTPS. Riesgo conocido de la industria: clonación de voz (no usamos clonación).
- **Datos de mercado:** Yahoo Finance es una API no oficial (uso académico); en producción, proveedor con licencia.

*(No es asesoramiento legal.)*

## 7. Monetización

SaaS B2B por volumen de análisis. Coste variable medido: **0,060 USD por análisis completo** (≈0,055 €).
Precios **hipotéticos** (práctica de máster) con margen bruto sobre el coste de IA:

| Plan | Para quién | Incluye | Precio | Coste IA máx. | Margen bruto |
|---|---|---|---|---|---|
| **Free** | Probar | 5 análisis/mes, solo nota, marca de agua | 0 € | 0,28 € | captación |
| **Pro** | Analista individual | 150 análisis/mes, audio, infografía, chat, mercado | **49 €/mes** | 8,3 € | **≈83 %** |
| **Team** | Gestoras, EAFI (5 usuarios) | 1.000 análisis/mes, espacio compartido | **390 €/mes** | 55 € | **≈86 %** |
| **API** | Brokers (B2B2C) | Pago por uso, integración | **0,25 €/análisis** | 0,055 € | **≈78 %** |

*(Conversión: 1 USD ≈ 0,92 €. Margen bruto = (precio − coste de IA) / precio, con el plan usado al máximo de
su cupo.)* El margen real será menor (infraestructura, soporte, datos de mercado con licencia), pero el coste
de IA no es la restricción: el de un plan Pro **completo** (150 análisis) son 8,3 €, apenas el 17 % de su precio.

## 8. Pitch técnico

Seis diapositivas, en **[`docs/pitch.pdf`](docs/pitch.pdf)** (texto fuente en [`docs/pitch.md`](docs/pitch.md); se
regenera con `python scripts/pitch_pdf.py --miniaturas`):

![Las seis diapositivas del pitch técnico](docs/img/readme/pitch.png)

| # | Diapositiva | Mensaje |
|---|---|---|
| 1 | **El problema** | El analista cruza a mano cuatro fuentes que nada conecta (PDF, gráfico, audio, mercado) y la IA genérica **inventa cifras**. Público B2B: analistas, EAFI, gestoras boutique. |
| 2 | **La solución** | Una nota de research **citada y verificada en ≈30 s**, desde un ticker o desde el informe, el gráfico y el audio. |
| 3 | **Por qué multimodal** | Seis modelos especializados encadenados más verificación determinista en Python. Diferencial: **«La IA vio · los datos dicen»** y cifras verificadas. |
| 4 | **Arquitectura** | Capas separadas, proveedores intercambiables por capacidad, modo demo, degradación elegante, más de 800 tests y CI/CD a AWS. |
| 5 | **Viabilidad y negocio** | **0,060 USD** por análisis, nota en 21,9 s, todo en 31,4 s; compliance por diseño; planes de 49 €, 390 € y 0,25 €/análisis. |
| 6 | **Tracción y hoja de ruta** | Equipos de research de boutiques y EAFI; vídeo-análisis, OCR, comparación entre empresas, alertas por ticker. |

## 9. Capturas

Recorrido por una ejecución real: **APIs reales** (OpenRouter, Yahoo Finance, SEC) sobre el caso
`samples/01_inditex` más el ticker `ITX.MC`. Las capturas completas, sin recortar, están en [`docs/img/`](docs/img).

**1 · Nota de análisis: cada cifra con su fuente y su sello de verificación** (11/11 verificadas)

![Nota de análisis con cifras verificadas](docs/img/readme/nota.png)

**2 · «La IA vio · los datos dicen»: el gráfico se contrasta con la serie real de precios** (9 de 9 afirmaciones
de la visión confirmadas)

![Contraste entre la lectura de la visión y los datos de mercado](docs/img/readme/contraste.png)

**3 · Audio e infografía: la ilustración la hace un modelo de difusión; las cifras las dibuja Python**

![Resumen en audio e infografía](docs/img/readme/infografia.png)

**4 · La cadena de modelos en vivo (el «cerebro»): qué entra, qué modelo actúa, en qué orden y en paralelo**

![Cadena de modelos en vivo](docs/img/readme/cerebro.png)

**5 · Traza de modelos: tiempo, tokens y coste real por paso** (18 pasos, 13 motores, 0,0651 USD en esta ejecución)

![Traza de modelos con diagrama de Gantt y coste por paso](docs/img/readme/traza.png)

## 10. Limitaciones y hoja de ruta

- El **guardrail** es heurístico: puede dejar pasar formulaciones muy indirectas («yo me saldría del valor»).
- La **verificación de cifras** comprueba que el número está en la fuente citada, no que su interpretación
  sea correcta.
- Sin **OCR**: un PDF escaneado no se puede analizar.
- Los **audios de la demo son sintéticos** (lectura de extractos del propio informe): los de earnings calls
  reales tienen derechos de autor.
- Precisión del análisis **no evaluada sistemáticamente** (sería el siguiente paso: conjunto de preguntas con
  respuesta conocida).
- **Hoja de ruta:** vídeo-análisis de webinars, OCR, *streaming*, comparación entre empresas, alertas por
  ticker, multiusuario con autenticación real y evaluación continua.

## 11. Estructura del repositorio

```
├── app.py                      # entrada de Streamlit (solo UI)
├── requirements*.txt · pyproject.toml · Dockerfile · run.sh · run.bat · .env.example
├── src/finlens/
│   ├── config.py               # ajustes por variables de entorno
│   ├── providers/              # Protocols + OpenRouter, Anthropic, OpenAI, mocks, registro por capacidad
│   ├── sources/                # Yahoo Finance, Hyperliquid, SEC EDGAR (+ mock)
│   ├── domain/                 # ingesta, RAG híbrido, prompts, esquemas, guardrails, verificación de cifras,
│   │                           # técnicos, gráfico, contraste visión↔datos, infografía, coste
│   ├── orchestration/          # pipeline paralelo, traza, caché LRU, métricas
│   └── ui/                     # tema editorial, mapa de la cadena, cerebro 3D (Three.js), Gantt, vistas
├── scripts/                    # medir.py, preparar_casos.py, pitch_pdf.py, propuesta_pdf.py
├── samples/                    # casos reales (Inditex) y entradas inválidas
├── deploy/                     # CloudFormation (AWS) y script de despliegue
├── .github/workflows/          # CI (ruff, mypy, pytest) y despliegue a AWS
├── tests/                      # más de 800 tests (mocks y respuestas reales grabadas)
└── docs/                       # propuesta y pitch (PDF), medidas, despliegue, guion del vídeo, enunciado, historial/
```

## Aviso legal

Información generada con IA con fines informativos. No constituye asesoramiento en materia de inversión.
