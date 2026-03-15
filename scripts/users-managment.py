from firebase_admin import auth

from uisurf_admin.config import get_firebase_app


def list_users() -> None:
    """Print all Firebase users and their custom claims."""
    page = auth.list_users()
    while page:
        for user in page.users:
            print("User: " + user.email)
            print("User Claims: " + str(user.custom_claims))
        # Get next batch of users.
        page = page.get_next_page()


def create_user(
    email: str,
    password: str,
    display_name: str | None = None,
    is_admin: bool = False,
) -> auth.UserRecord:
    """Create a Firebase user and optionally assign the admin custom claim."""
    user = auth.create_user(
        email=email,
        password=password,
        display_name=display_name,
    )

    if is_admin:
        auth.set_custom_user_claims(user.uid, {"admin": True})

    print("Successfully created user: " + user.email)
    return auth.get_user(user.uid)


def make_user_admin(email: str) -> None:
    """Set the `admin` custom claim to `True` for the specified user."""
    user = auth.get_user_by_email(email)
    current_user_claims = dict(user.custom_claims or {})
    current_user_claims.update({"admin": True})
    auth.set_custom_user_claims(user.uid, current_user_claims)
    print("Successfully updated user: " + user.email)


def reset_user_custom_claims(email: str) -> None:
    """Clear all custom claims for the specified user."""
    user = auth.get_user_by_email(email)
    auth.set_custom_user_claims(user.uid, None)
    print("Successfully updated user: " + user.email)


def get_user_admins() -> list[auth.UserRecord]:
    """Return all users whose custom claims include `admin=True`."""
    # List all users
    all_users = auth.list_users().iterate_all()
    # Filter users with admin custom claim
    admin_users = [
        user
        for user in all_users
        if user.custom_claims is not None and user.custom_claims.get("admin", False)
    ]
    print(admin_users)
    return admin_users


if __name__ == "__main__":
    """Run a local smoke test for the Firebase admin helpers."""
    get_firebase_app()
    list_users()
