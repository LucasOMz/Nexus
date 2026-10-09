"""Schemas de autenticação."""
from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import UsuarioOut


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UsuarioOut


class RefreshRequest(BaseModel):
    refresh_token: str
