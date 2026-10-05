# Plan de 3 días – Taller B5-T4 (FinTech multimodal)

**Hoy:** lunes 5 oct 2026 · **Deadline:** jueves 8 oct 2026, 18:00 (aula virtual) · **Entregable:** repo GitHub con MVP funcional + demo (desplegada o grabada).
**Regla de oro:** congelar funcionalidades el miércoles a las 22:00. El jueves solo se pule, se graba y se entrega **antes de las 16:00** (margen de 2 h por si falla la subida o el aula).

> Roles propuestos (ajustar al grupo). A = arquitectura + orquestación; B = capa de modelos de IA + audio/imagen; C = UI + documentación + demo.

## Lunes 5 – Decisiones y esqueleto
| Qué | Quién | Hecho cuando |
|---|---|---|
| Cerrar idea, público objetivo y nombre (usar `02_SPEC_PRODUCTO.md`) | Todos (30 min) | Spec aprobada por los 3 |
| Crear repo GitHub, ramas, `.env.example`, `requirements.txt` | A | Repo clonado por todos |
| Generar esqueleto con Claude Code (`03_PROMPT_CLAUDE_CODE.md`, Fase 0–1) | A | App arranca en modo demo (mocks) |
| Obtener y probar claves API (LLM, Whisper, TTS, imagen); anotar coste | B | Una llamada real por modalidad funciona |
| Reunir 3 casos de prueba: un informe anual PDF, un gráfico de velas, un audio corto (earnings call) | C | Ficheros en `samples/` |

## Martes 6 – Núcleo multimodal
| Qué | Quién | Hecho cuando |
|---|---|---|
| Proveedores reales: LLM, visión, STT, TTS, imagen | B | Cada uno con test de humo |
| Ingesta PDF + recuperación (RAG ligero) + análisis estructurado | A | Informe JSON con fuentes citadas |
| Orquestador: ejecución en paralelo (visión + STT), trazabilidad, coste | A | Traza visible por paso |
| UI: carga de archivos, pestañas de resultados, chat de seguimiento | C | Flujo completo clicable con mocks |
| Guardrails de compliance (disclaimer, sin recomendaciones) | B | Test que detecta “compra/vende” |

## Miércoles 7 – Integración, calidad y documentación
| Qué | Quién | Hecho cuando |
|---|---|---|
| Integrar UI con pipeline real, manejo de errores y estados de carga | A + C | Flujo end-to-end con los 3 casos de prueba |
| Pruebas, limpieza de código, fallback a mocks si falta una clave | B | `pytest` en verde |
| README final: capturas, diagrama de flujo, arquitectura, viabilidad | C | README sin placeholders (`04_README_BORRADOR.md`) |
| Prueba “plug-and-play” en una máquina limpia (venv nuevo o Docker) | B | Se arranca con 1–2 comandos |
| **Congelar funcionalidades 22:00** | Todos | Tag `v1.0-entrega` |

## Jueves 8 – Entrega
| Hora | Qué |
|---|---|
| 09:00–11:00 | Correcciones críticas solamente; grabar demo (3–5 min) |
| 11:00–13:00 | Despliegue en la nube (Streamlit Community Cloud o Hugging Face Spaces) si hay tiempo; si no, la demo grabada basta |
| 13:00–15:00 | Revisión final con el checklist de `01_MATRIZ_REQUISITOS.md` |
| **≤16:00** | **Subir al aula virtual** (enlace al repo + enlace a demo). Verificar que el repo es público o que el profesor tiene acceso |
| 18:00 | Deadline duro |

## Checklist de entrega (última comprobación)
- [ ] Repo accesible para el profesor, con README completo
- [ ] `requirements.txt` y/o `Dockerfile` probados desde cero
- [ ] Script de arranque (`run.sh` / `run.bat`) o comando único documentado
- [ ] Sin claves API en el repo (solo `.env.example`); historial limpio
- [ ] Modo demo funciona sin claves
- [ ] Demo grabada o URL desplegada, enlazada en el README
- [ ] Capturas de pantalla y diagrama de flujo en el README
- [ ] Enlace entregado en el aula virtual antes de las 16:00

## Riesgos y mitigaciones
- **Falla una API el último día:** modo demo con mocks + demo grabada con las APIs reales.
- **Costes descontrolados:** límite de longitud de entrada, caché, `cost.py` por ejecución.
- **Scope creep:** una sola vertical (análisis de informes), 3 entradas y 3 salidas. Todo lo demás va a “hoja de ruta” del README.
- **Conflictos de Git:** módulos separados por persona; PRs pequeñas; main protegida.
