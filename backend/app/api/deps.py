import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import ACCESS_TOKEN_TYPE, decode_token
from app.db.session import get_db
from app.models.auth_credential import AuthCredential


def get_current_user(request: Request, db: Session = Depends(get_db)) -> AuthCredential:
    """Resolve the logged-in user from the `access_token` cookie, or raise 401."""
    unauthorized = HTTPException(status_code=401, detail="not authenticated")
    token = request.cookies.get("access_token")
    if not token:
        raise unauthorized
    try:
        payload = decode_token(token, expected_type=ACCESS_TOKEN_TYPE)
    except jwt.PyJWTError:
        raise unauthorized
    user = db.scalars(
        select(AuthCredential).where(AuthCredential.username == payload["sub"])
    ).first()
    if user is None:
        raise unauthorized
    return user
