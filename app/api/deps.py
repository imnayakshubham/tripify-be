"""Auth stub, not a security boundary.

Identity is asserted by header and believed — anyone who can set a header can claim
admin. Real auth replaces `current_user` and nothing else.
"""

from fastapi import Depends, Header, HTTPException

from app.db import audit
from app.schema import CurrentUser

DEFAULT_EMAIL = "demo@example.com"


def current_user(
    x_user_email: str = Header(default=DEFAULT_EMAIL),
    x_user_role: str | None = Header(default=None),
) -> CurrentUser:
    """Resolve, and on first sight create, the caller's user row."""
    row = audit.upsert_user(email=x_user_email, role=x_user_role)

    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="This account is not active.")

    return CurrentUser(id=row["id"], email=row["email"], role=row["role"])


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required.")
    return user
