import math

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.auth_credential import AuthCredential
from app.services import auth_service
from app.services.errors import InvalidCredentialsError, TooManyAttemptsError

router = APIRouter(prefix="/api/auth", tags=["auth"])

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str


def _set_access_cookie(response: Response, username: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        create_access_token(username),
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


def _set_refresh_cookie(response: Response, username: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        create_refresh_token(username),
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )


@router.post("/login")
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        auth_service.authenticate(db, body.username, body.password, body.totp_code)
    except TooManyAttemptsError as exc:
        raise HTTPException(
            status_code=429,
            detail="too many attempts",
            headers={"Retry-After": str(max(1, math.ceil(exc.retry_after)))},
        )
    except InvalidCredentialsError:
        raise HTTPException(status_code=401, detail="invalid credentials")
    _set_access_cookie(response, body.username)
    _set_refresh_cookie(response, body.username)
    return {"detail": "ok"}


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    unauthorized = HTTPException(status_code=401, detail="not authenticated")
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise unauthorized
    try:
        payload = decode_token(token, expected_type=REFRESH_TOKEN_TYPE)
    except jwt.PyJWTError:
        raise unauthorized
    exists = db.scalars(
        select(AuthCredential.id).where(AuthCredential.username == payload["sub"])
    ).first()
    if exists is None:
        raise unauthorized
    _set_access_cookie(response, payload["sub"])
    return {"detail": "ok"}


@router.get("/me")
def me(user: AuthCredential = Depends(get_current_user)) -> dict[str, str]:
    return {"username": user.username}


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(
        ACCESS_COOKIE, httponly=True, samesite="lax", secure=settings.cookie_secure
    )
    response.delete_cookie(
        REFRESH_COOKIE, httponly=True, samesite="lax", secure=settings.cookie_secure
    )
    return {"detail": "ok"}
