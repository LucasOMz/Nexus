"""Política de primeiro acesso e autenticação multifator."""
from datetime import timezone
from typing import Literal

from app.config import settings
from app.models.core import Usuario
from app.models.enums import PapelUsuario

Etapa = Literal["trocar_senha", "cadastrar_mfa"]


def mfa_exigido(user: Usuario) -> bool:
    return user.mfa_obrigatorio or (
        settings.env.lower() == "production" and user.papel == PapelUsuario.ADMIN
    )


def etapa_pendente(user: Usuario) -> Etapa | None:
    if user.senha_temporaria:
        return "trocar_senha"
    if mfa_exigido(user) and not user.mfa_ativo:
        return "cadastrar_mfa"
    return None


def credencial_revogada(user: Usuario, emitido: int | float | None) -> bool:
    limite = user.forcar_logout_em
    if limite is None:
        return False
    if limite.tzinfo is None:
        limite = limite.replace(tzinfo=timezone.utc)
    return not isinstance(emitido, (int, float)) or emitido <= limite.timestamp()
