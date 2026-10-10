"""MFA (segunda etapa) — cadastro, confirmação e verificação.

TOTP em biblioteca padrão (`app.services.plataforma`), então **não há
dependência nova**. O segredo só é gravado **depois** que a pessoa confirma um
código: guardar antes deixaria um segredo pendente que ninguém usa, e um
cadastro pela metade é pior que nenhum.

## Por que só administrador

Exigir MFA de todo mundo num sistema de fábrica empurraria as pessoas a
anotarem o código num papel. O ganho de segurança ficaria na aparência. Quem
mexe em permissão, apaga ativo e restaura backup é quem precisa da segunda
etapa.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.core import Usuario
from app.models.enums import PapelUsuario
from app.services import plataforma
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
    user: Usuario = Depends(get_current_user),
):
    """QR Code do endereço `otpauth://` — o que o aplicativo lê.

    Renderizado no servidor porque o `qrcode` já é dependência (é ele que faz
    as etiquetas). Devolver como imagem, e não como texto, é o que torna o
    cadastro "aponte a câmera" em vez de "digite 32 letras e não erre".
    """
    import io as _io

    import qrcode
    from fastapi.responses import Response

    if not user.mfa_segredo:
        raise HTTPException(400, "Inicie a configuração antes de pedir o QR Code.")

    uri = plataforma.uri_otpauth(user.mfa_segredo, user.email)
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
    user: Usuario = Depends(get_current_user),
):
    papel = getattr(user.papel, "value", user.papel)
    return {
        "ativo": bool(user.mfa_ativo),
        "ativado_em": user.mfa_ativado_em,
        "codigos_restantes": len(user.mfa_recuperacao or []),
        "exigido": papel == PapelUsuario.ADMIN.value,
    }


@router.post("/iniciar", response_model=dict)
def iniciar(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Gera um segredo novo e o endereço do QR Code.

    **Não ativa nada.** O segredo fica pendente até alguém provar que o
    aplicativo está configurado, confirmando um código.
    """
    if user.mfa_ativo:
        raise HTTPException(400, "A segunda etapa já está ativa. Desative antes de trocar o aparelho.")

    segredo = plataforma.gerar_segredo()
    user.mfa_segredo = segredo
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
    user: Usuario = Depends(get_current_user),
):
    """Confirma o código e **então** ativa. Devolve os códigos de recuperação."""
    if user.mfa_ativo:
        raise HTTPException(400, "A segunda etapa já está ativa.")
    if not user.mfa_segredo:
        raise HTTPException(400, "Inicie a configuração antes de confirmar.")

    if not plataforma.conferir_codigo(user.mfa_segredo, body.codigo):
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
    db.commit()

    return {
        "ativo": True,
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
    if not user.mfa_ativo:
        raise HTTPException(400, "A segunda etapa não está ativa.")

    if not plataforma.conferir_codigo(user.mfa_segredo or "", body.codigo):
        raise HTTPException(400, "Código incorreto.")

    user.mfa_ativo = False
    user.mfa_segredo = None
    user.mfa_recuperacao = None
    user.mfa_ativado_em = None

    audit(db, user, "desativar_mfa", "usuario", user.id,
          ip=request.client.host if request.client else None)
    db.commit()
    return {"ativo": False}


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
        "valido": plataforma.conferir_codigo(user.mfa_segredo or "", body.codigo),
        "mfa": True,
    }


def consumir_recuperacao(db: Session, user: Usuario, codigo: str) -> bool:
    """Usa um código de recuperação — e o queima.

    Uso único de verdade: o hash sai da lista ao ser usado. Guardar a lista e
    só marcar como usado permitiria reuso em caso de falha no meio.
    """
    restantes = list(user.mfa_recuperacao or [])
    alvo = _hash_recuperacao(codigo)
    if alvo not in restantes:
        return False
    restantes.remove(alvo)
    user.mfa_recuperacao = restantes
    db.commit()
    return True
