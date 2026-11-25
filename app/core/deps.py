"""Dependências FastAPI: usuário atual e controle de acesso.

Dois níveis de autorização:
  - `require_module(...)`  — acesso a um módulo/tela (ex.: "relatorios").
  - `require_write` / `require_delete` — permissões de escrita do usuário.
  - `require_role(...)` / `require_admin` — papéis (compatibilidade).
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.core.permissoes import eh_admin, pode_acao, pode_modulo
from app.core.primeiro_acesso import Etapa, credencial_revogada, etapa_pendente
from app.core.security import decode_token
from app.database import get_db
from app.models.core import Usuario
from app.models.enums import PapelUsuario
from app.services import sessoes

# tokenUrl é usado apenas pelo Swagger UI ("Authorize").
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

_CREDENCIAIS_INVALIDAS = "Credenciais inválidas ou expiradas"


def _resolver_usuario(
    db: Session, token: str | None, etapa_permitida: Etapa | None = None,
) -> Usuario | None:
    """Decodifica o token e devolve o usuário ativo, ou None."""
    payload = decode_token(token or "")
    if payload is None or payload.get("type") not in ("access", "setup"):
        return None
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError):
        return None
    user = db.get(Usuario, user_id)
    if user is None or user.deleted_at is not None or not user.ativo:
        return None
    # O e-mail do token precisa bater com o do usuário: se o banco for restaurado
    # de um backup e o id passar a apontar para outra pessoa, o token é recusado.
    email_token = payload.get("email")
    if email_token and email_token != user.email:
        return None

    etapa = etapa_pendente(user)
    if payload["type"] == "setup":
        if etapa_permitida is None or etapa != etapa_permitida or payload.get("etapa") != etapa:
            return None
    elif etapa is not None or (user.mfa_ativo and payload.get("mfa_verificado") is not True):
        return None

    sid = payload.get("sid")
    if sid is None:
        if payload["type"] == "setup" or settings.env.lower() == "production":
            return None
        if credencial_revogada(user, payload.get("iat")):
            return None
    elif not isinstance(sid, str) or not sessoes.ativa(db, sid, user.id, setup=payload["type"] == "setup"):
        return None

    # --- modo manutenção --------------------------------------------------
    #
    # 503, e não 401: não é credencial errada, é o sistema indisponível. O
    # frontend usa o status para mostrar a tela de manutenção em vez de
    # mandar a pessoa para o login — onde ela bateria na mesma parede.
    papel = getattr(user.papel, "value", user.papel)
    if papel != "admin":
        from app.services import manutencao as _manutencao

        if _manutencao.esta_ativa(db):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_manutencao.mensagem(db),
                headers={"Retry-After": "60"},
            )

    # --- presença ---------------------------------------------------------
    #
    # Uma escrita por minuto, no máximo. Em toda requisição seria um UPDATE
    # por chamada, e o pool é pequeno.
    #
    # Falhar aqui NUNCA pode derrubar a requisição: é telemetria.
    if etapa is not None:
        return user
    try:
        from datetime import datetime, timezone

        agora = datetime.now(timezone.utc)
        ultimo = user.ultimo_acesso_em
        if ultimo is None or (agora - ultimo).total_seconds() > 60:
            user.ultimo_acesso_em = agora
            db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()

    return user


def _exigir_usuario(db: Session, token: str | None, etapa: Etapa | None = None) -> Usuario:
    user = _resolver_usuario(db, token, etapa)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_CREDENCIAIS_INVALIDAS,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_user(
    token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db),
) -> Usuario:
    return _exigir_usuario(db, token)


def usuario_para_troca_de_senha(
    token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db),
) -> Usuario:
    return _exigir_usuario(db, token, "trocar_senha")


def usuario_para_configurar_mfa(
    token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db),
) -> Usuario:
    return _exigir_usuario(db, token, "cadastrar_mfa")


def get_current_user_query(
    token: str | None = Query(default=None),
    header_token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    """Aceita o token via `?token=` (para <img src>) OU via header Authorization."""
    user = _resolver_usuario(db, token or header_token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_CREDENCIAIS_INVALIDAS)
    return user


def require_module(*modulos: str) -> Callable:
    """Exige acesso a pelo menos um dos módulos informados."""

    def dependency(user: Usuario = Depends(get_current_user)) -> Usuario:
        if eh_admin(user) or any(pode_modulo(user, m) for m in modulos):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seu usuário não tem acesso a este módulo",
        )

    return dependency


def _requer_acao(acao: str, mensagem: str) -> Callable:
    def dependency(user: Usuario = Depends(get_current_user)) -> Usuario:
        if not pode_acao(user, acao):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=mensagem)
        return user

    return dependency


# Permissões de escrita (criar/editar) e exclusão.
require_write = _requer_acao("pode_escrever", "Seu usuário não tem permissão para criar/editar")
require_delete = _requer_acao("pode_excluir", "Seu usuário não tem permissão para excluir")


def require_role(*roles: PapelUsuario) -> Callable:
    """Exige que o usuário tenha um dos papéis informados."""

    def dependency(user: Usuario = Depends(get_current_user)) -> Usuario:
        if user.papel not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permissão insuficiente para esta operação",
            )
        return user

    return dependency


def require_admin(user: Usuario = Depends(get_current_user)) -> Usuario:
    """Somente administradores (área de administração)."""
    if not eh_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso restrito ao administrador")
    return user


require_audit = require_role(PapelUsuario.ADMIN, PapelUsuario.AUDITOR)


def require_escrita(modulo: str) -> Callable:
    """Exige acesso ao módulo E permissão de criar/editar."""

    def dependency(user: Usuario = Depends(get_current_user)) -> Usuario:
        if eh_admin(user) or (pode_modulo(user, modulo) and pode_acao(user, "pode_escrever")):
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão de escrita neste módulo")

    return dependency


def require_exclusao(modulo: str) -> Callable:
    """Exige acesso ao módulo E permissão de excluir."""

    def dependency(user: Usuario = Depends(get_current_user)) -> Usuario:
        if eh_admin(user) or (pode_modulo(user, modulo) and pode_acao(user, "pode_excluir")):
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão para excluir neste módulo")

    return dependency
