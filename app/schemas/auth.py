"""Schemas de autenticação."""
from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import UsuarioOut


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UsuarioOut
    # O que o sistema AINDA exige desta pessoa antes de ela usar o sistema.
    #
    # O token é emitido mesmo assim, de propósito: para trocar a senha ou
    # cadastrar o MFA é preciso estar autenticado. A trava não é "não dar o
    # token" — é o servidor recusar qualquer outra rota enquanto isto não
    # estiver resolvido (ver `exigir_primeiro_acesso` em core/deps).
    acao_requerida: str | None = None
    # Texto pronto para a tela explicar o que fazer.
    acao_mensagem: str | None = None


class TrocaSenhaIn(BaseModel):
    senha_atual: str
    senha_nova: str
    confirmacao: str


class RefreshRequest(BaseModel):
    refresh_token: str
