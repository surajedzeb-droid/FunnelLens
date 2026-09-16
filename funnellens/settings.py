"""Loads secrets from .env (or Streamlit secrets) and settings from config/config.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_SECRETS = ("LSQ_ACCESS_KEY", "LSQ_SECRET_KEY", "LSQ_API_HOST")


class SettingsError(Exception):
    """Raised when required configuration or secrets are missing or invalid. Never includes secret values."""


def _load_secret_values() -> dict[str, str | None]:
    """Reads the three LSQ secrets from Streamlit secrets (if available) first, then from the environment/.env."""
    values: dict[str, str | None] = {}
    try:
        import streamlit as st  # type: ignore[import-not-found]

        for key in REQUIRED_SECRETS:
            if key in st.secrets:
                values[key] = str(st.secrets[key])
    except Exception:
        pass  # not running under Streamlit, or no secrets configured — fall through to .env

    load_dotenv(Path.cwd() / ".env", override=False)
    for key in REQUIRED_SECRETS:
        if key not in values:
            values[key] = os.environ.get(key)
    return values


@dataclass(frozen=True)
class Secrets:
    access_key: str
    secret_key: str
    api_host: str


@dataclass(frozen=True)
class Settings:
    secrets: Secrets
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def timezone(self) -> str:
        return self.config["timezone"]

    @property
    def fields(self) -> dict[str, str]:
        return self.config["fields"]

    @property
    def stages(self) -> list[str]:
        return self.config["stages"]

    @property
    def excluded_owner_roles(self) -> list[str]:
        return self.config["excluded_owner_roles"]

    @property
    def excluded_owner_names(self) -> list[str]:
        return self.config["excluded_owner_names"]

    @property
    def opportunity_event_code(self) -> int:
        return self.config["opportunity_event_code"]

    @property
    def api(self) -> dict[str, Any]:
        return self.config["api"]


def load_settings(config_path: Path | None = None) -> Settings:
    """Loads and validates secrets + config.yaml. Raises SettingsError (with no secret values in the message) if anything required is missing."""
    config_path = config_path or (PROJECT_ROOT / "config" / "config.yaml")

    raw_secrets = _load_secret_values()
    missing = [key for key in REQUIRED_SECRETS if not raw_secrets.get(key)]
    if missing:
        raise SettingsError(
            f"Missing required secret(s): {', '.join(missing)}. "
            f"Set them in .env (see .env.example) or in Streamlit Secrets."
        )
    secrets = Secrets(
        access_key=raw_secrets["LSQ_ACCESS_KEY"],  # type: ignore[arg-type]
        secret_key=raw_secrets["LSQ_SECRET_KEY"],  # type: ignore[arg-type]
        api_host=raw_secrets["LSQ_API_HOST"],  # type: ignore[arg-type]
    )

    if not config_path.exists():
        raise SettingsError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    required_keys = ("timezone", "fields", "stages", "excluded_owner_roles", "excluded_owner_names", "api")
    missing_keys = [key for key in required_keys if key not in config]
    if missing_keys:
        raise SettingsError(f"config.yaml is missing required key(s): {', '.join(missing_keys)}")

    return Settings(secrets=secrets, config=config)
