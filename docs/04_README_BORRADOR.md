# FinLens – Análisis multimodal de informes financieros

> Taller B5-T4 · Máster en IA y computación cuantitativa aplicada a mercados financieros (Instituto BME)
> Equipo: <Nombre 1>, <Nombre 2>, <Nombre 3> · Entrega: 8 de octubre de 2026

**Demo:** <enlace a la app desplegada> · **Vídeo:** <enlace a la grabación>

![Captura principal](docs/img/home.png)

## 1. Problema y propuesta de valor
<Describir en 4–6 líneas el problema del analista: informes en PDF, gráficos y conferencias de resultados en audio, todo disperso.>

**Público objetivo (B2B):** <analistas, EAFI, gestoras boutique…>
**Propuesta de valor multimodal:** <qué aporta cruzar texto, imagen y voz frente a un chat con un único modelo.>

![Esquema del producto](docs/img/esquema_producto.png)

## 2. Qué hace (demo en 30 segundos)
1. Subes un informe anual (PDF), el gráfico de cotización y el audio de la conferencia de resultados.
2. Preguntas por texto o por voz.
3. Obtienes un informe con cifras **citadas**, la lectura del gráfico, un resumen en **audio** y una **infografía**.
4. Puedes seguir preguntando en el chat.

| Entradas | Salidas |
|---|---|
| PDF · imagen de gráfico · audio · texto | Informe estructurado · audio TTS · infografía · chat |

## 3. Arquitectura y flujo de datos multimodal
<Pegar el diagrama mermaid de docs/02_SPEC_PRODUCTO.md o una imagen exportada.>

| Modalidad | Modelo | Proveedor | Rol |
|---|---|---|---|
| Texto→texto | <modelo> | Anthropic | Análisis y síntesis |
| Imagen→texto | <modelo> | Anthropic | Lectura del gráfico |
| Voz→texto | <modelo> | OpenAI | Transcripción |
| Texto→voz | <modelo> | OpenAI | Resumen en audio |
| Texto→imagen | <modelo> | OpenAI | Infografía |
| Recuperación | TF-IDF | Local | Selección de fragmentos del PDF |

**Capas:** `providers/` (conexión con modelos) · `domain/` (lógica de negocio) · `orchestration/` (encadenado, paralelismo, traza) · `ui/` (Streamlit).
**Decisiones de diseño:** <modo demo con mocks, JSON validado con Pydantic, degradación elegante, guardrails…>

## 4. Instalación y ejecución (plug-and-play)
```bash
git clone <url-del-repo> && cd finlens
cp .env.example .env        # opcional: sin claves arranca en modo demo
./run.sh                    # Windows: run.bat
```
**Docker:** `docker build -t finlens . && docker run -p 8501:8501 --env-file .env finlens`
**Variables:** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEMO_MODE`, nombres de modelo (ver `.env.example`).
**Tests:** `pytest`

## 5. Viabilidad técnica y económica
**Coste por análisis (medido con `scripts/medir.py`, media de N casos):**

| Componente | Uso medio | Coste |
|---|---|---|
| LLM (tokens in/out) | <…> | <…> € |
| STT | <min> | <…> € |
| TTS | <caracteres> | <…> € |
| Imagen | 1 | <…> € |
| **Total** | | **<…> €** |

**Latencias medidas:** ingesta <…> s · visión <…> s · STT <…> s · análisis <…> s · TTS <…> s · imagen <…> s · **total <…> s** (visión y STT en paralelo; TTS e imagen se cargan después).
**Palancas de coste:** recuperación en lugar del PDF completo, caché por hash, límites de entrada, modelos pequeños para tareas simples.

## 6. Compliance y privacidad
- **MiFID II / CNMV:** informa, no asesora; guardrail que detecta lenguaje de recomendación y disclaimer en cada salida.
- **RGPD:** sin almacenamiento de documentos; procesamiento por sesión; <proveedores y residencia de datos en producción>.
- **AI Act:** transparencia de contenido generado por IA y citación de fuentes.
- **Datos bancarios (PSD2):** fuera del MVP.

## 7. Monetización
<Planes Free / Pro / Team-API, precio, margen frente al coste por análisis de la sección 5.>

## 8. Pitch técnico
<Problema → solución → por qué multimodal → arquitectura → tracción potencial → hoja de ruta. 5–6 líneas o enlace a docs/pitch.pdf.>

## 9. Capturas
| Informe | Traza de modelos | Infografía |
|---|---|---|
| ![](docs/img/informe.png) | ![](docs/img/traza.png) | ![](docs/img/infografia.png) |

## 10. Limitaciones y hoja de ruta
<Vídeo-análisis de webinars, búsqueda multimodal con CLIP, conexión a datos de mercado en tiempo real, multiusuario y autenticación, evaluación sistemática de precisión.>

## 11. Estructura del repositorio
<Pegar el árbol de carpetas actualizado.>

## Aviso legal
Información generada con IA con fines informativos. No constituye asesoramiento en materia de inversión.
