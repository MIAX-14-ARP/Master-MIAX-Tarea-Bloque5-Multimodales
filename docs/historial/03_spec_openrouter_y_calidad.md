# 05 · Spec de mejoras (rama `mejoras/openrouter-ui`)

Autor: PM/arquitecto. Fuente de verdad para coder, QA, tester y UI. Si algo de aquí choca con el código,
gana esta spec; si choca con la realidad de una API, se documenta y se avisa al PM (no se inventa).

## 0. Reglas para todos los agentes

- **Cero alucinaciones.** No inventes endpoints, parámetros, nombres de modelo ni campos de respuesta.
  Todo lo de OpenRouter está verificado abajo (docs oficiales + catálogo público `GET /api/v1/models`,
  consultado el 2026-10-06). Lo que no esté aquí: compruébalo (WebFetch a `openrouter.ai/docs/...md`)
  o márcalo `VERIFICAR` y avisa.
- Mantén estilo del repo: español en nombres de variables locales/comentarios/mensajes de UI, docstrings breves,
  `from __future__ import annotations`, dataclasses frozen, Protocols en `providers/base.py`.
- Las capas siguen: SDKs solo en `providers/`; `domain/` y `orchestration/` solo dependen de
  `providers.base`; UI no contiene lógica de negocio. `tests/test_arquitectura.py` debe seguir pasando
  (amplía `SDK` con `httpx` si se usa directamente).
- **Nunca** leas, imprimas, registres ni copies el contenido de `.env` ni claves. Los tests usan claves falsas.
- `pytest` completo en verde antes de entregar. Nada de llamadas reales a red en tests normales (usa clientes falsos inyectados,
  como ya hacen `tests/test_providers_openai.py` y `tests/test_providers_anthropic.py`).

## 1. OpenRouter (hechos verificados)

Base URL `https://openrouter.ai/api/v1`, cabecera `Authorization: Bearer $OPENROUTER_API_KEY`.
Cabeceras opcionales de atribución: `HTTP-Referer`, `X-Title: FinLens`.
Compatible con el SDK `openai` (`openai.OpenAI(base_url=..., api_key=...)`).

| Capacidad | Endpoint | Cómo con SDK openai | Notas verificadas |
|---|---|---|---|
| LLM | `POST /chat/completions` | `client.chat.completions.create(model, messages, max_tokens, response_format?)` | `usage` trae `prompt_tokens`, `completion_tokens` y `cost` (USD real). Structured outputs: `response_format={"type":"json_schema","json_schema":{"name":..,"strict":true,"schema":..}}` + `extra_body={"provider":{"require_parameters":true}}`. Soportan structured outputs: `anthropic/claude-sonnet-5.5`, `google/gemini-3.8-flash` y otros (catálogo: `supported_parameters` contiene `structured_outputs`). |
| Visión | `POST /chat/completions` | content `[{"type":"text",...},{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}]` | mismos modelos multimodales |
| STT | `POST /audio/transcriptions` | `client.audio.transcriptions.create(model, file=(name, bytes), response_format="verbose_json")` | multipart ≤ 25 MB; timeout upstream 60 s; respuesta `text`, `duration` (verbose_json), `usage.seconds`, `usage.cost`. Formatos: wav, mp3, flac, m4a, ogg, webm, aac. Modelos: `openai/whisper-large-v3-turbo`, `openai/whisper-large-v3`, `openai/whisper-1`, `openai/gpt-4o-mini-transcribe`, `mistralai/voxtral-mini-transcribe`. Parámetro opcional `language` (ISO-639-1) → enviar `"es"`. |
| TTS | `POST /audio/speech` | `client.audio.speech.create(model, input, voice, response_format="mp3")` | devuelve bytes de audio (no JSON); `response_format` `mp3` o `pcm` (por defecto pcm → **enviar mp3 siempre**). Voces dependen del modelo. Modelos: `hexgrad/kokoro-82m` (open-weight, muy barato), `google/gemini-3.8-flash-tts`, `mistralai/voxtral-mini-tts-2603`, `qwen/qwen-audio-3.0-tts-flash`, `microsoft/mai-voice-2.1-flash`. |
| Imagen | `POST /images` (NO `/images/generations`) | `client.post("/images", body={...}, cast_to=httpx.Response)` o `httpx` directo | body: `model`, `prompt`, `n`, `aspect_ratio` (`1:1`,`16:9`,`4:3`...), `resolution` (`512`,`1K`,`2K`), `quality`, `output_format` (`png`). Respuesta `{"data":[{"b64_json":..,"media_type":"image/png"}],"usage":{"cost":..}}`. Modelos: `black-forest-labs/flux.2-klein-4b` (open-weight, barato), `bytedance-seed/seedream-4.5`, `openai/gpt-image-1-mini`, `google/gemini-2.5-flash-image`. |

Errores: códigos HTTP 400/401/402 (sin saldo)/403/404/413/429/5xx → mapear a `ProviderError` con mensaje claro
en español, igual que `translate_error` de `openai_provider.py` (402 → "Saldo de OpenRouter insuficiente").

## 2. Configuración por capacidad (sustituye al todo-o-nada)

Nuevas variables (`config.py`, `.env.example`, README):

```
OPENROUTER_API_KEY=
# Proveedor por capacidad: auto | openrouter | anthropic | openai | mock
LLM_PROVIDER=auto
VISION_PROVIDER=auto
STT_PROVIDER=auto
TTS_PROVIDER=auto
IMAGE_PROVIDER=auto
# Modelos para OpenRouter (slugs del catálogo)
OPENROUTER_LLM_MODEL=anthropic/claude-sonnet-5.5
OPENROUTER_VISION_MODEL=google/gemini-3.8-flash
OPENROUTER_STT_MODEL=openai/whisper-large-v3-turbo
OPENROUTER_TTS_MODEL=hexgrad/kokoro-82m
OPENROUTER_TTS_VOICE=ef_dora       # VERIFICAR en el test e2e; voz española de Kokoro
OPENROUTER_IMAGE_MODEL=black-forest-labs/flux.2-klein-4b
```

Regla `auto` por capacidad: OpenRouter si hay `OPENROUTER_API_KEY`; si no, proveedor nativo (anthropic para
llm/visión, openai para stt/tts/imagen) si hay su clave; si no, `mock`. `DEMO_MODE=true` fuerza mock en todo.
Si se pide explícitamente un proveedor sin clave → mock para esa capacidad + aviso.

`Providers` gana `info: tuple[ProviderInfo, ...]` con `ProviderInfo(capability: str, backend: str, model: str)`
(capability ∈ "llm","vision","stt","tts","image"; backend ∈ "openrouter","anthropic","openai","mock").
`Providers.is_demo` = True solo si **todas** son mock. Nueva propiedad `Providers.mock_capabilities -> tuple[str,...]`.
`Settings.demo_reason` se mantiene (compatibilidad) pero el registro decide por capacidad.
`build_providers(settings)` mantiene su firma.

## 3. Proveedor OpenRouter

`src/finlens/providers/openrouter_provider.py`: `OpenRouterLLM`, `OpenRouterVision`, `OpenRouterSTT`,
`OpenRouterTTS`, `OpenRouterImage`. Cliente inyectable (`client=`) para tests, timeout 120 s.
- `TextResult` gana campo opcional `cost_usd: float | None = None` (coste real si el proveedor lo informa).
  `domain/cost.text_result_cost` usa `cost_usd` si no es None; si no, tarifas. Igual para STT/TTS/imagen:
  añade `cost_usd: float | None = None` a `TranscriptionResult`, `SpeechResult`, `ImageResult`.
- LLM/visión: cuando se pide JSON, NO se depende de `response_format` (la capa `structured.py` ya valida y
  reintenta). Se envía `max_tokens` tal cual (sin el mínimo 8000 de Anthropic).
- `finish_reason == "length"` → ProviderError "respuesta cortada por límite de tokens".
- Respuesta vacía → ProviderError.
- STT: `language="es"`, `response_format="verbose_json"`; duración de `duration` o estimada.
- TTS: `response_format="mp3"`, mime `audio/mpeg`.
- Imagen: `/images`, `aspect_ratio="4:3"`, `output_format="png"`; decodificar `b64_json`.

## 4. Anthropic: `MIN_OUTPUT_TOKENS`

Hoy fuerza 8000 en todas las llamadas. Cambiar a variable `LLM_MIN_OUTPUT_TOKENS` (por defecto 4000) aplicada
solo al proveedor Anthropic nativo. Documentar por qué existe (el pensamiento comparte presupuesto).

## 5. Verificación determinista de cifras (anti-alucinación)

Nuevo `src/finlens/domain/grounding.py`:
- `FigureCheck(figure_name: str, value: str, status: Literal["verificada","no_encontrada","sin_fuente_documental"], page: int | None)`.
- `check_figures(report: AnalysisReport, document: IngestedDocument) -> tuple[FigureCheck, ...]`:
  para cada `KeyFigure` con cita `documento p.N`, normaliza los números del valor (formatos español e inglés:
  `1.234,5`, `1,234.5`, `12,3 %`, `€`, `M€`, `millones`) y comprueba que el número aparece en el texto de esa
  página (también tolera la página ±0 sólo; no busques en todo el documento). Cifras citadas solo a gráfico/audio
  → `sin_fuente_documental`.
- `AnalysisResult` gana `figure_checks: tuple[FigureCheck, ...]` y paso de traza "Verificación de cifras"
  (modelo "reglas deterministas", nota "N/M cifras verificadas"). Si alguna `no_encontrada` → warning.
- Tests unitarios exhaustivos de normalización.

## 6. Infografía honesta (cifras por Python, no por difusión)

Regla del CLAUDE.md §0.6: los modelos de imagen escriben mal números. Nuevo flujo:
1. LLM redacta prompt de **ilustración de fondo sin texto ni números** (actualiza `INFOGRAPHIC_SYSTEM`).
2. Modelo de imagen genera la ilustración.
3. `src/finlens/domain/infographic.py` (matplotlib + Pillow, backend `Agg`) compone la infografía final:
   ilustración como cabecera/fondo atenuado + título + tarjetas con las **cifras clave verificadas**
   (valor tal cual del informe, sin reinterpretar) + tendencia del gráfico + pie
   «Generado con IA · Solo informativo · Fuentes: p.N». Devuelve PNG bytes.
   Si la generación de la ilustración falla → componer igualmente sin ilustración (degradación).
4. `MediaResult.image` = la infografía compuesta (`ImageResult`, model = "<modelo imagen> + composición Python").
   `MediaResult` gana `illustration: ImageResult | None` (la cruda).
Paleta/tipografía de la composición: la define el agente UI (constantes en `infographic.py`, sección `ESTILO`).

## 7. Calidad de ingeniería

- `requirements.txt` con versiones **fijadas (==)** y compatibles con Python 3.11 (Dockerfile) y 3.12+.
  Comprueba con `pip download --python-version 3.11 --only-binary=:all: --no-deps -d <tmp> <pkg>==<ver>`.
  Añade `matplotlib` y `pillow`. `requirements-dev.txt`: pytest, ruff, mypy fijados.
- `pyproject.toml`: metadatos del paquete `finlens` (src layout), config de ruff (line-length 110, reglas
  E,F,I,B,UP,SIM), mypy (no estricto total; `ignore_missing_imports`), pytest (mover desde pytest.ini y borrar
  pytest.ini). `pip install -r requirements.txt` debe seguir siendo suficiente para arrancar.
- `.github/workflows/ci.yml`: Python 3.11 y 3.12, instala dev, `ruff check`, `mypy src`, `pytest`. Sin secretos.
- Logging: `logging` estándar, logger `finlens`, configurado en `app.py`/scripts (nivel por `LOG_LEVEL`).
  `_execute` del pipeline registra paso, modelo, segundos y ok/fallo. **Nunca** contenido de documentos ni claves.
- `AnalysisCache` con tope LRU (por defecto 16 entradas, `OrderedDict`).
- `ruff check` y `mypy src` limpios.

## 8. Contrato para la UI (no cambiar sin avisar al PM)

La UI puede usar: `Providers.info`, `Providers.is_demo`, `Providers.mock_capabilities`,
`AnalysisResult.figure_checks`, `MediaResult.illustration`, `TextResult/... .cost_usd` vía `TraceStep.cost_usd`
(ya existente), y todo lo que ya existía. Firmas públicas de `analyze`, `generate_media`, `answer_followup`,
`build_providers`, `build_mock_providers` se mantienen.

---

## 9. Ronda 2: defectos detectados en el E2E real (2026-10-06, caso `samples/01_inditex`)

E2E real con OpenRouter: funciona de punta a punta (≈38 s, ≈0,07 USD con medios). Defectos de calidad:

### 9.1 Recuperación multilingüe (BLOQUEANTE de calidad)
Pregunta en español + informe en inglés → TF-IDF no encuentra la cuenta de resultados (p.5) ni las
perspectivas (p.20); el LLM responde "no constan ventas ni margen" aunque están en el PDF.
Arreglo: **recuperación híbrida** con embeddings multilingües.
- Nuevo Protocol `EmbeddingProvider.embed(texts: Sequence[str], kind: Literal["query","document"]) -> EmbeddingResult(vectors: list[list[float]], model: str, tokens: int, cost_usd: float | None)` en `providers/base.py`; 6ª capacidad `"embeddings"` en registro/`ProviderInfo` (`EMBEDDINGS_PROVIDER=auto|openrouter|openai|mock`).
- OpenRouter: `POST /embeddings` vía `client.embeddings.create(model=..., input=[...])` (VERIFICADO en vivo
  con openai 3.24: `r.data[i].embedding`, `r.usage.prompt_tokens`, `r.usage.cost`). Modelo por defecto
  `OPENROUTER_EMBEDDINGS_MODEL=baai/bge-m3` (open-weight, multilingüe, 1024 dims; 78 fragmentos en 1,8 s y
  0,0002 USD). Lotes de ≤ 64 textos. OpenAI nativo: `text-embedding-3-small`. Mock: vector determinista
  (p.ej. hashing de tokens) para tests y demo.
- `domain/rag.py`: `HybridRetriever` = TF-IDF (léxico, siempre) + coseno sobre embeddings (si disponibles),
  fusionados con Reciprocal Rank Fusion (k=60). Si el paso de embeddings falla → degradar a TF-IDF con warning.
  numpy permitido en domain. `RETRIEVAL_K` 4 → 8 (contexto barato; mejora cobertura).
- Pipeline: paso de traza "Índice semántico (embeddings)" en la ingesta (coste real) y "Recuperación"
  indica "híbrida (TF-IDF + bge-m3)" o "solo TF-IDF". El chat de seguimiento reutiliza el índice (embebe solo la pregunta).
- La caché de análisis ya cubre no re-embeber el mismo PDF.

### 9.2 Grounding con escalas y lenguaje
El LLM tradujo "€10.7 billion" a "10.700 millones de euros" → `no_encontrada` falso.
- (a) Prompt: en `key_figures.value` copiar la cifra **literal como aparece en el documento** (mismo idioma,
  formato y unidad); traducir solo `name`.
- (b) `grounding.py`: además de coincidencia exacta, aceptar equivalencia de escala: un número del valor
  coincide con uno de la página si `a == b * 10**k` para k ∈ {±3, ±6, ±9} con tolerancia de redondeo
  (comparar con la precisión decimal del más corto; p.ej. 10.7e9 vs 10.700e6 vs 10,7 mil millones).
  Reconocer escalas por palabra: miles/thousand(s)/k, millones/million(s)/mn/M, mil millones/billion(s)/bn/B.
  Estado nuevo NO: mantener los tres estados; añadir campo `matched: str | None` con el texto encontrado en la
  página (para que la UI muestre "p.15: €10.7 billion").
- Tests con los casos reales: "39.864 millones" vs "Net sales (4) 39,864" (tabla en millones), "58,3 %" vs
  "58.3%", "€10.7 billion" vs "10.700 millones", "4,8%" vs "4.8%".

### 9.3 STT truncado (proveedor upstream intermitente)
Observado: `openai/whisper-large-v3(-turbo)` en OpenRouter devuelve a veces sólo el primer segmento
(duration 7.4 s de un audio de 83 s). `openai/gpt-4o-mini-transcribe` y `mistralai/voxtral-mini-transcribe`
transcribieron completo.
- Medir duración real del audio con `mutagen==1.47.0` (pure Python, wheel py3 verificado) para mp3/m4a/ogg/flac/wav;
  sustituye a la estimación por bytes cuando sea posible.
- Si la duración informada por el proveedor (o `usage.seconds`) < 80 % de la real, o el texto tiene < 4
  caracteres por segundo de audio real → reintentar UNA vez con `OPENROUTER_STT_FALLBACK_MODEL`
  (por defecto `openai/gpt-4o-mini-transcribe`; vacío = sin respaldo). Nota en traza "reintento por transcripción truncada".
- Si el respaldo también parece truncado → aceptar la mejor (más larga) y warning.

### 9.4 Otros
- `scripts/medir.py`: forzar UTF-8 en stdout (`sys.stdout.reconfigure(encoding="utf-8")`) para Windows.

### 9.5 Peticiones de la UI al backend
- `TraceStep.started_s: float | None = None`: segundos desde el inicio de la fase (`analyze` o
  `generate_media`) en que empezó el paso. Rellenarlo en `_execute` y en los pasos manuales. Gantt exacto.
- `analyze(..., on_step: Callable[[str, Literal["start","end"], TraceStep | None], None] | None = None)`
  y lo mismo en `generate_media`: callback opcional de progreso, llamado al empezar y al acabar cada paso
  (thread-safe: puede llamarse desde hilos del pool). Firmas existentes siguen funcionando sin él.
  La UI (`ui/live.py`) lo usará en lugar de envolver proveedores (eso lo cambia el agente UI después).
- `AnalysisReport.contradictions: list[Finding] = []` + regla en `ANALYST_SYSTEM`: las contradicciones entre
  modalidades van ahí (no mezcladas en `correlations`). Actualizar mock.
- Mayúsculas/textos fijos de la infografía (`TITULO`, `LEYENDA`, encabezados) dentro del bloque ESTILO.
- `scripts/preparar_casos.py`: arreglar avisos de ruff (UP017, B905).
- Embeddings (§9.1) añade una 6ª capacidad: la UI la mostrará en la barra de proveedores.
