from functools import lru_cache
import socket
import threading
from urllib.parse import urlencode

import docker
from docker.errors import APIError, DockerException, NotFound
from fastapi import HTTPException, status

from uisurf_admin.config import SessionSettings, get_session_settings
from uisurf_admin.models import SessionResponse


class SessionManager:
    """Manage the lifecycle and in-memory cache of UISurf agent session containers."""

    def __init__(self, settings: SessionSettings | None = None) -> None:
        """Create a session manager backed by app settings and a thread-safe cache.

        Args:
            settings: Optional application settings instance. When omitted, the
                shared cached settings are loaded from `get_session_settings()`.
        """
        self.settings = settings or get_session_settings()
        self.sessions: dict[str, SessionResponse] = {}
        self.sessions_lock = threading.Lock()

    def get_docker_client(self) -> docker.DockerClient:
        """Create a Docker client from the local environment.

        Returns:
            A Docker SDK client configured from the local environment.

        Raises:
            HTTPException: If the Docker daemon cannot be reached.
        """
        try:
            return docker.from_env()
        except DockerException as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="failed to connect to docker",
            ) from exc

    def validate_session_id(self, session_id: str) -> str:
        """Validate the external session ID before creating container resources.

        Args:
            session_id: The client-provided logical session identifier.

        Returns:
            The validated session identifier unchanged.

        Raises:
            HTTPException: If the session ID does not match the configured pattern.
        """
        if not self.settings.session_id_regex.fullmatch(session_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "session_id must be 3-64 chars and contain only letters, numbers, "
                    "hyphens, or underscores"
                ),
            )
        return session_id

    def is_port_available(self, port: int) -> bool:
        """Return whether a host port can be bound for a new session.

        Args:
            port: Host TCP port to test.

        Returns:
            `True` when the port is available for binding, otherwise `False`.
        """
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            bind_host = (
                self.settings.session_bind_host
                if self.settings.session_bind_host != "0.0.0.0"
                else ""
            )
            try:
                sock.bind((bind_host, port))
            except OSError:
                return False
            return True

    def allocate_port(self) -> int:
        """Find the next free host port reserved for managed agent sessions.

        Returns:
            The first available host port above `session_base_port`.
        """
        port = self.settings.session_base_port + 1
        while True:
            if self.is_port_available(port) and all(
                session.port != port for session in self.sessions.values()
            ):
                return port
            port += 1

    def build_public_base_url(self, port: int) -> str:
        """Build the externally reachable base URL for a managed session.

        Args:
            port: Published host port used by the session.

        Returns:
            The absolute public base URL for the container instance.
        """
        base = f"{self.settings.public_vnc_scheme}://{self.settings.public_vnc_host}"
        if self.settings.public_vnc_mode == "proxy":
            prefix = self.settings.normalized_public_vnc_proxy_path_prefix
            return f"{base}{prefix}/{port}"
        return f"{base}:{port}"

    def build_vnc_url(self, session_id: str, port: int) -> str:
        """Build the VNC URL returned to API callers for the given session.

        Args:
            session_id: Logical session identifier used for relative proxy paths.
            port: Published host port used by the session.

        Returns:
            A public absolute URL for the session VNC endpoint.

        Raises:
            HTTPException: If `PUBLIC_VNC_HOST` is not configured.
        """
        if not self.settings.public_vnc_host:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="PUBLIC_VNC_HOST must be configured to build a session VNC URL",
            )
        query = urlencode(
            {
                "autoconnect": "1",
                "resize": "scale",
                "path": self.build_websockify_path(port),
            }
        )
        return f"{self.build_public_base_url(port)}/vnc.html?{query}"

    def build_websockify_path(self, port: int) -> str:
        """Build the path parameter expected by noVNC for websocket tunneling."""
        if self.settings.public_vnc_mode == "proxy":
            prefix = self.settings.normalized_public_vnc_proxy_path_prefix.strip("/")
            return f"{prefix}/{port}/websockify"
        return "websockify"

    def build_agent_environment(self, port: int) -> dict[str, str]:
        """Build per-container environment variables for agent discovery URLs.

        Args:
            port: Published host port assigned to the container.

        Returns:
            Environment variables combining shared agent credentials with
            per-session public URLs.
        """
        environment = self.settings.agent_environment()
        public_base_url = self.build_public_base_url(port)
        environment["PUBLIC_BASE_URL"] = public_base_url
        environment["BROWSER_AGENT_PUBLIC_URL"] = f"{public_base_url}/browser/"
        environment["DESKTOP_AGENT_PUBLIC_URL"] = f"{public_base_url}/desktop/"
        return environment

    def build_session(
        self,
        session_id: str,
        port: int,
        control_mode: str,
    ) -> SessionResponse:
        """Build the API response model representing an agent session.

        Args:
            session_id: Logical session identifier.
            port: Published host port assigned to the container.
            control_mode: Session control mode such as `agent` or `manual`.

        Returns:
            A `SessionResponse` describing the session metadata.
        """
        container_name = f"{self.settings.session_container_prefix}_{session_id}"
        return SessionResponse(
            session_id=session_id,
            container_name=container_name,
            port=port,
            control_mode=control_mode,
            vnc_url=self.build_vnc_url(session_id, port),
        )

    def extract_labels(
        self,
        container: docker.models.containers.Container,
    ) -> dict[str, str]:
        """Reload a container and return its Docker labels as a plain dictionary.

        Args:
            container: Docker container object returned by the SDK.

        Returns:
            A dictionary of Docker label key/value pairs.
        """
        container.reload()
        return container.attrs.get("Config", {}).get("Labels", {}) or {}

    def load_sessions_from_docker(self) -> dict[str, SessionResponse]:
        """Rebuild the in-memory session map from Docker-managed containers.

        Returns:
            A mapping of session ID to `SessionResponse` for all managed containers.

        Raises:
            HTTPException: If Docker cannot list the managed containers.
        """
        restored: dict[str, SessionResponse] = {}
        client = self.get_docker_client()

        try:
            containers = client.containers.list(
                filters={"label": f"{self.settings.session_label_managed}=true"}
            )
        except DockerException as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="failed to load docker sessions",
            ) from exc

        for container in containers:
            labels = self.extract_labels(container)
            session_id = labels.get(self.settings.session_label_id)
            port_value = labels.get(self.settings.session_label_port)
            control_mode = labels.get(self.settings.session_label_mode, "agent")

            if not session_id or not port_value:
                continue

            try:
                port = int(port_value)
            except ValueError:
                continue

            restored[session_id] = SessionResponse(
                session_id=session_id,
                container_name=container.name,
                port=port,
                control_mode=control_mode,
                vnc_url=self.build_vnc_url(session_id, port),
            )

        return restored

    def restore_sessions(self) -> None:
        """Replace the in-memory session cache with the current Docker state."""
        with self.sessions_lock:
            self.sessions.clear()
            self.sessions.update(self.load_sessions_from_docker())

    def list_sessions(self) -> list[SessionResponse]:
        """Return the current in-memory list of managed agent sessions.

        Returns:
            A list of all tracked agent sessions.
        """
        return list(self.sessions.values())

    def get_session(self, session_id: str) -> SessionResponse:
        """Fetch a single session from the in-memory cache.

        Args:
            session_id: Logical session identifier to look up.

        Returns:
            The matching `SessionResponse`.

        Raises:
            HTTPException: If the session does not exist.
        """
        session = self.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="session not found")
        return session

    def create_session(self, session_id: str, control_mode: str) -> SessionResponse:
        """Start a Docker container for a new managed agent session.

        Args:
            session_id: Logical session identifier requested by the client.
            control_mode: Requested session control mode.

        Returns:
            The created session metadata.

        Raises:
            HTTPException: If validation fails, the session already exists, or
                the Docker container cannot be started.
        """
        validated_id = self.validate_session_id(session_id)
        client = self.get_docker_client()
        environment = self.settings.agent_environment()

        if not environment:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "missing agent API credentials: configure GEMINI_API_KEY or "
                    "GOOGLE_API_KEY for session containers"
                ),
            )

        with self.sessions_lock:
            if validated_id in self.sessions:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"session '{validated_id}' already exists",
                )

            max_attempts = 20
            last_error = ""

            for _ in range(max_attempts):
                port = self.allocate_port()
                session = self.build_session(validated_id, port, control_mode)
                environment = self.build_agent_environment(port)

                try:
                    client.containers.run(
                        self.settings.ui_agent_image,
                        detach=True,
                        name=session.container_name,
                        init=True,
                        ipc_mode="host",
                        shm_size="2g",
                        cap_add=["SYS_ADMIN"],
                        environment=environment,
                        labels={
                            self.settings.session_label_managed: "true",
                            self.settings.session_label_id: session.session_id,
                            self.settings.session_label_port: str(session.port),
                            self.settings.session_label_mode: session.control_mode,
                        },
                        ports={
                            f"{self.settings.ui_agent_container_port}/tcp": (
                                self.settings.session_bind_host,
                                port,
                            )
                        },
                    )
                    self.sessions[validated_id] = session
                    return session
                except APIError as exc:
                    message = str(exc)
                    last_error = message
                    if "port is already allocated" in message.lower():
                        continue
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"failed to start agent container: {message}",
                    ) from exc
                except DockerException as exc:
                    last_error = str(exc)
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"failed to start agent container: {exc}",
                    ) from exc

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"failed to allocate a free agent port: {last_error or 'unknown error'}",
            )

    def delete_session(self, session_id: str) -> None:
        """Stop and remove the agent container associated with a session.

        Args:
            session_id: Logical session identifier to delete.

        Raises:
            HTTPException: If the session does not exist or Docker removal fails.
        """
        client = self.get_docker_client()

        with self.sessions_lock:
            session = self.sessions.get(session_id)
            if not session:
                raise HTTPException(status_code=404, detail="session not found")

            try:
                container = client.containers.get(session.container_name)
                container.remove(force=True)
            except NotFound:
                pass
            except DockerException as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"failed to delete agent container: {exc}",
                ) from exc

            del self.sessions[session_id]


@lru_cache
def get_session_manager() -> SessionManager:
    """Return the shared `SessionManager` instance used by FastAPI dependencies."""
    return SessionManager()
