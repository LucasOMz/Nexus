"""Reporte de erro — canal de retorno durante a implantação.

**Qualquer usuário** autenticado pode enviar (título, descrição e um print
opcional). **Só o administrador** vê a lista do que foi reportado.

Recurso temporário: desligue com `REPORTE_ERRO_ATIVO=false` no `.env`. Com ele
desligado, a tela desaparece do menu e a API recusa novos envios — o que já foi
reportado continua acessível ao administrador.
"""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.core.deps import get_current_user, require_admin
from app.core.planta import planta_ativa
from app.database import get_db
from app.models.core import ReporteErro, Usuario
from app.services.audit_service import audit

router = APIRouter(prefix="/reportes", tags=["reportes"])

REPORTES_DIR = os.path.join(settings.media_dir, "reportes")
TIPOS_IMAGEM = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
TAMANHO_MAX = 8 * 1024 * 1024  # 8 MB

STATUS_VALIDOS = ("aberto", "em_analise", "resolvido", "descartado")
ROTULO_STATUS = {
    "aberto": "Aberto",
    "em_analise": "Em análise",
    "resolvido": "Resolvido",
    "descartado": "Descartado",
}


def _exigir_ativo() -> None:
    if not settings.reporte_erro_ativo:
        raise HTTPException(404, "O reporte de erro está desativado neste sistema.")


def _serializar(r: ReporteErro, incluir_anotacao: bool = True) -> dict:
    dados = {
        "id": r.id,
        "titulo": r.titulo,
        "descricao": r.descricao,
        "tela": r.tela,
        "status": r.status,
        "status_rotulo": ROTULO_STATUS.get(r.status, r.status),
        "tem_imagem": bool(r.imagem),
        "criado_em": (r.created_at.isoformat() + ("" if r.created_at.tzinfo else "+00:00")) if r.created_at else None,
        "usuario_nome": r.usuario_nome,
        "usuario_email": r.usuario_email,
        "planta_sigla": r.planta_sigla,
    }
    # A anotação é do administrador para o administrador: não vai para o autor.
    if incluir_anotacao:
        dados["observacao_admin"] = r.observacao_admin
    return dados


@router.get("/disponivel")
def disponivel(_: Usuario = Depends(get_current_user)) -> dict:
    """A tela de reporte está ligada? (o frontend usa para mostrar ou não o card)"""
    return {"ativo": settings.reporte_erro_ativo}


@router.post("", status_code=201)
async def criar(
    request: Request,
    titulo: str = Form(..., min_length=3, max_length=200),
    descricao: str = Form(..., min_length=5),
    tela: str | None = Form(default=None),
    arquivo: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
) -> dict:
    """Registra um reporte de erro. Disponível para QUALQUER usuário."""
    _exigir_ativo()

    nome_arquivo = None
    mime = None
    if arquivo is not None and arquivo.filename:
        if arquivo.content_type not in TIPOS_IMAGEM:
            raise HTTPException(400, "O print precisa ser uma imagem (PNG, JPG, WEBP ou GIF).")
        conteudo = await arquivo.read()
        if len(conteudo) > TAMANHO_MAX:
            raise HTTPException(400, "O print é grande demais (limite de 8 MB).")
        os.makedirs(REPORTES_DIR, exist_ok=True)
        nome_arquivo = f"{uuid.uuid4().hex}_{os.path.basename(arquivo.filename)}"
        with open(os.path.join(REPORTES_DIR, nome_arquivo), "wb") as fh:
            fh.write(conteudo)
        mime = arquivo.content_type

    reporte = ReporteErro(
        usuario_id=user.id,
        planta_id=planta_id,
        titulo=titulo.strip(),
        descricao=descricao.strip(),
        tela=(tela or "").strip() or None,
        imagem=nome_arquivo,
        mime_type=mime,
        status="aberto",
    )
    db.add(reporte)
    db.flush()

    # O próprio autor não precisa ver a lista, mas fica o registro de quem foi.
    audit(db, user, "reporte_erro", "reporte", reporte.id,
          ip=request.client.host if request.client else None,
          diff={"titulo": reporte.titulo, "tela": reporte.tela, "com_print": bool(nome_arquivo)})
    db.commit()
    db.refresh(reporte)
    return _serializar(reporte)


@router.get("")
def listar(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
) -> dict:
    """Lista os reportes recebidos — **somente administrador**."""
    consulta = db.query(ReporteErro).options(
        selectinload(ReporteErro.usuario), selectinload(ReporteErro.planta)
    )
    if status:
        consulta = consulta.filter(ReporteErro.status == status)

    itens = consulta.order_by(ReporteErro.id.desc()).all()
    por_status = {s: 0 for s in STATUS_VALIDOS}
    for r in db.query(ReporteErro).all():
        por_status[r.status] = por_status.get(r.status, 0) + 1

    return {
        "total": len(itens),
        "por_status": por_status,
        "ativo": settings.reporte_erro_ativo,
        "itens": [_serializar(r) for r in itens],
    }


@router.get("/meus")
def meus(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """Os reportes **do próprio usuário**, com a situação atual.

    A situação é definida pelo administrador na triagem — é o retorno que o
    autor recebe sobre o que reportou. A anotação interna do administrador
    **não** aparece aqui.
    """
    itens = (
        db.query(ReporteErro)
        .options(selectinload(ReporteErro.usuario), selectinload(ReporteErro.planta))
        .filter(ReporteErro.usuario_id == user.id)
        .order_by(ReporteErro.id.desc())
        .all()
    )
    por_status = {s: 0 for s in STATUS_VALIDOS}
    for r in itens:
        por_status[r.status] = por_status.get(r.status, 0) + 1

    return {
        "total": len(itens),
        "por_status": por_status,
        "itens": [_serializar(r, incluir_anotacao=False) for r in itens],
    }


@router.get("/{reporte_id}/imagem")
def imagem(
    reporte_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Print do erro — administrador, ou o próprio autor."""
    r = db.get(ReporteErro, reporte_id)
    if r is None or not r.imagem:
        raise HTTPException(404, "Este reporte não tem print.")
    if user.papel != "admin" and r.usuario_id != user.id:
        raise HTTPException(403, "Sem acesso a este print.")
    caminho = os.path.join(REPORTES_DIR, r.imagem)
    if not os.path.exists(caminho):
        raise HTTPException(404, "Arquivo do print não encontrado.")
    return FileResponse(caminho, media_type=r.mime_type or "image/png")


@router.patch("/{reporte_id}")
def atualizar(
    reporte_id: int,
    request: Request,
    status: str | None = Form(default=None),
    observacao_admin: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> dict:
    """Muda a situação do reporte e/ou anota uma observação — só administrador."""
    r = db.get(ReporteErro, reporte_id)
    if r is None:
        raise HTTPException(404, "Reporte não encontrado")
    if status is not None:
        if status not in STATUS_VALIDOS:
            raise HTTPException(400, f"Situação inválida. Use: {', '.join(STATUS_VALIDOS)}.")
        r.status = status
    if observacao_admin is not None:
        r.observacao_admin = observacao_admin.strip() or None

    audit(db, user, "update", "reporte", r.id,
          ip=request.client.host if request.client else None,
          diff={"status": r.status, "observacao": r.observacao_admin})
    db.commit()
    db.refresh(r)
    return _serializar(r)


@router.delete("/{reporte_id}", status_code=204)
def excluir(
    reporte_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Remove um reporte (e o print) — só administrador."""
    r = db.get(ReporteErro, reporte_id)
    if r is None:
        raise HTTPException(404, "Reporte não encontrado")

    if r.imagem:
        try:
            os.unlink(os.path.join(REPORTES_DIR, r.imagem))
        except OSError:
            pass  # arquivo já não existe: o registro ainda deve sair

    audit(db, user, "delete", "reporte", r.id,
          ip=request.client.host if request.client else None, diff={"titulo": r.titulo})
    db.delete(r)
    db.commit()
