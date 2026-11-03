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

from app.core.permissoes import eh_admin, pode_acao, pode_modulo
from app.core.security import decode_token
from app.database import get_db
from app.models.core import Usuario
from app.models.enums import PapelUsuario

# tokenUrl é usado apenas pelo Swagger UI ("Authorize").
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

_CREDENCIAIS_INVALIDAS = "Credenciais inválidas ou expiradas"


def _resolver_usuario(db: Session, token: str | None) -> Usuario | None:
    """Decodifica o token e devolve o usuário ativo, ou None."""
    payload = decode_token(token or "")
    if payload is None or payload.get("type") != "access":
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

    # --- o administrador derrubou as sessões desta pessoa? ----------------
    #
    # `forcar_logout_em` é um carimbo. O token sabe quando foi emitido
    # (`iat`); se for anterior, a sessão não vale mais.
    #
    # Comparar com `iat` — e não com "agora" — é o que faz isto funcionar sem
    # tabela de sessões: um token emitido DEPOIS do carimbo continua válido,
    # então a própria pessoa pode logar de novo na hora.
    if user.forcar_logout_em is not None:
        emitido = payload.get("iat")
        # `<=` e não `<`: o `iat` tem precisão de **segundos**, e a derrubada
        # pode cair no mesmo segundo em que o token foi emitido. Com `<`, o
        # token sobrevivia — e o teste ficava intermitente, dependendo de
        # cruzar ou não a fronteira do segundo.
        #
        # O CI pegou isso e a máquina local não: lá, tudo roda em
        # milissegundos e os dois instantes são sempre iguais.
        #
        # Efeito colateral: quem fizer login exatamente no segundo da própria
        # derrubada é recusado. Edge case raro, e falhar fechado é o lado
        # certo para uma trava.
        if emitido is not None and int(emitido) <= int(user.forcar_logout_em.timestamp()):
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


def get_current_user(
    token: str | None = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> Usuario:
    """Resolve o usuário autenticado a partir do header Authorization: Bearer."""
    user = _resolver_usuario(db, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_CREDENCIAIS_INVALIDAS,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


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
