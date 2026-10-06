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
from app.db.session import get_db
from app.models.auth_credential import AuthCredential
from app.services import auth_service
from app.services.errors import (
    InvalidCredentialsError,
    InvalidTotpCodeError,
    TotpAlreadyConfirmedError,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str


class TotpConfirmRequest(BaseModel):
    code: str


def _set_access_cookie(response: Response, username: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        create_access_token(username),
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True,
        samesite="lax",
    )


def _set_refresh_cookie(response: Response, username: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        create_refresh_token(username),
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True,
        samesite="lax",
    )


@router.post("/login")
def login(body: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        auth_service.authenticate(db, body.username, body.password, body.totp_code)
    except InvalidCredentialsError:
        raise HTTPException(status_code=401, detail="invalid credentials")
    _set_access_cookie(response, body.username)
    _set_refresh_cookie(response, body.username)
    return {"detail": "ok"}


@router.post("/totp/setup")
def totp_setup(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        _, provisioning_uri = auth_service.begin_totp_setup(db)
    except TotpAlreadyConfirmedError:
        raise HTTPException(status_code=409, detail="totp already confirmed")
    except InvalidCredentialsError:
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {"provisioning_uri": provisioning_uri}


@router.post("/totp/confirm")
def totp_confirm(body: TotpConfirmRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        auth_service.confirm_totp_setup(db, body.code)
    except InvalidTotpCodeError:
        raise HTTPException(status_code=400, detail="invalid code")
    except InvalidCredentialsError:
        raise HTTPException(status_code=401, detail="invalid credentials")
    return {"detail": "confirmed"}


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


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(ACCESS_COOKIE)
    response.delete_cookie(REFRESH_COOKIE)
    return {"detail": "ok"}
