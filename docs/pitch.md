# FinLens · Pitch técnico

> Seis diapositivas en texto. Pásalas a un PDF o a diapositivas si el aula virtual lo pide.
> Las cifras marcadas **[PENDIENTE]** salen de `python scripts/medir.py` con claves reales.

---

## 1. El problema

El analista financiero trabaja con **tres fuentes que nada conecta**: el informe anual en PDF, el gráfico de
cotización y la conferencia de resultados en audio. Leer, interpretar y escuchar son tres tareas manuales, y
lo valioso —¿lo que dice la dirección encaja con las cifras y con el mercado?— no queda ni trazado ni citado.

**Público:** analistas junior y *sell-side*, EAFI, gestoras boutique, relación con inversores (B2B);
brokers (B2B2C).

## 2. La solución

**FinLens convierte esos tres materiales en un análisis estructurado y citado en minutos.**
Una consulta → cifras con fuente (`documento p.3`), lectura del gráfico, declaraciones de la dirección y su
correlación; además, resumen en audio, infografía y chat de seguimiento.

*Demo:* PDF + gráfico + audio → informe con citas → traza de modelos.

## 3. Por qué multimodal (y no «un chat con un PDF»)

Ningún modelo único hace todo el trabajo. Cada paso lo resuelve un **modelo especializado**:

| Paso | Modelo |
|---|---|
| Recuperación en el PDF | TF-IDF local (coste 0) |
| Lectura del gráfico | Claude (visión) |
| Transcripción | Whisper |
| Análisis y chat | Claude |
| Resumen en audio | OpenAI TTS |
| Infografía | OpenAI imagen |

El valor diferencial es la **correlación entre modalidades**, con trazabilidad por paso visible en la UI.

## 4. Arquitectura

Capas separadas y modelos **intercambiables**: `providers/` (IA) · `domain/` (negocio) ·
`orchestration/` · `ui/`. Un test hace cumplir que ningún SDK se importa fuera de `providers/`.

Visión y STT **en paralelo**; el informe llega primero y el audio y la infografía después.
Modo demo con *mocks*: la app siempre arranca. Degradación elegante: si falla un paso opcional, el informe se
entrega igualmente.

## 5. Viabilidad y negocio

- **Coste por análisis:** **[PENDIENTE]** USD (medido). **Latencia hasta el informe:** **[PENDIENTE]** s.
- **Compliance por diseño:** informa, no asesora; guardrail determinista contra lenguaje de recomendación y
  *disclaimer* en todas las salidas (MiFID II / CNMV); sin almacenar documentos (RGPD); contenido marcado como
  IA y citado (AI Act).
- **Monetización:** SaaS B2B por volumen — Free · Pro (por analista) · Team/API (por uso). Margen = precio −
  coste medio × análisis incluidos.

## 6. Tracción potencial y hoja de ruta

**Tracción:** equipos de research de boutiques y EAFI que hoy hacen este cruce a mano; integración con
plataformas de brokers.

**Hoja de ruta:** vídeo-análisis de webinars · búsqueda multimodal (CLIP) · datos de mercado en tiempo real ·
multiusuario y autenticación · OCR · evaluación sistemática de precisión · *embeddings* en lugar de TF-IDF.
