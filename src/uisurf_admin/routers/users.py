import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi_utils.api_model import APIModel
from fastapi_utils.cbv import cbv
from firebase_admin import auth
from firebase_admin.auth import (
    EmailAlreadyExistsError,
    UserNotFoundError,
    UidAlreadyExistsError,
)

from uisurf_admin.models import UserRecordModel
from uisurf_admin.security import is_admin


logger = logging.getLogger(__name__)

router = APIRouter()


class MessageResponse(APIModel):
    """Simple response envelope for mutation endpoints."""

    message: str


class PasswordResetResponse(MessageResponse):
    """Response payload returned after generating a reset-password link."""

    link: str


def _to_user_model(user: auth.UserRecord) -> UserRecordModel:
    """Convert a Firebase `UserRecord` into the API response model."""
    return UserRecordModel(
        uid=user.uid,
        email=user.email or "",
        display_name=user.display_name,
        custom_claims=user.custom_claims,
        disabled=user.disabled,
        email_verified=user.email_verified,
    )


def _get_user_or_404(user_id: str) -> auth.UserRecord:
    """Fetch a Firebase user by UID or raise a 404 response."""
    try:
        return auth.get_user(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' was not found",
        ) from exc


def _get_user_by_email_or_404(email: str) -> auth.UserRecord:
    """Fetch a Firebase user by email address or raise a 404 response."""
    try:
        return auth.get_user_by_email(email)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with email '{email}' was not found",
        ) from exc


@cbv(router)
class UsersCBV:
    """Administrative endpoints for managing Firebase Auth users."""

    @router.get(
        "/",
        response_model=list[UserRecordModel],
        dependencies=[Depends(is_admin)],
    )
    async def get_users(self) -> list[UserRecordModel]:
        """Return all Firebase users sorted by display name and email."""
        try:
            users = [_to_user_model(user) for user in auth.list_users().iterate_all()]
        except Exception as exc:
            logger.exception("Failed to list Firebase users")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to retrieve users",
            ) from exc

        return sorted(
            users,
            key=lambda user: (
                (user.display_name or "").lower(),
                user.email.lower(),
            ),
        )

    @router.put(
        "/{user_id}",
        response_model=UserRecordModel,
        dependencies=[Depends(is_admin)],
    )
    async def update_user(self, user_id: str, user_data: UserRecordModel) -> UserRecordModel:
        """Update mutable fields for a Firebase user and return the fresh record."""
        _get_user_or_404(user_id)
        payload = user_data.model_dump(
            exclude_none=True,
            exclude={"uid", "custom_claims"},
        )

        try:
            auth.update_user(user_id, **payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            logger.exception("Failed to update Firebase user '%s'", user_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update user",
            ) from exc

        updated_user = _get_user_or_404(user_id)
        return _to_user_model(updated_user)

    @router.post(
        "/",
        response_model=UserRecordModel,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(is_admin)],
    )
    async def create_user(self, user: UserRecordModel) -> UserRecordModel:
        """Create a Firebase user and optionally attach custom claims."""
        payload = user.model_dump(exclude_none=True, exclude={"uid", "custom_claims"})

        try:
            created_user = auth.create_user(**payload)
            if user.custom_claims is not None:
                auth.set_custom_user_claims(created_user.uid, user.custom_claims)
        except (EmailAlreadyExistsError, UidAlreadyExistsError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        except Exception as exc:
            logger.exception("Failed to create Firebase user")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user",
            ) from exc

        return _to_user_model(_get_user_or_404(created_user.uid))

    @router.post(
        "/{email}/reset-password",
        response_model=PasswordResetResponse,
        dependencies=[Depends(is_admin)],
    )
    async def reset_user_password(self, email: str) -> PasswordResetResponse:
        """Generate a password-reset link for the given user email."""
        user = _get_user_by_email_or_404(email)

        try:
            link = auth.generate_password_reset_link(user.email)
        except Exception as exc:
            logger.exception("Failed to generate reset link for '%s'", email)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate password reset link",
            ) from exc

        return PasswordResetResponse(
            message="Password reset link generated successfully",
            link=link,
        )

    @router.delete(
        "/{uid}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(is_admin)],
    )
    async def delete_user_by_id(self, uid: str) -> Response:
        """Delete a Firebase user identified by UID."""
        user = _get_user_or_404(uid)

        try:
            auth.delete_user(user.uid)
        except Exception as exc:
            logger.exception("Failed to delete Firebase user '%s'", uid)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete user",
            ) from exc

        return Response(status_code=status.HTTP_204_NO_CONTENT)
