from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    app_secret_key: str = ""
    debug: bool = True

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/callback"

    # Fernet encryption key for stored tokens
    # Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    fernet_key: str = ""

    # Gemini
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    # Tried in order if the primary model is overloaded (503) or unavailable.
    # Lighter/older models tend to have separate capacity, so they often
    # stay up even when the flagship model is getting hammered.
    gemini_fallback_models: list[str] = ["gemini-3.5-flash-lite", "gemini-2.5-flash"]

    # DB
    database_url: str = "sqlite+aiosqlite:///./workspace_ai.db"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
