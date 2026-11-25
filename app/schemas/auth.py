"""Schemas de autenticação."""
from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import UsuarioOut


class Token(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    user: UsuarioOut
    # O que o sistema AINDA exige desta pessoa antes de ela usar o sistema.
    #
    # Uma etapa pendente recebe somente a credencial temporária da etapa.
    acao_requerida: str | None = None
    # Texto pronto para a tela explicar o que fazer.
    acao_mensagem: str | None = None


class TrocaSenhaIn(BaseModel):
    senha_atual: str
    senha_nova: str
    confirmacao: str


class RefreshRequest(BaseModel):
    refresh_token: str
