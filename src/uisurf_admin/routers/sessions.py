from fastapi import APIRouter, Depends, status
from fastapi_utils.cbv import cbv

from uisurf_admin.models import (
    CreateSessionRequest,
    DeleteSessionResponse,
    SessionResponse,
)
from uisurf_admin.security import is_admin, AuthUserSchema, get_auth_user
from uisurf_admin.services.session_manager import SessionManager, get_session_manager


router = APIRouter()


@cbv(router)
class SessionsCBV:
    """Administrative endpoints for managing UISurf agent sessions."""

    session_manager: SessionManager = Depends(get_session_manager)
    user : AuthUserSchema = Depends(get_auth_user)

    @router.get(
        "/",
        response_model=list[SessionResponse],
        summary="List active sessions",
        description="Returns the in-memory list of active UISurf agent sessions.",
        dependencies=[Depends(is_admin)],
    )
    async def list_sessions(self) -> list[SessionResponse]:
        """Return all active managed agent sessions."""
        return self.session_manager.list_sessions()

    @router.post(
        "/",
        response_model=SessionResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Create an agent session",
        description=(
            "Starts a new UISurf agent container for the provided session ID and returns "
            "its connection details."
        ),
        responses={
            201: {"description": "Session created successfully"},
            401: {"description": "Missing or invalid authentication token"},
            403: {"description": "Authenticated user is not authorized"},
            409: {"description": "A session with the same ID already exists"},
            422: {"description": "Invalid request body or session ID"},
            500: {"description": "Agent container failed to start"},
        }
    )
    async def create_session(self, payload: CreateSessionRequest) -> SessionResponse:
        """Create and return a managed agent session."""
        return self.session_manager.create_session(
            payload.session_id,
            payload.control_mode,
        )

    @router.get(
        "/{session_id}",
        response_model=SessionResponse,
        summary="Get a session",
        description="Returns the current metadata for a single session.",
        responses={
            401: {"description": "Missing or invalid authentication token"},
            403: {"description": "Authenticated user is not authorized"},
            404: {"description": "Session not found"},
        }
    )
    async def get_session(self, session_id: str) -> SessionResponse:
        """Return metadata for a single managed agent session."""
        return self.session_manager.get_session(session_id)

    @router.delete(
        "/{session_id}",
        response_model=DeleteSessionResponse,
        summary="Delete a session",
        description="Stops the agent container for a session and removes it from memory.",
        responses={
            401: {"description": "Missing or invalid authentication token"},
            403: {"description": "Authenticated user is not authorized"},
            404: {"description": "Session not found"},
        }
    )
    async def delete_session(self, session_id: str) -> DeleteSessionResponse:
        """Delete a managed agent session and return its deletion status."""
        self.session_manager.delete_session(session_id)
        return DeleteSessionResponse(status="deleted")
