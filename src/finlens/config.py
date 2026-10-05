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

    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")

    # Nombres de modelo. VERIFICAR en la documentación oficial de cada proveedor.
    llm_model: str = "claude-sonnet-5-5"
    vision_model: str = "claude-sonnet-5-5"
    stt_model: str = "whisper-1"
    tts_model: str = "tts-1"
    tts_voice: str = "alloy"
    image_model: str = "gpt-image-1"

    # Ajustes de las llamadas reales. El esfuerzo controla la profundidad de razonamiento del LLM
    # (low|medium|high|xhigh|max; vacío = no enviarlo, p.ej. con modelos que no lo admiten).
    llm_effort: str = "medium"
    # Si es True, Anthropic reintenta en otro modelo cuando rechaza una petición (API beta).
    llm_refusal_fallback: bool = False
    image_size: str = "1024x1024"
    image_quality: str = "medium"

    # Límite de texto que se ingiere del PDF (palanca de coste).
    max_pdf_chars: int = 300_000

    # Tarifas orientativas en USD. VERIFICAR en las páginas oficiales de precios.
    price_llm_input_per_mtok: float = 2.0
    price_llm_output_per_mtok: float = 10.0
    price_stt_per_minute: float = 0.006
    price_tts_per_mchar: float = 15.0
    price_image_per_unit: float = 0.04

    @property
    def has_anthropic_key(self) -> bool:
        return bool(self.anthropic_api_key.get_secret_value().strip())

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key.get_secret_value().strip())

    @property
    def demo_reason(self) -> str | None:
        """Motivo por el que se activa el modo demo, o None si se usan las APIs reales."""
        if self.demo_mode:
            return "DEMO_MODE está activado."
        faltan = [
            nombre
            for nombre, hay in (
                ("ANTHROPIC_API_KEY", self.has_anthropic_key),
                ("OPENAI_API_KEY", self.has_openai_key),
            )
            if not hay
        ]
        if faltan:
            return f"Falta la clave API: {', '.join(faltan)}."
        return None

    @property
    def is_demo(self) -> bool:
        """True si debe usarse el modo demo (proveedores simulados)."""
        return self.demo_reason is not None


@lru_cache
def get_settings() -> Settings:
    """Devuelve los ajustes de la aplicación (se cargan una sola vez)."""
    return Settings()
