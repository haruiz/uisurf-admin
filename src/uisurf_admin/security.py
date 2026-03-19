from datetime import datetime
import logging
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from fastapi_utils.api_model import APIModel
from pydantic import ConfigDict, EmailStr
from firebase_admin import auth
from firebase_admin.auth import ExpiredIdTokenError, InvalidIdTokenError

from uisurf_admin.config import get_firebase_app


logger = logging.getLogger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="token_optional",
    auto_error=False,
)


class AuthUserSchema(APIModel):
    """Normalized Firebase ID token claims used by the API."""

    class FirebaseSchema(APIModel):
        """Firebase provider metadata embedded in the token."""

        identities: dict[str, list[str]] = {}
        sign_in_provider: str | None = None

    model_config = ConfigDict(extra="ignore")
    admin: bool = False
    iss: str
    aud: str
    auth_time: datetime
    user_id: str
    sub: str
    iat: datetime
    exp: datetime
    email: EmailStr
    email_verified: bool
    firebase: FirebaseSchema
    uid: str


def _verify_token(token: str) -> AuthUserSchema:
    """Validate a Firebase ID token and convert its claims into `AuthUserSchema`."""
    try:
        decoded: dict[str, Any] | None = auth.verify_id_token(token, app=get_firebase_app())
    except ExpiredIdTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        ) from exc
    except InvalidIdTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected Firebase token verification failure")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service error",
        ) from exc

    if not decoded:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )

    return AuthUserSchema(**decoded)


async def get_auth_user(token: str = Depends(oauth2_scheme)) -> AuthUserSchema:
    """Return the authenticated user for endpoints that require a valid bearer token."""
    return _verify_token(token)


async def get_auth_user_or_none(
    token: str | None = Depends(oauth2_scheme_optional),
) -> AuthUserSchema | None:
    """Return the authenticated user when a bearer token is present, otherwise `None`."""
    if token is None:
        return None

    try:
        return _verify_token(token)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
            raise
        return None


async def get_auth_user_or_None(
    token: str | None = Depends(oauth2_scheme_optional),
) -> AuthUserSchema | None:
    """Backward-compatible alias for `get_auth_user_or_none`."""
    return await get_auth_user_or_none(token)


async def is_admin(auth_user: AuthUserSchema = Depends(get_auth_user)) -> AuthUserSchema:
    """Ensure the authenticated user has the `admin` claim before accessing the endpoint."""
    if not auth_user.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operation not permitted",
        )
    return auth_user
