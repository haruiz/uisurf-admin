import logging
import re
from functools import lru_cache
from typing import Literal

import firebase_admin
from firebase_admin import credentials
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


logger = logging.getLogger(__name__)


class AppSettings(BaseSettings):
    """Central application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Public API prefix mounted by FastAPI behind the reverse proxy.
    api_root_path: str = Field(default="/api", validation_alias="API_ROOT_PATH")

    # Firebase project identifier used by admin tooling and backend integration.
    firebase_project_id: str | None = Field(
        default=None,
        validation_alias="FIREBASE_PROJECT_ID",
    )
    # Service-account client email for explicit Firebase initialization.
    firebase_client_email: str | None = Field(
        default=None,
        validation_alias="FIREBASE_CLIENT_EMAIL",
    )
    # Service-account private key for explicit Firebase initialization.
    firebase_private_key: str | None = Field(
        default=None,
        validation_alias="FIREBASE_PRIVATE_KEY",
    )


class SessionSettings(BaseSettings):
    """Session-management configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # First host port reserved for managed agent sessions. New sessions allocate upward from here.
    session_base_port: int = Field(default=7000, validation_alias="SESSION_BASE_PORT")
    # Docker image name used when creating a new UISurf agent container.
    ui_agent_image: str = Field(
        default="uisurf-agent:latest",
        validation_alias="UI_AGENT_IMAGE",
    )
    # TCP port exposed by the agent container itself.
    ui_agent_container_port: int = Field(
        default=6080,
        validation_alias="UI_AGENT_CONTAINER_PORT",
    )
    # Prefix used to build deterministic Docker container names per session.
    session_container_prefix: str = Field(
        default="uisurf-agent-session",
        validation_alias="SESSION_CONTAINER_PREFIX",
    )
    # Host interface used when publishing the agent container port locally.
    session_bind_host: str = Field(
        default="127.0.0.1",
        validation_alias="SESSION_BIND_HOST",
    )
    # Optional public hostname used to generate absolute agent access URLs for clients.
    public_vnc_host: str = Field(default="127.0.0.1", validation_alias="PUBLIC_VNC_HOST")
    # URL scheme paired with `public_vnc_host` when building the public access URL.
    public_vnc_scheme: str = Field(default="http", validation_alias="PUBLIC_VNC_SCHEME")
    # Session URL generation mode. `direct` exposes host ports directly, while
    # `proxy` emits path-based URLs meant to be fronted by a reverse proxy.
    public_vnc_mode: Literal["direct", "proxy"] = Field(
        default="direct",
        validation_alias="PUBLIC_VNC_MODE",
    )
    # Proxy path prefix used when `PUBLIC_VNC_MODE=proxy`.
    public_vnc_proxy_path_prefix: str = Field(
        default="/sessions",
        validation_alias="PUBLIC_VNC_PROXY_PATH_PREFIX",
    )
    # API key used by the UISurf agent when talking to Gemini-compatible backends.
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    # API key used by the UISurf agent when talking to Google AI backends.
    google_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")

    # Docker label used to mark containers created and managed by this API.
    session_label_managed: str = "uisurf-agent.managed"
    # Docker label key storing the logical session identifier.
    session_label_id: str = "uisurf-agent.session_id"
    # Docker label key storing the published host port used by the session.
    session_label_port: str = "uisurf-agent.port"
    # Docker label key storing the session control mode.
    session_label_mode: str = "uisurf-agent.control_mode"

    # Regular expression that constrains session identifiers accepted by the API.
    session_id_pattern: str = r"^[a-zA-Z0-9_-]{3,64}$"

    @property
    def session_id_regex(self) -> re.Pattern[str]:
        """Compiled session ID validator used by the session manager."""
        return re.compile(self.session_id_pattern)

    @property
    def normalized_public_vnc_proxy_path_prefix(self) -> str:
        """Return a stable absolute prefix used for reverse-proxied session URLs."""
        prefix = self.public_vnc_proxy_path_prefix.strip()
        if not prefix:
            return "/sessions"
        return "/" + prefix.strip("/")

    def agent_environment(self) -> dict[str, str]:
        """Return environment variables that must be injected into agent containers."""
        environment: dict[str, str] = {}
        if self.gemini_api_key:
            environment["GEMINI_API_KEY"] = self.gemini_api_key
        if self.google_api_key:
            environment["GOOGLE_API_KEY"] = self.google_api_key
        return environment


@lru_cache
def get_app_settings() -> AppSettings:
    """Return the cached application settings instance."""
    return AppSettings()


@lru_cache
def get_session_settings() -> SessionSettings:
    """Return the cached session-management settings instance."""
    return SessionSettings()


@lru_cache
def get_firebase_app() -> firebase_admin.App:
    """Initialize and cache the default Firebase Admin application."""
    try:
        return firebase_admin.get_app()
    except ValueError:
        pass

    settings = get_app_settings()

    if settings.firebase_client_email and settings.firebase_private_key and settings.firebase_project_id:
        credential = credentials.Certificate(
            {
                "type": "service_account",
                "project_id": settings.firebase_project_id,
                "client_email": settings.firebase_client_email,
                "private_key": settings.firebase_private_key.replace("\\n", "\n"),
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        )
        default_app = firebase_admin.initialize_app(
            credential=credential,
            options={"projectId": settings.firebase_project_id},
        )
        logger.info("Firebase app initialized from explicit service account settings")
        return default_app

    options = {"projectId": settings.firebase_project_id} if settings.firebase_project_id else None
    default_app = firebase_admin.initialize_app(options=options)
    if settings.firebase_project_id:
        logger.info(
            "Firebase app initialized with application default credentials for project %s",
            settings.firebase_project_id,
        )
    else:
        logger.info("Firebase app initialized with application default credentials")
    return default_app
