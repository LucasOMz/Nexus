"""Identidades de colaboradores do AD usadas nos termos dos ativos."""
from __future__ import annotations

from secrets import token_urlsafe

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.permissoes import email_da_conta_root
from app.core.security import hash_password
from app.models.core import ConfiguracaoSistema, Usuario
from app.models.enums import PapelUsuario
from app.services import ldap_service


class ColaboradorAD(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    login: str = Field(min_length=1, max_length=120)
    nome: str = Field(min_length=1, max_length=160)
    email: EmailStr = Field(max_length=160)


def ad_disponivel(cfg: ConfiguracaoSistema | None) -> bool:
    return bool(cfg and cfg.ldap_ativo and cfg.ldap_servidor and cfg.ldap_base_dn)


def buscar_colaborador(db: Session, login: str) -> ColaboradorAD:
    cfg = db.get(ConfiguracaoSistema, 1)
    if not ad_disponivel(cfg):
        raise HTTPException(409, "A integração com o AD precisa estar habilitada em Administração.")
    db.expunge(cfg)
    db.rollback()
    ok, _, dados = ldap_service.buscar_usuario(cfg, login)
    if not ok:
        raise HTTPException(400, "Não foi possível localizar o colaborador no AD. Confira o login e a conexão.")
    try:
        return ColaboradorAD.model_validate(dados)
    except ValidationError as exc:
        raise HTTPException(422, "O diretório precisa informar um login, um nome e um e-mail válido para o termo.") from exc


def vincular_colaborador(db: Session, dados: ColaboradorAD, planta_id: int | None) -> Usuario:
    def localizar():
        encontrados = db.scalars(select(Usuario).where(
            func.lower(Usuario.login_ad) == dados.login.lower(), Usuario.origem == "ad", Usuario.deleted_at.is_(None),
        ).limit(2)).all()
        if len(encontrados) > 1:
            raise HTTPException(409, "Já existe mais de um cadastro Nexus para esse login de rede.")
        return encontrados[0] if encontrados else None

    colaborador = localizar()
    if colaborador is not None:
        return colaborador
    email = dados.email.lower()
    if email_da_conta_root(email) or db.scalar(select(Usuario.id).where(func.lower(Usuario.email) == email)):
        raise HTTPException(409, "Este e-mail já está reservado ou vinculado a outro cadastro no Nexus.")
    # Termos e movimentações referenciam Usuario. O registro só serve
    # para identificar o colaborador até a TI liberar seu acesso.
    colaborador = Usuario(
        nome=dados.nome, email=email, login_ad=dados.login, origem="ad",
        ativo=False, chat_ia_ativo=False, papel=PapelUsuario.LEITOR, planta_id=planta_id,
        senha_hash=hash_password(token_urlsafe(32)), mfa_obrigatorio=True,
    )
    try:
        db.add(colaborador)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        colaborador = localizar()
        if colaborador is None:
            raise HTTPException(409, "Não foi possível vincular este login ao cadastro do colaborador.") from exc
    return colaborador
