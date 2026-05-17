"""All configuration comes from environment variables — documented in the repo README.

Nothing here hardcodes a deployment URL. Anything optional degrades to an honest
"not configured" state surfaced by the UI, never to fabricated data.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


@dataclass
class Settings:
    # --- service
    port: int = field(default_factory=lambda: _env_int("PORT", 4601))
    public_base_url: str = field(default_factory=lambda: _env("PUBLIC_BASE_URL"))

    # --- Dynatrace (demo tenant)
    dt_environment: str = field(default_factory=lambda: _env("DT_ENVIRONMENT").rstrip("/"))
    dt_platform_token: str = field(default_factory=lambda: _env("DT_PLATFORM_TOKEN"))
    dt_api_token: str = field(default_factory=lambda: _env("DT_API_TOKEN"))

    # --- Google Cloud / Vertex
    gcp_project: str = field(default_factory=lambda: _env("GOOGLE_CLOUD_PROJECT"))
    gcp_location: str = field(default_factory=lambda: _env("GOOGLE_CLOUD_LOCATION", "global"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-3-flash-preview"))

    # --- GitHub
    github_repo: str = field(default_factory=lambda: _env("GITHUB_REPO"))
    github_token: str = field(default_factory=lambda: _env("GITHUB_TOKEN"))
    github_app_id: str = field(default_factory=lambda: _env("GITHUB_APP_ID"))
    github_app_private_key_b64: str = field(default_factory=lambda: _env("GITHUB_APP_PRIVATE_KEY_B64"))
    github_app_installation_id: str = field(default_factory=lambda: _env("GITHUB_APP_INSTALLATION_ID"))

    # --- persistence / secrets
    store_backend: str = field(default_factory=lambda: _env("STORE"))
    firestore_database: str = field(default_factory=lambda: _env("FIRESTORE_DATABASE", "(default)"))
    secrets_backend: str = field(default_factory=lambda: _env("SECRETS_BACKEND"))

    # --- shop / demo
    shop_url: str = field(default_factory=lambda: _env("SHOP_URL").rstrip("/"))
    demo_service_name: str = field(default_factory=lambda: _env("DEMO_SERVICE_NAME", "loose-threads-shop"))

    # --- cadences & budgets (mirrored by the Settings page defaults)
    poll_seconds: int = field(default_factory=lambda: _env_int("POLL_SECONDS", 30))
    cooldown_seconds: int = field(default_factory=lambda: _env_int("COOLDOWN_SECONDS", 180))
    needle_lapse_seconds: int = field(default_factory=lambda: _env_int("NEEDLE_LAPSE_SECONDS", 90))
    approve_timeout_seconds: int = field(default_factory=lambda: _env_int("APPROVE_TIMEOUT_SECONDS", 600))
    dql_budget_per_incident: int = field(default_factory=lambda: _env_int("DQL_BUDGET_PER_INCIDENT", 12))

    # --- self-instrumentation
    otel_enabled: bool = field(default_factory=lambda: _env_bool("OTEL_ENABLED", bool(_env("DT_API_TOKEN"))))
    otel_service_name: str = field(default_factory=lambda: _env("OTEL_SERVICE_NAME", "darn-agent"))

    # ----------------------------------------------------------- derived

    @property
    def dt_mcp_url(self) -> str:
        override = _env("DT_MCP_URL")
        if override:
            return override
        if not self.dt_environment:
            return ""
        return (
            f"{self.dt_environment}"
            "/platform-reserved/mcp-gateway/v0.1/servers/dynatrace-mcp/mcp"
        )

    @property
    def dt_classic_url(self) -> str:
        override = _env("DT_CLASSIC_URL")
        if override:
            return override.rstrip("/")
        # https://abc123.apps.dynatrace.com -> https://abc123.live.dynatrace.com
        return self.dt_environment.replace(".apps.dynatrace.com", ".live.dynatrace.com")

    @property
    def dynatrace_configured(self) -> bool:
        return bool(self.dt_environment and self.dt_platform_token)

    @property
    def github_mode(self) -> str:
        if self.github_app_id and self.github_app_private_key_b64:
            return "app"
        if self.github_token:
            return "pat"
        return "none"

    @property
    def github_configured(self) -> bool:
        return self.github_mode != "none" and bool(self.github_repo)

    @property
    def store_mode(self) -> str:
        if self.store_backend:
            return self.store_backend
        return "firestore" if self.gcp_project else "memory"

    @property
    def secrets_mode(self) -> str:
        if self.secrets_backend:
            return self.secrets_backend
        return "gcp" if self.gcp_project else "memory"

    @property
    def vertex_configured(self) -> bool:
        return bool(self.gcp_project)


settings = Settings()
