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
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core import cripto
from app.core.deps import get_current_user, oauth2_scheme, usuario_para_troca_de_senha
from app.core.primeiro_acesso import (
    Etapa,
    etapa_pendente,
)
from app.core.rate_limit import login_limiter
from app.core.security import (
    SETUP_TTL,
    create_access_token,
    create_refresh_token,
    create_setup_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.segredos_instalacao import SENHAS_ADMIN_PADRAO_ANTIGAS
from app.database import get_db
from app.models.core import Usuario
from app.models.enums import PapelUsuario
from app.schemas.auth import PoliticaSessao, RefreshRequest, Token, TrocaSenhaIn
from app.schemas.common import UsuarioOut
from app.services import sessoes
from app.services.audit_service import audit
from app.services.config_service import obter_config
from app.services.ldap_service import autenticar

router = APIRouter(prefix="/auth", tags=["auth"])

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


def _par_de_tokens(user: Usuario, sid: str) -> Token:
    argumentos = {"mfa_verificado": user.mfa_ativo, "sessao_id": sid}
    return Token(
        access_token=create_access_token(user.id, user.papel.value, user.email, **argumentos),
        refresh_token=create_refresh_token(user.id, user.papel.value, user.email, **argumentos),
        user=UsuarioOut.model_validate(user),
    )


def emitir_sessao(db: Session, user: Usuario) -> Token:
    """Registra a sessão na transação que conclui a autenticação."""
    sid = uuid4().hex
    par = _par_de_tokens(user, sid)
    sessoes.registrar(db, sid, user.id, timedelta(days=settings.refresh_token_expire_days), par.refresh_token)
    return par


def emitir_credencial_de_etapa(db: Session, user: Usuario, etapa: Etapa, mensagem: str | None = None) -> Token:
    sid = uuid4().hex
    sessoes.registrar(db, sid, user.id, SETUP_TTL)
    return Token(
        access_token=create_setup_token(user.id, user.papel.value, user.email, etapa, sid),
        user=UsuarioOut.model_validate(user),
        acao_requerida=etapa,
        acao_mensagem=mensagem,
    )


@router.post("/login", response_model=Token)
def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    codigo_form: Annotated[str | None, Form(alias="codigo")] = None,
    # Compatibilidade com clientes que enviavam o código na query.
    codigo: str | None = Query(default=None),
) -> Token:
    """Autentica o usuário e emite access + refresh tokens.

    `username` aceita o e-mail (contas locais) ou o login do AD
    (`sAMAccountName`), conforme o filtro configurado.
    """
    client_ip = request.client.host if request.client else "unknown"
    if not login_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde um instante.",
                            headers={"Retry-After": str(login_limiter.window_seconds)})
    codigo = codigo_form or codigo

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
    revogacao_antes = user.forcar_logout_em if user is not None else None
    resultado_ad = None

    if user is not None and user.origem == "local":
        # Conta local (inclui o root/admin): senha do sistema, sem AD.
        if not verify_password(form.password, user.senha_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_ERRO_GENERICO)
        if (
            settings.env.lower() == "production"
            and user.papel == PapelUsuario.ADMIN
            and form.password in SENHAS_ADMIN_PADRAO_ANTIGAS
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_ERRO_GENERICO)
    else:
        autenticado = False
        # O AD serve para confirmar QUEM é a pessoa (a senha de rede). Se ela
        # pode entrar, e com qual perfil, é decidido aqui no cadastro.
        if cfg.ldap_ativo:
            if user is not None and user.login_ad:
                resultado = autenticar(cfg, user.login_ad, form.password, email_alternativo=user.email)
            else:
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
                resultado_ad = resultado
        # Compatibilidade: conta que existe localmente e não é do AD.
        if not autenticado and user is not None and user.origem != "ad":
            if verify_password(form.password, user.senha_hash):
                autenticado = True
        if not autenticado:
            # Mensagem única: não revela se o usuário existe ou não.
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_ERRO_GENERICO)

    # A redefinição do MFA revoga sessões sob o mesmo bloqueio. Caso uma
    # revogação tenha ocorrido durante a autenticação, recomece o login.
    db.refresh(user, with_for_update={"of": Usuario})
    if user.deleted_at is not None or user.forcar_logout_em != revogacao_antes:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_ERRO_GENERICO)
    if not user.ativo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário inativo")
    if resultado_ad is not None:
        _sincronizar_nome_do_ad(user, resultado_ad)

    # --- modo manutenção --------------------------------------------------
    #
    # A checagem vem DEPOIS da senha: quem não acertou a senha recebe o erro
    # genérico e não descobre, pela mensagem de manutenção, que o usuário
    # existe.
    #
    # O administrador entra mesmo com o modo ligado — é ele que vai desligar.
    # 503 e não 403: o frontend mostra a tela de manutenção com o texto
    # escrito pelo administrador, em vez de um "acesso negado" seco.
    papel_do_login = getattr(user.papel, "value", user.papel)
    if papel_do_login != "admin":
        from app.services import manutencao as _manutencao

        if _manutencao.esta_ativa(db):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=_manutencao.mensagem(db),
                headers={"Retry-After": "60"},
            )

    # --- Primeiro acesso e segunda etapa ---------------------------------
    # A ordem importa. Trocar a senha vem ANTES do MFA: enquanto a senha for a
    # que o administrador definiu, ela e conhecida por outra pessoa - proteger
    # com MFA uma senha compartilhada nao protege nada.
    #
    acao = etapa_pendente(user)
    mensagem = None

    if acao == "trocar_senha":
        mensagem = "Sua senha foi definida pelo administrador. Escolha uma senha sua para continuar."

    elif user.mfa_ativo:
        # MFA ja cadastrado: agora sim exige o codigo, sem emitir token util.
        from app.routers.mfa import consumir_recuperacao
        from app.services import plataforma as _plataforma

        if not codigo:
            # Fica DEPOIS de a senha ser conferida: pedir o codigo antes
            # revelaria quais contas tem MFA, sem ninguem ter provado nada.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="mfa_necessario"
            )

        if not _plataforma.conferir_codigo(cripto.decifrar(user.mfa_segredo) or "", codigo):
            # Nao sendo TOTP, pode ser um codigo de recuperacao (uso unico).
            if not consumir_recuperacao(db, user, codigo):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Codigo de verificacao invalido.",
                )

    elif acao == "cadastrar_mfa":
        mensagem = (
            "Sua verificação em duas etapas foi redefinida. Cadastre o aplicativo autenticador para continuar."
            if user.mfa_recadastro_pendente
            else "Bem-vindo! Antes de usar o sistema, cadastre a verificação em duas etapas com o aplicativo autenticador."
        )

    audit(db, user, "login", "usuario", user.id, ip=client_ip)
    token = emitir_credencial_de_etapa(db, user, acao, mensagem) if acao is not None else emitir_sessao(db, user)
    db.commit()
    return token


TEMAS_VALIDOS = {"light", "dark"}
# Paletas de cor — os MESMOS valores de `[data-paleta="..."]` no CSS.
# Separadas do tema porque são decisões independentes: claro/escuro é
# iluminação do ambiente, paleta é identidade visual.
PALETAS_VALIDAS = {"nexus", "azul", "roxo", "ambar", "classico"}
# Cor de FUNDO — o terceiro eixo, independente do destaque.
FUNDOS_VALIDOS = {"verde", "neutro", "azul", "areia"}


class PreferenciasUpdate(BaseModel):
    """Preferências de interface do próprio usuário."""

    model_config = ConfigDict(extra="forbid")

    barra_favoritos: list[str] | None = None
    barra_padrao: bool = False
    # Ordem da lista inteira da gaveta. Separada dos favoritos: quem reordena
    # mexe em todas as linhas, não só nas marcadas.
    barra_ordem: list[str] | None = None
    # Tema de interface. Fica no servidor, e não só no navegador, para a
    # preferência acompanhar a PESSOA — quem troca de computador não deveria
    # reconfigurar a tela.
    tema: str | None = None
    # Cor de destaque, independente do claro/escuro.
    paleta: str | None = None
    # Cor de fundo, independente do destaque e do modo.
    fundo: str | None = None


def _limpar_lista(itens: list[str] | None) -> list[str]:
    """Limita quantidade e tamanho: é preferência de tela, não campo livre."""
    return [str(m).strip()[:40] for m in (itens or []) if str(m).strip()][:80]


# Regras da senha, em um lugar só — a tela e o servidor dizem a mesma coisa.
SENHA_MINIMA = 8
SENHAS_PROIBIDAS = {
    "admin123", "12345678", "senha123", "password", "123456789",
    "mudar123", "trocar123", "qwerty123",
}


def _validar_senha_nova(senha: str, nome: str | None = None) -> None:
    """Recusa senha fraca — e explica o porquê, em vez de só negar."""
    if len(senha or "") < SENHA_MINIMA:
        raise HTTPException(400, f"A senha precisa de pelo menos {SENHA_MINIMA} caracteres.")
    if senha.lower() in SENHAS_PROIBIDAS:
        raise HTTPException(400, "Esta senha é fácil de adivinhar. Escolha outra.")
    if senha.isdigit():
        raise HTTPException(400, "Use letras e números, não só números.")
    primeiro = (nome or "").strip().split(" ")[0].lower()
    if primeiro and len(primeiro) >= 4 and primeiro in senha.lower():
        raise HTTPException(400, "A senha não pode conter o seu nome.")


@router.post("/trocar-senha", response_model=dict)
def trocar_senha(
    body: TrocaSenhaIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(usuario_para_troca_de_senha),
) -> dict:
    """Troca a senha do próprio usuário.

    Serve para o primeiro acesso (senha temporária criada pelo administrador) e
    para a troca voluntária. Nas duas, exige a senha atual: sessão aberta numa
    máquina destravada não pode virar troca de senha.
    """
    db.refresh(user, with_for_update={"of": Usuario})
    if body.senha_nova != body.confirmacao:
        raise HTTPException(400, "A confirmação não confere com a senha nova.")
    if not verify_password(body.senha_atual, user.senha_hash):
        raise HTTPException(400, "A senha atual não confere.")
    if body.senha_nova == body.senha_atual:
        raise HTTPException(400, "A senha nova precisa ser diferente da atual.")

    _validar_senha_nova(body.senha_nova, user.nome)

    if user.origem == "ad" and not user.senha_hash:
        # Conta de AD não tem senha local para trocar; quem manda é o domínio.
        raise HTTPException(
            400, "Sua conta usa a senha da rede. Troque-a no domínio, não aqui."
        )

    sessoes.revogar_do_usuario(db, user)
    user.senha_hash = hash_password(body.senha_nova)
    user.senha_temporaria = False          # cumpriu a exigência do primeiro acesso
    if user.primeiro_acesso_em is None:
        user.primeiro_acesso_em = datetime.now(timezone.utc)

    audit(db, user, "trocar_senha", "usuario", user.id,
          ip=request.client.host if request.client else None)
    db.commit()

    # O que ainda falta depois da troca: cadastrar o MFA, se exigido.
    proxima = etapa_pendente(user)
    return {
        "ok": True,
        "acao_requerida": proxima,
        "mensagem": (
            "Senha alterada. Agora cadastre a verificação em duas etapas."
            if proxima else "Senha alterada com sucesso."
        ),
    }


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
    if body.barra_padrao:
        user.barra_favoritos = None
        user.barra_ordem = None
    elif body.barra_favoritos is not None:
        limpos = _limpar_lista(body.barra_favoritos)
        user.barra_favoritos = json.dumps(limpos, ensure_ascii=False)

    if not body.barra_padrao and body.barra_ordem is not None:
        ordem = _limpar_lista(body.barra_ordem)
        user.barra_ordem = json.dumps(ordem, ensure_ascii=False) if ordem else None

    if body.tema is not None:
        # Lista fechada: um valor inventado deixaria a tela sem estilo nenhum,
        # porque não haveria bloco de CSS correspondente.
        escolhido = str(body.tema).strip().lower()
        if escolhido not in TEMAS_VALIDOS:
            raise HTTPException(
                400, f"Tema desconhecido. Use um destes: {', '.join(sorted(TEMAS_VALIDOS))}."
            )
        user.tema = escolhido

    if body.paleta is not None:
        escolhida = str(body.paleta).strip().lower()
        if escolhida not in PALETAS_VALIDAS:
            raise HTTPException(
                400, f"Paleta desconhecida. Use uma destas: {', '.join(sorted(PALETAS_VALIDAS))}."
            )
        user.paleta = escolhida

    if body.fundo is not None:
        escolhido_fundo = str(body.fundo).strip().lower()
        if escolhido_fundo not in FUNDOS_VALIDOS:
            raise HTTPException(
                400, f"Fundo desconhecido. Use um destes: {', '.join(sorted(FUNDOS_VALIDOS))}."
            )
        user.fundo = escolhido_fundo

    db.commit()
    return {
        "barra_favoritos": json.loads(user.barra_favoritos) if user.barra_favoritos else [],
        "barra_personalizada": user.barra_personalizada,
        "barra_ordem": json.loads(user.barra_ordem) if user.barra_ordem else [],
        "tema": user.tema,
        "paleta": user.paleta,
        "fundo": user.fundo,
        "mensagem": "Preferências salvas",
    }


@router.post("/refresh", response_model=Token)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> Token:
    """Emite um novo par de tokens a partir de um refresh token válido."""
    data = _ler_refresh(payload.refresh_token)
    user = db.get(Usuario, int(data["sub"]))
    if user is None or user.deleted_at is not None or not user.ativo:
        raise HTTPException(status_code=401, detail="Usuário inválido")
    # Mesma checagem de identidade do access token.
    if data.get("email") and data["email"] != user.email:
        raise HTTPException(status_code=401, detail="Sessão inválida")
    if etapa_pendente(user) is not None or (user.mfa_ativo and data.get("mfa_verificado") is not True):
        raise HTTPException(status_code=401, detail="Entre novamente para concluir a autenticação")

    sid = data["sid"]
    novo = _par_de_tokens(user, sid)
    if not sessoes.renovar(
        db, sid, user.id, payload.refresh_token, novo.refresh_token,
        timedelta(days=settings.refresh_token_expire_days),
    ):
        # Um refresh já usado encerra a sessão, inclusive o par mais recente.
        sessoes.revogar(db, sid, user.id)
        db.commit()
        raise HTTPException(status_code=401, detail="Sessão encerrada. Entre novamente.")
    db.commit()
    return novo


def _ler_refresh(token: str) -> dict:
    dados = decode_token(token)
    if (
        dados is None or dados.get("type") != "refresh"
        or not isinstance(dados.get("sid"), str) or not isinstance(dados.get("jti"), str)
        or not isinstance(dados.get("sub"), str) or not dados["sub"].isdigit()
    ):
        raise HTTPException(status_code=401, detail="Refresh token inválido")
    return dados


@router.post("/logout")
def logout(payload: RefreshRequest, db: Session = Depends(get_db)) -> dict:
    """O refresh assinado autoriza encerrar a própria sessão, mesmo com access expirado."""
    dados = _ler_refresh(payload.refresh_token)
    sessoes.revogar(db, dados["sid"], int(dados["sub"]))
    db.commit()
    return {"ok": True}


@router.get("/me", response_model=UsuarioOut)
def me(user: Usuario = Depends(get_current_user)) -> Usuario:
    """Retorna o perfil do usuário autenticado."""
    return user


@router.get("/politica-sessao", response_model=PoliticaSessao)
def ler_politica_sessao(db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)) -> PoliticaSessao:
    return PoliticaSessao(inatividade_minutos=sessoes.inatividade_minutos(db))


@router.post("/atividade", status_code=204)
def registrar_atividade(
    atraso_ms: Annotated[int, Query(ge=0, le=30000)] = 0,
    user: Usuario = Depends(get_current_user),
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> None:
    """Registra uma interação explícita, independente das consultas em segundo plano."""
    sid = (decode_token(token or "") or {}).get("sid")
    if not isinstance(sid, str) or not sessoes.registrar_atividade(db, sid, user.id, atraso_ms):
        raise HTTPException(401, "Sessão encerrada. Entre novamente.", headers={"WWW-Authenticate": "Bearer"})
    db.commit()
