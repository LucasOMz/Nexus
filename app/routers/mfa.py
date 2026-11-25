"""Cadastro, confirmação e verificação do MFA da conta."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core import cripto
from app.core.deps import get_current_user, usuario_para_configurar_mfa
from app.core.primeiro_acesso import mfa_exigido
from app.database import get_db
from app.models.core import Usuario
from app.models.enums import PapelUsuario
from app.routers.auth import emitir_credencial_de_etapa, emitir_sessao
from app.services import plataforma, sessoes
from app.services.audit_service import audit

router = APIRouter(prefix="/mfa", tags=["mfa"])


class CodigoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigo: str = Field(min_length=6, max_length=10)


def _hash_recuperacao(codigo: str) -> str:
    return hashlib.sha256(plataforma.normalizar_codigo_recuperacao(codigo).encode()).hexdigest()


def exigir_admin(user: Usuario) -> None:
    papel = getattr(user.papel, "value", user.papel)
    if papel != PapelUsuario.ADMIN.value:
        raise HTTPException(
            403, "A segunda etapa é exigida de administradores."
        )


@router.get("/qrcode")
def qrcode_imagem(
    db: Session = Depends(get_db),
    user: Usuario = Depends(usuario_para_configurar_mfa),
):
    """QR Code do endereço `otpauth://` — o que o aplicativo lê.

    Renderizado no servidor porque o `qrcode` já é dependência (é ele que faz
    as etiquetas). Devolver como imagem, e não como texto, é o que torna o
    cadastro "aponte a câmera" em vez de "digite 32 letras e não erre".
    """
    import io as _io

    import qrcode
    from fastapi.responses import Response

    if user.mfa_ativo:
        raise HTTPException(404, "QR Code disponível durante o cadastro da segunda etapa.")
    segredo = cripto.decifrar(user.mfa_segredo)
    if not segredo:
        raise HTTPException(400, "Inicie a configuração antes de pedir o QR Code.")

    uri = plataforma.uri_otpauth(segredo, user.email)
    imagem = qrcode.make(uri)
    buffer = _io.BytesIO()
    imagem.save(buffer, format="PNG")

    # Sem cache: o segredo muda a cada início de configuração, e uma imagem
    # guardada mostraria um segredo que já não vale.
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/situacao", response_model=dict)
def situacao(
    db: Session = Depends(get_db),
    user: Usuario = Depends(usuario_para_configurar_mfa),
):
    return {
        "ativo": bool(user.mfa_ativo),
        "ativado_em": user.mfa_ativado_em,
        "codigos_restantes": len(user.mfa_recuperacao or []),
        "exigido": mfa_exigido(user),
    }


@router.post("/iniciar", response_model=dict)
def iniciar(
    db: Session = Depends(get_db),
    user: Usuario = Depends(usuario_para_configurar_mfa),
):
    """Gera um segredo novo e o endereço do QR Code.

    **Não ativa nada.** O segredo fica pendente até alguém provar que o
    aplicativo está configurado, confirmando um código.
    """
    db.refresh(user, with_for_update={"of": Usuario})
    if user.senha_temporaria:
        raise HTTPException(401, "Troque a senha antes de configurar a segunda etapa.")
    if user.mfa_ativo:
        raise HTTPException(400, "A segunda etapa já está ativa. Desative antes de trocar o aparelho.")

    segredo = plataforma.gerar_segredo()
    user.mfa_segredo = cripto.cifrar(segredo)
    db.commit()

    return {
        "segredo": segredo,
        "uri": plataforma.uri_otpauth(segredo, user.email),
        "instrucoes": (
            "Abra o aplicativo autenticador, aponte para o QR Code e informe o "
            "código de 6 dígitos para confirmar."
        ),
    }


@router.post("/confirmar", response_model=dict)
def confirmar(
    body: CodigoIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(usuario_para_configurar_mfa),
):
    """Confirma o código e **então** ativa. Devolve os códigos de recuperação."""
    db.refresh(user, with_for_update={"of": Usuario})
    if user.senha_temporaria:
        raise HTTPException(401, "Troque a senha antes de configurar a segunda etapa.")
    if user.mfa_ativo:
        raise HTTPException(400, "A segunda etapa já está ativa.")
    segredo = cripto.decifrar(user.mfa_segredo)
    if not segredo:
        raise HTTPException(400, "Inicie a configuração antes de confirmar.")

    if not plataforma.conferir_codigo(segredo, body.codigo):
        raise HTTPException(
            400,
            "Código incorreto. Confira o relógio do celular e tente o código atual.",
        )

    codigos = plataforma.gerar_codigos_de_recuperacao()
    user.mfa_ativo = True
    user.mfa_ativado_em = datetime.now(timezone.utc)
    user.mfa_recuperacao = [_hash_recuperacao(c) for c in codigos]

    audit(db, user, "ativar_mfa", "usuario", user.id,
          ip=request.client.host if request.client else None)
    sessoes.revogar_do_usuario(db, user)
    sessao = emitir_sessao(db, user)
    db.commit()

    return {
        "ativo": True,
        "sessao": sessao,
        "codigos_recuperacao": codigos,
        "aviso": (
            "Guarde estes códigos. Cada um serve UMA vez e é a única forma de "
            "entrar se você perder o celular. Eles não serão mostrados de novo."
        ),
    }


@router.post("/desativar", response_model=dict)
def desativar(
    body: CodigoIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Desativa mediante um código válido.

    Exigir o código (e não só a sessão) evita que alguém que encontrou uma
    máquina destravada desligue a proteção da conta.
    """
    db.refresh(user, with_for_update={"of": Usuario})
    if not user.mfa_ativo:
        raise HTTPException(400, "A segunda etapa não está ativa.")

    if not plataforma.conferir_codigo(cripto.decifrar(user.mfa_segredo) or "", body.codigo):
        if not consumir_recuperacao(db, user, body.codigo):
            raise HTTPException(400, "Código incorreto.")

    user.mfa_ativo = False
    user.mfa_segredo = None
    user.mfa_recuperacao = None
    user.mfa_ativado_em = None
    sessoes.revogar_do_usuario(db, user)

    audit(db, user, "desativar_mfa", "usuario", user.id,
          ip=request.client.host if request.client else None)
    sessao = (
        emitir_credencial_de_etapa(db, user, "cadastrar_mfa") if mfa_exigido(user)
        else emitir_sessao(db, user)
    )
    db.commit()
    return {"ativo": False, "sessao": sessao}


@router.post("/verificar", response_model=dict)
def verificar(
    body: CodigoIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Confere um código sem alterar nada — a segunda etapa do login."""
    if not user.mfa_ativo:
        return {"valido": True, "mfa": False}
    return {
        "valido": plataforma.conferir_codigo(cripto.decifrar(user.mfa_segredo) or "", body.codigo),
        "mfa": True,
    }


def consumir_recuperacao(db: Session, user: Usuario, codigo: str) -> bool:
    """Usa um código de recuperação — e o queima.

    Bloqueia a linha até o chamador confirmar a transação.
    """
    armazenados = (
        db.query(Usuario.mfa_recuperacao).filter(Usuario.id == user.id).with_for_update(of=Usuario).scalar()
    )
    restantes = list(armazenados or [])
    alvo = _hash_recuperacao(codigo)
    if alvo not in restantes:
        return False
    restantes.remove(alvo)
    user.mfa_recuperacao = restantes
    return True
