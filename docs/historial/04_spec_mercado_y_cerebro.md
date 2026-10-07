# 06 · Spec ronda 3: datos de mercado reales + "cerebro" animado

Continúa `03_spec_openrouter_y_calidad.md` (sus reglas §0 aplican igual: cero alucinaciones, estilo del repo, capas,
nunca leer `.env`, tests sin red).

## 10. Datos de mercado reales y verificación cruzada visión ↔ datos

Valor de negocio: hoy el usuario tiene que traer el gráfico. Con un **ticker** FinLens se baja los datos
(acciones vía Yahoo Finance, cripto vía Hyperliquid, fundamentales oficiales de EE. UU. vía SEC EDGAR XBRL),
dibuja el gráfico, se lo da al **modelo de visión** y luego **contrasta lo que "ve" el modelo con los números
calculados en Python** (detector de alucinaciones visuales). Además el LLM recibe métricas de mercado
verificables como 4ª fuente citada (`origin="mercado"`) y los fundamentales oficiales SEC como 5ª
(`origin="sec"`), que sirven también para verificar cifras.

### 10.1 APIs (VERIFICADAS en vivo el 2026-10-06; sin clave)

**Yahoo Finance (no oficial)**: `GET https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}?range=6mo&interval=1d`
con cabecera `User-Agent: Mozilla/5.0`. Respuesta: `chart.result[0].meta` (currency, symbol,
regularMarketPrice, fiftyTwoWeekHigh, fiftyTwoWeekLow, exchangeName…), `timestamp[]`,
`indicators.quote[0].{open,high,low,close,volume}[]` (puede haber `null`: descartar esas velas).
`chart.error` no nulo → símbolo inválido. Ejemplos: `ITX.MC`, `SAN.MC`, `AAPL`.
Es API no oficial: documentarlo como riesgo (en producción, proveedor con licencia, p.ej. BME Market Data).

**Hyperliquid** (perp DEX on-chain, API pública): `POST https://api.hyperliquid.xyz/info`, cuerpo JSON:
- `{"type":"candleSnapshot","req":{"coin":"BTC","interval":"1d","startTime":<ms>,"endTime":<ms>}}` →
  lista de `{t,T,s,i,o,c,h,l,v,n}`; o/c/h/l/v vienen como **strings**.
- `{"type":"metaAndAssetCtxs"}` → `[meta, ctxs]`; `meta.universe[i].name` se alinea con `ctxs[i]`, que trae
  `funding` (tasa horaria, string), `openInterest` (unidades del activo), `markPx`, `oraclePx`, `prevDayPx`,
  `dayNtlVlm` (volumen nocional 24 h en USD), `premium`.
- `{"type":"fundingHistory","coin":"ETH","startTime":<ms>}` → `[{coin,fundingRate,premium,time}]`.
Funding anualizado = tasa horaria × 24 × 365.

**SEC EDGAR** (datos públicos del Gobierno de EE. UU.): cabecera obligatoria
`User-Agent: FinLens academic project <email>` (configurable con `SEC_USER_AGENT`).
- `GET https://www.sec.gov/files/company_tickers.json` → `{"0":{"cik_str":320193,"ticker":"AAPL","title":"Apple Inc."},...}`.
- `GET https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json` → `facts["us-gaap"][TAG]["units"]["USD"]`
  = lista de `{start,end,val,fy,fp,form,filed,frame}`. Usar sólo `form=="10-K"`, `fp=="FY"` y periodo ≈ 1 año
  (end − start > 300 días; los saldos de balance no tienen `start`: aceptarlos por `end`). Ingresos: probar
  `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, `SalesRevenueNet` y quedarse con el dato
  **más reciente** (en AAPL `Revenues` sólo llega a 2018). Otros: `NetIncomeLoss`, `GrossProfit`,
  `OperatingIncomeLoss`, `Assets`, `Liabilities`, `StockholdersEquity`, `NetCashProvidedByUsedInOperatingActivities`.
  Últimos 3 ejercicios, deduplicados por `end`. Sólo empresas que reportan a la SEC; para el resto se omite sin error.

### 10.2 Arquitectura

- Nuevo paquete `src/finlens/sources/` (conectores de datos externos, NO IA; capa hermana de `providers/`):
  - `base.py`: Protocols + dataclasses frozen `Candle(t: datetime, o, h, l, c, v: float)`,
    `PriceSeries(symbol, currency, source, candles: tuple[Candle, ...], meta: dict)`,
    `DerivativesSnapshot(funding_hourly, funding_annualized, open_interest, mark_px, oracle_px,
    day_notional_volume, prev_day_px)`, `FundamentalFact(tag, label_es, value, unit, fy, end, form, accn)`,
    `Fundamentals(company, cik, facts: tuple[FundamentalFact, ...])`, `SourceError`.
  - `yahoo.py`, `hyperliquid.py`, `sec_edgar.py`: `httpx`, timeout 20 s, cliente inyectable para tests,
    caché en memoria del mapa de tickers SEC.
  - `registry.py`: `resolve_market(ticker) -> "cripto" | "accion"` (cripto si el símbolo está en el universo de
    Hyperliquid, comprobado con `metaAndAssetCtxs` y cacheado; si no, acción). Mock determinista
    (serie sintética reproducible) para demo y tests.
  - Tests con respuestas JSON reales grabadas UNA vez en `tests/fixtures/` (recortadas); sin red en tests.
  - `tests/test_arquitectura.py`: `domain/` no importa `finlens.sources` ni `httpx`; `sources/` no importa SDKs de IA.
- `domain/technicals.py` (puro, numpy): SMA20/50, EMA, RSI14 (Wilder), volatilidad anualizada (√252 acciones,
  √365 cripto), máximo drawdown, rango del periodo (mín/máx con fechas), rentabilidad del periodo, tendencia
  determinista `alcista|bajista|lateral` (pendiente de la regresión del cierre normalizada + posición frente a
  SMA50; umbrales documentados como constantes), soportes/resistencias por pivotes locales.
  `TechnicalSummary` dataclass. Tests con series sintéticas de resultado conocido.
- `domain/market_chart.py`: velas + volumen + SMA20/50 desde `PriceSeries` con matplotlib (Figure +
  FigureCanvasAgg, thread-safe), 1400×900, PNG bytes, estilo coherente con el bloque ESTILO de `infographic.py`.
  **Sin** anotar valores numéricos de indicadores (para que el contraste visión↔datos sea honesto); sí ejes
  con precios y fechas y título con símbolo, fuente y rango.
- `domain/chart_check.py`: `check_chart_reading(reading: ChartReading, tech: TechnicalSummary) -> ChartCheck`.
  Veredictos por afirmación: tendencia (coincide o no), niveles de precio citados por la visión dentro de
  [mín·0,97, máx·1,03] del periodo, soportes/resistencias citados frente a pivotes (±3 %).
  `ChartCheck(agreement_score: float 0..1, items: tuple[ChartCheckItem(claim, verdict: "confirmada" | "discrepa"
  | "no_verificable", detail)])`. Funciona también con gráficos subidos por el usuario si hay ticker.
- Esquema: `Origin` añade `"mercado"` y `"sec"`. Prompts: bloques `<mercado>` (resumen técnico + derivados si
  cripto) y `<sec>` (fundamentales) con la regla de citarlos como `mercado` / `sec`.
- Grounding: `KeyFigure` citada a `sec` se verifica contra `Fundamentals` (equivalencia de escala §9.2 de la spec 05);
  citada a `mercado`, contra `TechnicalSummary` / `DerivativesSnapshot` (tolerancia 1 %).

### 10.3 Integración en el pipeline

- `AnalysisInput` gana `ticker: str = ""` y `market_range: str = "6mo"`. Vale **PDF o ticker** (al menos uno);
  sin PDF se omiten ingesta y recuperación y el análisis trabaja con mercado (+ SEC + audio).
- Fase 1 en paralelo: [ingesta + embeddings] ‖ [datos de mercado → técnicos → gráfico generado si no se subió
  uno → visión → contraste] ‖ [STT] ‖ [SEC si es acción con CIK]. Pasos de traza: "Datos de mercado (Yahoo |
  Hyperliquid)", "Indicadores técnicos", "Gráfico generado", "Fundamentales SEC", "Contraste visión ↔ datos".
- `AnalysisResult` gana `market: MarketContext | None` (serie, técnicos, derivados, fundamentales,
  chart_check, chart_png generado). Fallos de fuentes → warning y se sigue (degradación).
- Mock/demo: fuentes simuladas para que la demo completa funcione sin red.

## 11. UI: "cerebro" animado (red neuronal de modelos)

Referencia (reel visto por el PM): red neuronal en **3D con perspectiva**, una **placa de cristal translúcida
por capa** con cabecera mono ("Layer 2 · Neurons: 13 · Activation: Sigmoid"), nodos blancos pequeños en
columna con etiqueta y valor numérico al lado, **cientos de conexiones finas blancas semitransparentes** entre
capas, **salida ganadora resaltada en amarillo**, suelo de **rejilla en perspectiva**, cámara en travelling
lento a través de las capas, fondo azul petróleo oscuro.

Adaptación FinLens:
- Capa de entrada = modalidades (PDF, Gráfico, Audio, Pregunta, Ticker/Mercado, SEC). Capas ocultas = modelos
  reales (embeddings, visión, STT, LLM analista, guardrails, verificador, TTS, imagen) con su slug. Capa de
  salida = entregables (Informe citado, Cifras verificadas, Contraste visión↔datos, Audio, Infografía, Chat).
- **Dependiente de la tarea**: sólo se encienden las entradas aportadas y los modelos usados en la traza; pulsos
  de luz viajan por las aristas en el orden real de ejecución (paralelismo visible); las salidas producidas se
  resaltan (acento latón de la UI en lugar del amarillo del reel) con su métrica (tiempo, coste, cifras verificadas).
- Three.js desde cdnjs dentro de `st.components.v1.html` (iframe), datos inyectados como JSON escapado; fallback
  Canvas 2D si WebGL o el CDN fallan; `prefers-reduced-motion` → estático. Fluido, ligero.
- Usos: (a) hero en reposo antes de analizar (la red "respira", pulsos tenues); (b) reproducción de la
  ejecución real tras analizar (y en vivo vía `on_step` cuando exista).
