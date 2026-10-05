# Matriz de requisitos – Taller B5-T4

Fuente: enunciado del taller (PDF). Cada fila = algo que se evalúa, cómo lo cubrimos y qué evidencia mostrar.

| # | Requisito del enunciado | Cómo lo cubrimos | Evidencia en el repo / demo | Estado |
|---|---|---|---|---|
| 1 | Grupos de 3, entrega por aula virtual antes del 8-oct 18:00 | Plan con entrega objetivo jueves 16:00 | Captura del envío | ☐ |
| 2 | Repo GitHub con código fuente del MVP funcional | Repo estructurado en capas | URL del repo | ☐ |
| 3 | **4.1** Esquema visual y descriptivo del problema, público (B2C/B2B/B2B2C) y propuesta de valor con multimodalidad | Sección “Producto” del README con diagrama; público B2B (analistas, EAFI, gestoras boutique) | `README.md` § Problema y propuesta de valor | ☐ |
| 4 | **4.1** Viabilidad técnica: costes de inferencia y consumo de APIs | Tabla de unit economics por análisis (LLM + STT + TTS + imagen) con tarifas verificadas | `README.md` § Viabilidad; módulo de coste en la app | ☐ |
| 5 | **4.1** Latencias para UX fluida | Medir y reportar latencia por paso (traza del pipeline); ejecución paralela de visión y STT | Tabla de latencias medidas | ☐ |
| 6 | **4.1** Marco regulatorio (compliance, privacidad) | MiFID II (información vs. asesoramiento), RGPD, AI Act (transparencia), disclaimers y guardrails en código | `README.md` § Compliance; `guardrails.py` + test | ☐ |
| 7 | **4.1** Modelo de monetización | Planes SaaS por volumen de análisis + API; costes vs. precio | `README.md` § Monetización | ☐ |
| 8 | **4.2** Máxima diversidad de modalidades de entrada y salida con coherencia | Entrada: PDF, imagen de gráfico, audio, texto. Salida: informe, audio (TTS), infografía, chat | Demo mostrando las 4+3 modalidades | ☐ |
| 9 | **4.2** Orquestación de múltiples modelos especializados (no un único modelo monolítico) | LLM de razonamiento + modelo de visión + Whisper (STT) + TTS + modelo de imagen + recuperación TF-IDF/embeddings, encadenados | Diagrama de arquitectura + traza por paso en la UI | ☐ |
| 10 | **4.3** Aplicación operativa real | App Streamlit funcional de extremo a extremo | Demo | ☐ |
| 11 | **4.3** UI/UX, navegación clara, robustez | Pestañas, estados de carga, errores amigables, fallback | Capturas; prueba con entradas inválidas | ☐ |
| 12 | **4.3** Plug-and-play: scripts de arranque y dependencias | `requirements.txt`, `Dockerfile`, `run.sh`/`run.bat`, `.env.example`, modo demo sin claves | Probado en máquina limpia | ☐ |
| 13 | **4.4** README exhaustivo con capturas, diagrama de flujo multimodal y arquitectura | `04_README_BORRADOR.md` completado | `README.md` | ☐ |
| 14 | **4.4** “Pitch Deck técnico” | Sección de pitch en README (o 5–6 diapositivas opcionales) | `docs/pitch.md` o PDF | ☐ |
| 15 | **4.4** Modularidad: separar capa de modelos IA, lógica de negocio e interfaz | `providers/` (IA) · `domain/` (negocio) · `orchestration/` · `ui/` | Estructura del repo | ☐ |
| 16 | **5.2** Demo funcional: desplegada o grabada/en vivo, evidenciando usabilidad e integración real de modalidades | Vídeo 3–5 min con APIs reales + (opcional) despliegue | Enlace en README | ☐ |

## Qué maximiza la nota (según el enunciado)
1. **Más modalidades con sentido** (filas 8–9): no añadir por añadir; cada una tiene que servir al flujo del analista.
2. **Orquestación visible**: mostrar la traza de pasos y modelos en la UI. Es la evidencia más directa del criterio 4.2.
3. **Plug-and-play** (fila 12): un profesor que clona y falla al arrancar pierde puntos de MVP; el modo demo lo evita.
4. **Viabilidad con números reales** (filas 4–5): costes y latencias medidos, no inventados.

## Fuera de alcance (declarar como hoja de ruta)
Vídeo-análisis, búsqueda multimodal con CLIP, conexión a datos bancarios (PSD2), autenticación y multiusuario.
