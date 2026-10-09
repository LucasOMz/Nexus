"""Autenticação: login (local ou LDAP/AD), refresh, logout e perfil do usuário.

Regra de autenticação:

* Usuário **local** (`origem='local'`) — o `root`/admin e as contas criadas na
  tela de Administração — autentica **somente pela senha do sistema**. É a
  exceção que não depende do grupo do AD.
* Os demais tentam o **LDAP/AD** (se ativo) e, não dando certo, a senha local
  (compatibilidade com contas antigas).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.rate_limit import login_limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.database import get_db
from app.models.core import Usuario
from app.schemas.auth import RefreshRequest, Token
from app.schemas.common import UsuarioOut
from app.services.audit_service import audit
from app.services.config_service import obter_config
from app.services.ldap_service import autenticar

router = APIRouter(prefix="/auth", tags=["auth"])

# Blacklist de refresh tokens em memória. OPCIONAL em produção: usar Redis
# para sobreviver a múltiplas réplicas (ver seção 6 da especificação).
_refresh_blacklist: set[str] = set()

_ERRO_GENERICO = "Usuário ou senha inválidos"


def _sincronizar_nome_do_ad(user: Usuario, resultado) -> bool:
    """Mantém o nome em dia com o diretório.

    O AD é a fonte da verdade sobre COMO a pessoa se chama; o sistema é a fonte
    sobre O QUE ela pode fazer. Por isso daqui só sai atualização de nome —
    nunca papel, nunca criação de conta.
    """
    if resultado.nome and user.nome != resultado.nome:
        user.nome = resultado.nome
        return True
    return False


@router.post("/login", response_model=Token)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> Token:
    """Autentica o usuário e emite access + refresh tokens.

    `username` aceita o e-mail (contas locais) ou o login do AD
    (`sAMAccountName`), conforme o filtro configurado.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not login_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um instante.")

    identificador = (form.username or "").strip()
    # Procura por e-mail OU pelo usuário de logon do AD: quem entra digita o
    # login de rede (`joao.silva`), que quase nunca é igual ao e-mail.
    user = (
        db.query(Usuario)
        .filter(
            or_(
                func.lower(Usuario.email) == identificador.lower(),
                func.lower(Usuario.login_ad) == identificador.lower(),
            ),
            Usuario.deleted_at.is_(None),
        )
        .first()
    )
    cfg = obter_config(db)

    if user is not None and user.origem == "local":
        # Conta local (inclui o root/admin): senha do sistema, sem AD.
        if not verify_password(form.password, user.senha_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_ERRO_GENERICO)
    else:
        autenticado = False
        # O AD serve para confirmar QUEM é a pessoa (a senha de rede). Se ela
        # pode entrar, e com qual perfil, é decidido aqui no cadastro.
        if cfg.ldap_ativo:
            resultado = autenticar(cfg, identificador, form.password)
            if resultado.ok:
                autenticado = user is not None
                if user is None:
                    # Senha de rede correta, mas ninguém liberou o acesso.
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Seu usuário de rede ainda não tem acesso a este sistema. "
                               "Peça ao administrador para cadastrá-lo.",
                    )
                _sincronizar_nome_do_ad(user, resultado)
        # Compatibilidade: conta que existe localmente e não é do AD.
        if not autenticado and user is not None and user.origem != "ad":
            if verify_password(form.password, user.senha_hash):
                autenticado = True
        if not autenticado:
            # Mensagem única: não revela se o usuário existe ou não.
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_ERRO_GENERICO)

    if not user.ativo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário inativo")

    audit(db, user, "login", "usuario", user.id, ip=client_ip)
    db.commit()

    return Token(
        access_token=create_access_token(user.id, user.papel.value, user.email),
        refresh_token=create_refresh_token(user.id, user.papel.value),
        user=UsuarioOut.model_validate(user),
    )


class PreferenciasUpdate(BaseModel):
    """Preferências de interface do próprio usuário."""

    model_config = ConfigDict(extra="forbid")

    barra_favoritos: list[str] | None = None
    # Ordem da lista inteira da gaveta. Separada dos favoritos: quem reordena
    # mexe em todas as linhas, não só nas marcadas.
    barra_ordem: list[str] | None = None


def _limpar_lista(itens: list[str] | None) -> list[str]:
    """Limita quantidade e tamanho: é preferência de tela, não campo livre."""
    return [str(m).strip()[:40] for m in (itens or []) if str(m).strip()][:80]


@router.put("/preferencias")
def salvar_preferencias(
    body: PreferenciasUpdate,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """Salva as preferências de interface **do próprio usuário**.

    Não existe como alterar a de outra pessoa: o alvo é sempre quem está
    logado. Como fica no banco, a barra lateral escolhida acompanha a pessoa em
    qualquer computador em que ela entrar.

    Só os campos enviados são alterados — marcar um favorito não apaga a ordem,
    e reordenar não desmarca nada.
    """
    if body.barra_favoritos is not None:
        limpos = _limpar_lista(body.barra_favoritos)
        user.barra_favoritos = json.dumps(limpos, ensure_ascii=False) if limpos else None

    if body.barra_ordem is not None:
        ordem = _limpar_lista(body.barra_ordem)
        user.barra_ordem = json.dumps(ordem, ensure_ascii=False) if ordem else None

    db.commit()
    return {
        "barra_favoritos": json.loads(user.barra_favoritos) if user.barra_favoritos else [],
        "barra_ordem": json.loads(user.barra_ordem) if user.barra_ordem else [],
        "mensagem": "Preferências salvas",
    }


@router.post("/refresh", response_model=Token)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> Token:
    """Emite um novo par de tokens a partir de um refresh token válido."""
    if payload.refresh_token in _refresh_blacklist:
        raise HTTPException(status_code=401, detail="Refresh token revogado")
    data = decode_token(payload.refresh_token)
    if data is None or data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Refresh token inválido")
    user = db.get(Usuario, int(data["sub"]))
    if user is None or user.deleted_at is not None or not user.ativo:
        raise HTTPException(status_code=401, detail="Usuário inválido")
    # Mesma checagem de identidade do access token.
    if data.get("email") and data["email"] != user.email:
        raise HTTPException(status_code=401, detail="Sessão inválida")

    # Rotação: revoga o refresh anterior.
    _refresh_blacklist.add(payload.refresh_token)

    return Token(
        access_token=create_access_token(user.id, user.papel.value, user.email),
        refresh_token=create_refresh_token(user.id, user.papel.value, user.email),
        user=UsuarioOut.model_validate(user),
    )


@router.post("/logout")
def logout(payload: RefreshRequest, user: Usuario = Depends(get_current_user)) -> dict:
    """Revoga o refresh token informado."""
    _refresh_blacklist.add(payload.refresh_token)
    return {"ok": True}


@router.get("/me", response_model=UsuarioOut)
def me(user: Usuario = Depends(get_current_user)) -> Usuario:
    """Retorna o perfil do usuário autenticado."""
    return user
