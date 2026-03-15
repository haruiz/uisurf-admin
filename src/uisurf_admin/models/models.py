from typing import Optional
from typing import Literal

from fastapi_utils.api_model import APIModel


class UserRecordModel(APIModel):
    uid: Optional[str] = None
    email: str
    display_name: Optional[str] = None
    custom_claims: Optional[dict] = None
    disabled: Optional[bool] = False
    email_verified: Optional[bool] = False
    password: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True


class CreateSessionRequest(APIModel):
    """Payload used to create a managed UISurf agent session."""

    session_id: str
    control_mode: Literal["agent", "manual"] = "agent"


class SessionResponse(APIModel):
    """Session metadata returned by the UISurf agent sessions API."""

    session_id: str
    container_name: str
    port: int
    control_mode: Literal["agent", "manual"] = "agent"
    vnc_url: str


class DeleteSessionResponse(APIModel):
    """Response payload returned after deleting a session."""

    status: str
