# Guion del vídeo de demostración (4 min)

Grabar con APIs reales (demo en AWS o `run.bat` con `OPENROUTER_API_KEY`). Pantalla a 1280×800 o más, zoom del
navegador al 90 %. Graba voz en off por bloques; los análisis tardan ~30 s: deja que se vea el mapa vivo y
corta en edición si hace falta. Coste total de la grabación: < 1 USD.

| Tiempo | Pantalla | Qué decir (idea, no literal) |
|---|---|---|
| 0:00–0:20 | Portada de FinLens con el **cerebro 3D** en reposo | «Un analista cruza a mano el informe anual, el gráfico, la conferencia de resultados y los datos de mercado, y la IA genérica inventa cifras. FinLens lo hace en 30 segundos y verifica cada número.» |
| 0:20–0:40 | Barra de proveedores (6 modelos REAL) | «Seis modelos especializados vía OpenRouter: Claude analiza, Gemini lee el gráfico, Whisper transcribe, Kokoro habla, Flux ilustra y bge-m3 busca en varios idiomas.» |
| 0:40–1:00 | **Caso 1**: subir `samples/01_inditex` (PDF, gráfico, audio) + ticker `ITX.MC`; pulsar Analizar | «Informe anual real de Inditex, en inglés; preguntamos en español.» |
| 1:00–1:30 | **Mapa de la cadena** en vivo: ramas paralelas encendiéndose | «Visión, transcripción, embeddings y datos de mercado van en paralelo.» |
| 1:30–2:15 | **Nota de análisis**: cifras con sello «VERIFICADA p.5 · 39,864», correlaciones, contradicciones | «Cada cifra cita su página y Python comprueba que está ahí. Si el modelo se inventa una, sale en rojo.» |
| 2:15–2:45 | Pestaña **Mercado**: «La IA vio · los datos dicen» | «El modelo de visión dice ver soportes y tendencia; lo contrastamos con la serie real de precios. Es un detector de alucinaciones visuales.» |
| 2:45–3:05 | **Audio** (reproducir 5 s) e **infografía** | «Resumen hablado con aviso legal; la infografía la ilustra un modelo de difusión, pero las cifras las dibuja Python.» |
| 3:05–3:25 | **Chat**: «¿Qué dijo la dirección sobre el margen bruto en 2026?» | «El chat reutiliza el índice y cita fuentes.» |
| 3:25–3:45 | **Caso 2**: solo ticker `BTC` (sin PDF) | «Sin documentos: datos on-chain de Hyperliquid, funding y open interest, verificados.» |
| 3:45–4:00 | Pestaña **Traza** (Gantt, coste) + cerebro reproduciendo la ejecución | «0,06 dólares y 31 segundos por análisis, medidos. Compliance por diseño: informa, no asesora. Desplegado en AWS con CI/CD.» |

Comprobaciones antes de grabar: que la barra de proveedores no muestre ninguna capacidad «SIM»; que no haya
avisos de cuota en OpenRouter; probar una vez el caso 1 para calentar la caché del navegador.
