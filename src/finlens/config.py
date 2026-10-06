"""Configuración de FinLens a partir de variables de entorno (ver .env.example)."""
from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes de la aplicación. Cada campo se lee de la variable de entorno homónima."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Modo demo: si es True (o faltan claves) se usan proveedores simulados.
    demo_mode: bool = False

    openrouter_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")

    # Proveedor por capacidad: auto | openrouter | anthropic | openai | mock.
    # auto = OpenRouter si hay su clave; si no, el proveedor nativo si hay su clave; si no, mock.
    llm_provider: str = "auto"
    vision_provider: str = "auto"
    stt_provider: str = "auto"
    tts_provider: str = "auto"
    image_provider: str = "auto"
    embeddings_provider: str = "auto"

    # Modelos para OpenRouter (slugs del catálogo https://openrouter.ai/api/v1/models).
    openrouter_llm_model: str = "anthropic/claude-sonnet-5.5"
    openrouter_vision_model: str = "google/gemini-3.8-flash"
    openrouter_stt_model: str = "openai/whisper-large-v3-turbo"
    openrouter_tts_model: str = "hexgrad/kokoro-82m"
    openrouter_tts_voice: str = "ef_dora"
    openrouter_image_model: str = "black-forest-labs/flux.2-klein-4b"
    openrouter_embeddings_model: str = "baai/bge-m3"
    # Razonamiento obligatorio en algunos modelos de OpenRouter: sus tokens cuentan contra max_tokens.
    # Esfuerzo enviado como reasoning.effort (vacío = no enviarlo) y mínimo de max_tokens.
    openrouter_reasoning_effort: str = "low"
    openrouter_min_output_tokens: int = 4000
    # Idioma de la transcripción (ISO-639-1); vacío = autodetección.
    stt_language: str = ""
    # Modelo de respaldo si la transcripción parece truncada (vacío = sin respaldo).
    openrouter_stt_fallback_model: str = "openai/gpt-4o-mini-transcribe"

    # Nombres de modelo. VERIFICAR en la documentación oficial de cada proveedor.
    llm_model: str = "claude-sonnet-5-5"
    vision_model: str = "claude-sonnet-5-5"
    stt_model: str = "whisper-1"
    tts_model: str = "tts-1"
    tts_voice: str = "alloy"
    image_model: str = "gpt-image-1"
    embeddings_model: str = "text-embedding-3-small"

    # Ajustes de las llamadas reales. El esfuerzo controla la profundidad de razonamiento del LLM
    # (low|medium|high|xhigh|max; vacío = no enviarlo, p.ej. con modelos que no lo admiten).
    llm_effort: str = "medium"
    # Si es True, Anthropic reintenta en otro modelo cuando rechaza una petición (API beta).
    llm_refusal_fallback: bool = False
    # Mínimo de max_tokens que se envía a Anthropic nativo: allí el pensamiento comparte presupuesto
    # con la respuesta y un límite bajo corta el JSON. No se aplica a OpenRouter.
    llm_min_output_tokens: int = 4000
    image_size: str = "1024x1024"
    image_quality: str = "medium"

    # Nivel de logging del logger `finlens` (DEBUG|INFO|WARNING|ERROR).
    log_level: str = "INFO"

    # Límite de texto que se ingiere del PDF (palanca de coste).
    max_pdf_chars: int = 300_000

    # Tarifas orientativas en USD. VERIFICAR en las páginas oficiales de precios.
    price_llm_input_per_mtok: float = 2.0
    price_llm_output_per_mtok: float = 10.0
    price_stt_per_minute: float = 0.006
    price_tts_per_mchar: float = 15.0
    price_image_per_unit: float = 0.04
    price_embeddings_per_mtok: float = 0.02
    # TTS vía OpenRouter no informa del coste: tarifa por defecto de hexgrad/kokoro-82m según el
    # catálogo de OpenRouter (0,62 USD por millón de caracteres). VERIFICAR si cambias de modelo.
    openrouter_price_tts_per_mchar: float = 0.62

    @property
    def has_openrouter_key(self) -> bool:
        return bool(self.openrouter_api_key.get_secret_value().strip())

    @property
    def has_anthropic_key(self) -> bool:
        return bool(self.anthropic_api_key.get_secret_value().strip())

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key.get_secret_value().strip())

    @property
    def effective_price_tts_per_mchar(self) -> float:
        """Tarifa TTS según el backend previsible: OpenRouter (kokoro) o la de OpenAI configurada."""
        pedido = self.tts_provider.strip().lower()
        if not self.demo_mode and pedido in ("auto", "openrouter") and self.has_openrouter_key:
            return self.openrouter_price_tts_per_mchar
        return self.price_tts_per_mchar

    @property
    def demo_reason(self) -> str | None:
        """Motivo por el que no hay ninguna API real, o None si alguna capacidad puede usarla.

        El registro decide por capacidad (ver `providers.registry`); esto solo cubre el caso en
        que todo sería simulado.
        """
        if self.demo_mode:
            return "DEMO_MODE está activado."
        if self.has_openrouter_key or self.has_anthropic_key or self.has_openai_key:
            return None
        return "Falta la clave API: OPENROUTER_API_KEY (o ANTHROPIC_API_KEY y OPENAI_API_KEY)."

    @property
    def is_demo(self) -> bool:
        """True si todo sería simulado (sin claves o con DEMO_MODE)."""
        return self.demo_reason is not None


@lru_cache
def get_settings() -> Settings:
    """Devuelve los ajustes de la aplicación (se cargan una sola vez)."""
    return Settings()
