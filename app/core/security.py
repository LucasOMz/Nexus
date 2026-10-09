"""Segurança: hash de senha (bcrypt) e JWT (PyJWT).

Decisão arquitetural: usamos `bcrypt` diretamente (em vez de passlib), pois o
passlib tem incompatibilidades conhecidas com bcrypt >= 4.1. Tokens JWT:
access (15 min) + refresh (7 dias) com claim `type` para impedir reuso.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.config import settings

# bcrypt só usa os primeiros 72 bytes; senhas maiores são truncadas.
_BCRYPT_MAX_BYTES = 72

# Sufixo aplicado ao segredo em tempo de execução. Permite invalidar TODOS os
# tokens já emitidos (usado depois de restaurar um backup do banco).
_sufixo_runtime = ""


def invalidar_tokens() -> None:
    """Invalida todos os tokens emitidos até agora (obriga novo login)."""
    global _sufixo_runtime
    import secrets

    _sufixo_runtime = secrets.token_urlsafe(16)


def _segredo() -> str:
    return settings.jwt_secret + _sufixo_runtime


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


def _create_token(sub: str, papel: str, token_type: str, expires_delta: timedelta, email: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": sub,
        "papel": papel,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    # O e-mail vai no token para detectar troca de identidade: se o banco for
    # restaurado e o id passar a apontar para outra pessoa, o token é recusado.
    if email:
        payload["email"] = email
    return jwt.encode(payload, _segredo(), algorithm=settings.jwt_algorithm)


def create_access_token(user_id: int, papel: str, email: str | None = None) -> str:
    return _create_token(
        str(user_id), papel, "access", timedelta(minutes=settings.access_token_expire_minutes), email
    )


def create_refresh_token(user_id: int, papel: str, email: str | None = None) -> str:
    return _create_token(
        str(user_id), papel, "refresh", timedelta(days=settings.refresh_token_expire_days), email
    )


def decode_token(token: str) -> dict[str, Any] | None:
    """Decodifica e valida um JWT; retorna None se inválido/expirado."""
    try:
        return jwt.decode(token, _segredo(), algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
