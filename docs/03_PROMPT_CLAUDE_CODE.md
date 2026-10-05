# Prompts para Claude Code – FinLens (Taller B5-T4)

**Cómo usarlo:** (1) crea el repo y ábrelo con Claude Code; (2) copia `02_SPEC_PRODUCTO.md` y `01_MATRIZ_REQUISITOS.md` a `docs/`; (3) pega el **Prompt maestro**; (4) ejecuta las **fases** en orden, una por una, revisando el resultado antes de pasar a la siguiente.

---

## PROMPT MAESTRO (pegar primero)

```
Actúa como ingeniero de software senior. Vamos a construir el MVP de una startup FinTech basada en IA
multimodal para un taller de máster con entrega el jueves 8 de octubre de 2026 a las 18:00.

CONTEXTO: lee docs/02_SPEC_PRODUCTO.md (alcance, arquitectura, modelos) y docs/01_MATRIZ_REQUISITOS.md
(criterios de evaluación) antes de escribir código. Son la fuente de verdad. Si algo es ambiguo,
pregúntame antes de asumir.

STACK: Python 3.11, Streamlit (UI), Pydantic, pytest. Modelos por API: LLM+visión (Anthropic),
STT/TTS/imagen (OpenAI). Recuperación local con TF-IDF (scikit-learn). Sin base de datos.

REGLAS DE ARQUITECTURA (obligatorias):
1. Estructura: src/finlens/{config.py, providers/, domain/, orchestration/, ui/}, app.py, tests/, docs/, samples/.
2. La lógica de negocio (domain/, orchestration/) solo depende de Protocols definidos en providers/base.py.
   Ningún SDK (anthropic, openai) se importa fuera de providers/.
3. Debe existir un MODO DEMO con proveedores mock: si faltan claves API o DEMO_MODE=true, la app arranca y
   recorre todo el flujo con respuestas simuladas. Los tests usan solo mocks (cero coste).
4. Toda salida del LLM es JSON validado con Pydantic y cita sus fuentes (p.ej. "documento p.3"); si el
   JSON es inválido, reintentar una vez y degradar con un mensaje claro.
5. El orquestador ejecuta visión y STT en paralelo, registra una traza por paso (paso, modelo, segundos,
   nota) y el coste estimado; la UI muestra esa traza.
6. Degradación elegante: si falla un paso opcional (TTS, imagen), se entrega igualmente el informe y se
   muestra un aviso.
7. Compliance: la herramienta informa, no asesora. Guardrail determinista que detecta lenguaje de
   recomendación (compra/venta/precio objetivo) y disclaimer en todas las salidas.
8. Cero secretos en el repo: .env.example, .gitignore con .env. Nombres de modelo y tarifas por variable de
   entorno / constantes editables, y comenta que deben verificarse en la documentación oficial.
9. Código limpio: type hints, funciones pequeñas, docstrings breves en español, sin dependencias innecesarias.
10. Idioma: README, docs, comentarios, textos de la UI y prompts en ESPAÑOL.

FORMA DE TRABAJO: trabaja por fases. Al final de cada fase: ejecuta los tests, dime qué comprobaste y qué
queda pendiente, y espera mi confirmación. No avances de fase por tu cuenta. No añadas funcionalidades
fuera del alcance de la spec (vídeo, CLIP, login, base de datos).

Empieza ahora con la FASE 0.
```

---

## FASE 0 – Esqueleto y plug-and-play
```
FASE 0. Crea la estructura de carpetas, requirements.txt (versiones razonables, sin fijar de más),
.env.example (claves, nombres de modelo, DEMO_MODE), .gitignore, Dockerfile (python:3.11-slim, expone
Streamlit), run.sh y run.bat (crear venv, instalar, lanzar la app) y un app.py mínimo que muestre el título
y el estado (modo demo / modo real). Añade config.py con un dataclass Settings leído de variables de entorno,
donde demo_mode sea verdadero si DEMO_MODE=true o si no hay ninguna clave.
Criterio de hecho: `./run.sh` abre la app en modo demo sin claves.
```

## FASE 1 – Capa de proveedores (IA)
```
FASE 1. Implementa providers/base.py con Protocols: LLMClient (complete(system, user, images, max_tokens)
-> LLMResult con texto y tokens), STTClient, TTSClient, ImageGenClient, y un dataclass ProviderSet.
Implementa: anthropic_provider (LLM + visión con imágenes base64), openai_provider (LLM opcional, Whisper STT,
TTS, generación de imagen), mock (todos, deterministas; el TTS mock genera un WAV corto; el de imagen
renderiza una tarjeta con matplotlib) y registry.build_providers(settings) que elige proveedor por
modalidad según las claves disponibles y deja notas de qué modalidades están en demo.
Tests: el registry devuelve mocks sin claves; los mocks cumplen los contratos.
```

## FASE 2 – Lógica de negocio
```
FASE 2. En domain/: schemas.py (Pydantic: KeyMetric, ChartReading, AnalysisReport, PipelineInput,
TraceStep, PipelineResult), prompts.py (system prompts en español: lector de gráficos que describe solo lo
visible y no inventa niveles; analista que usa solo el contexto, cita fuentes y baja la confianza si falta
información; generador de prompt de imagen; chat de seguimiento), ingest.py (PDF con pypdf, troceado con
número de página), rag.py (índice TF-IDF y búsqueda top-k), guardrails.py (regex de lenguaje de recomendación,
métricas sin fuente, disclaimer) y cost.py (tracker de coste por llamada con tarifas editables).
Tests: troceado, recuperación, guardrails (debe marcar "compra" y "precio objetivo"), parseo de JSON inválido.
```

## FASE 3 – Orquestador
```
FASE 3. Implementa orchestration/pipeline.py con la clase AnalystPipeline(providers, settings):
1) si hay PDF: extraer, trocear, indexar; 2) en paralelo (ThreadPoolExecutor): leer el gráfico con visión
y transcribir el audio; 3) recuperar los fragmentos relevantes a la pregunta (si la pregunta viene del audio,
usar la transcripción); 4) llamar al LLM analista con el contexto (limitado por max_context_chars) y validar
el JSON; 5) aplicar guardrails; 6) opcionales: TTS del resumen y generación de infografía (LLM crea el
prompt, modelo de imagen la genera). Registra una TraceStep por paso con modelo y segundos, acumula coste y
captura excepciones por paso añadiendo avisos en lugar de abortar. Añade un método chat(report, context,
pregunta) para el seguimiento.
Tests con mocks: flujo completo, flujo solo texto, fallo simulado de TTS (el informe sigue saliendo).
```

## FASE 4 – Interfaz
```
FASE 4. Implementa la UI en Streamlit (app.py + ui/): barra lateral con carga de PDF, imagen del gráfico,
audio (subida y, si es viable, grabación), pregunta de texto y casillas para audio/infografía; botón
"Analizar" con indicadores de progreso por paso. Resultados en pestañas: Informe (titular, resumen, métricas
con fuente, riesgos, oportunidades, disclaimer y avisos), Gráfico, Transcripción, Audio (reproductor),
Infografía, Traza y coste (tabla de pasos con modelo, segundos y coste total) y Chat de seguimiento.
Usa st.session_state, mensajes de error amigables, validación de entradas (tipo y tamaño) y un banner visible
cuando se esté en modo demo. Incluye un botón "Cargar ejemplo" que use los ficheros de samples/.
```

## FASE 5 – Calidad y entrega
```
FASE 5. (a) Revisa que ningún SDK se importe fuera de providers/ y que no haya secretos; (b) completa
tests y ejecuta pytest; (c) comprueba el arranque desde cero con run.sh y con Docker; (d) manejo de errores:
PDF sin texto, audio vacío, imagen corrupta, clave inválida; (e) añade un script scripts/medir.py que ejecute
los casos de samples/ y imprima latencia por paso y coste medio (para la sección de viabilidad del README);
(f) rellena docs/ con el diagrama mermaid de flujo y la arquitectura; (g) dame una lista de lo que falte
respecto a docs/01_MATRIZ_REQUISITOS.md.
```

## PROMPT DE REVISIÓN (antes de entregar)
```
Actúa como evaluador del taller. Con docs/01_MATRIZ_REQUISITOS.md, audita el repositorio fila por fila:
indica para cada requisito si está cubierto, parcial o falta, con la evidencia (fichero o línea) y propón la
corrección mínima. Prioriza lo que más puntúa: diversidad de modalidades, orquestación multi-modelo visible,
plug-and-play, README con capturas y diagrama, viabilidad con cifras medidas.
```

## PROMPTS PUNTUALES ÚTILES
- **Depurar:** “Esto falla: <error>. Reproduce el fallo con un test, corrígelo y explica la causa en dos líneas.”
- **Recortar alcance:** “Quedan N horas. Dime qué quitarías del MVP para entregar seguro y qué dejarías como hoja de ruta.”
- **Medir coste:** “Ejecuta scripts/medir.py con las APIs reales sobre los 3 casos y pega la tabla de latencia y coste.”
