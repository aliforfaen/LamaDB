"""Application configuration from environment variables."""
import asyncio
import json
from pathlib import Path as _Path
from typing import Any

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

    # Home Assistant integration
    homeassistant_url: str = ""
    homeassistant_token: str = ""
    homeassistant_highlight_entities: str = ""



    # Wiki — CouchDB-backed LiveSync collector
    wiki_couchdb_url: str = ""
    wiki_couchdb_db: str = ""
    wiki_couchdb_user: str = ""
    wiki_couchdb_password: str = ""
    wiki_couchdb_encryption_key: str = ""  # LiveSync E2EE passphrase
    wiki_sync_interval: int = 900    # seconds, safety-net full re-sync


settings = Settings()


# ---------------------------------------------------------------------------
# Per-module settings engine
# ---------------------------------------------------------------------------

SETTINGS_FILE = _Path(__file__).parent.parent / "settings.json"


async def _load_settings_file() -> dict:
    """Load settings.json overlay file. Returns empty dict if missing.

    File I/O is offloaded to a thread to keep the event loop responsive
    when called from async route handlers.
    """
    if SETTINGS_FILE.exists():
        try:
            raw = await asyncio.to_thread(SETTINGS_FILE.read_text)
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


async def discover_module_configs() -> dict[str, dict]:
    """Walk all modules and collect MODULE_CONFIG_SCHEMA declarations."""
    modules_dir = _Path(__file__).parent.parent / "modules"
    result = {}
    if not modules_dir.exists():
        return result

    settings_overlay = await _load_settings_file()

    for item in sorted(modules_dir.iterdir()):
        if not item.is_dir() or not (item / "__init__.py").exists():
            continue
        try:
            mod = __import__(f"modules.{item.name}", fromlist=["MODULE_CONFIG_SCHEMA", "ENABLED"])
            schema = getattr(mod, "MODULE_CONFIG_SCHEMA", None)
            if not schema:
                continue

            values = {}
            for key, field in schema.items():
                env_name = field.get("env", key.upper())
                env_val = getattr(settings, env_name.lower(), None) if hasattr(settings, env_name.lower()) else None
                file_val = settings_overlay.get(item.name, {}).get(key)
                resolved = env_val if env_val else file_val if file_val else field.get("default", "")
                display_val = "***" if field.get("type") == "secret" and resolved else resolved
                values[key] = {
                    "value": resolved,
                    "display": display_val,
                    "source": "env" if env_val else "file" if file_val else "default",
                    "restart_required": field.get("restart_required", True),
                }

            result[item.name] = {
                "enabled": getattr(mod, "ENABLED", False),
                "schema": schema,
                "values": values,
            }
        except Exception:
            pass

    return result


async def save_settings(module_name: str, key_values: dict) -> bool:
    """Save settings for a module to settings.json. Returns True if restart needed.

    File I/O (both read and write) is offloaded to a thread to keep the
    event loop responsive.
    """
    settings_overlay = await _load_settings_file()
    if module_name not in settings_overlay:
        settings_overlay[module_name] = {}

    restart_needed = False
    schemas = await discover_module_configs()
    module_schema = schemas.get(module_name, {}).get("schema", {})

    for key, value in key_values.items():
        field = module_schema.get(key, {})
        expected_type = field.get("type", "str")
        try:
            if expected_type == "int":
                value = int(value)
            elif expected_type == "bool":
                value = bool(value)
            elif expected_type == "str":
                value = str(value)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid {expected_type} value for '{key}': {value}")

        settings_overlay[module_name][key] = value
        if field.get("restart_required", True):
            restart_needed = True

    payload = json.dumps(settings_overlay, indent=2)
    await asyncio.to_thread(SETTINGS_FILE.write_text, payload)
    return restart_needed
