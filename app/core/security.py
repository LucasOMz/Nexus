"""Segurança: hash de senha (bcrypt) e JWT (PyJWT).

Decisão arquitetural: usamos `bcrypt` diretamente (em vez de passlib), pois o
passlib tem incompatibilidades conhecidas com bcrypt >= 4.1. Tokens JWT:
access (15 min) + refresh (7 dias) com claim `type` para impedir reuso.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import bcrypt
import jwt

from app.config import settings

# bcrypt só usa os primeiros 72 bytes; senhas maiores são truncadas.
_BCRYPT_MAX_BYTES = 72

SETUP_TTL = timedelta(minutes=10)


def _prepare(password: str) -> bytes:
    raw = password.encode("utf-8")
    return raw[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """Gera hash bcrypt da senha."""
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verifica senha contra o hash armazenado."""
    try:
        return bcrypt.checkpw(_prepare(password), hashed.encode("utf-8"))
    except ValueError:
        return False


def _create_token(
    sub: str, papel: str, token_type: str, expires_delta: timedelta, email: str | None = None,
    *, etapa: str | None = None, mfa_verificado: bool = False, sessao_id: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": sub,
        "papel": papel,
        "type": token_type,
        "iat": now.timestamp(),
        "exp": now + expires_delta,
    }
    # O e-mail vai no token para detectar troca de identidade: se o banco for
    # restaurado e o id passar a apontar para outra pessoa, o token é recusado.
    if email:
        payload["email"] = email
    if etapa is not None:
        payload["etapa"] = etapa
    if mfa_verificado:
        payload["mfa_verificado"] = True
    if sessao_id is not None:
        payload["sid"] = sessao_id
        payload["jti"] = uuid4().hex
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(
    user_id: int, papel: str, email: str | None = None, *,
    mfa_verificado: bool = False, sessao_id: str | None = None,
) -> str:
    return _create_token(
        str(user_id), papel, "access", timedelta(minutes=settings.access_token_expire_minutes), email,
        mfa_verificado=mfa_verificado, sessao_id=sessao_id,
    )


def create_refresh_token(
    user_id: int, papel: str, email: str | None = None, *,
    mfa_verificado: bool = False, sessao_id: str | None = None,
) -> str:
    return _create_token(
        str(user_id), papel, "refresh", timedelta(days=settings.refresh_token_expire_days), email,
        mfa_verificado=mfa_verificado, sessao_id=sessao_id,
    )


def create_setup_token(user_id: int, papel: str, email: str, etapa: str, sessao_id: str) -> str:
    return _create_token(str(user_id), papel, "setup", SETUP_TTL, email, etapa=etapa, sessao_id=sessao_id)


def decode_token(token: str) -> dict[str, Any] | None:
    """Decodifica e valida um JWT; retorna None se inválido/expirado."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
