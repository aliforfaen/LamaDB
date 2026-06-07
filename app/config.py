"""Application configuration from environment variables."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    database_url: str = "postgresql://lamadb:lamadb_secret@localhost:5432/lamadb"
    api_key_salt: str = "change-me-in-production"
    cors_origins: str = "http://localhost:3000,http://localhost:8080"

    # FreshRSS GReader API
    freshrss_url: str = ""
    freshrss_username: str = ""
    freshrss_api_password: str = ""

    # ntfy notifications
    ntfy_url: str = "https://ntfy.notflix.no"
    ntfy_topic: str = "hermes-worker"

    # Dozzle log viewer
    dozzle_url: str = ""

    # Wiki filesystem path (mounted from host)
    wiki_path: str = "/wiki"

    # Telegram bot token for notifications
    telegram_bot_token: str = ""

    # Uptime Kuma API
    uptime_kuma_url: str = ""
    uptime_kuma_api_key: str = ""
    uptime_kuma_user: str = ""
    uptime_kuma_password: str = ""

    # Notflix module — Sonarr/Radarr/Tautulli
    sonarr_url: str = ""
    sonarr_api_key: str = ""
    radarr_url: str = ""
    radarr_api_key: str = ""
    tautulli_url: str = ""
    tautulli_api_key: str = ""

    # Hermes Agent API
    hermes_url: str = ""
    hermes_api_key: str = ""
    hermes_dashboard_session_token: str = ""


settings = Settings()
