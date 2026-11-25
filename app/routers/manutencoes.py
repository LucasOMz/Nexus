"""Manutenções com transições de status, histórico e anexos.

Regra de negócio central: abrir manutenção move o ativo para `manutencao`;
concluir/cancelar restaura o status anterior (em_uso se havia atribuição,
senão estoque) — reflete os triggers documentados em schema.sql.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import get_current_user, require_delete, require_write
from app.core.pagination import paginate
from app.core.planta import aplicar_filtro, planta_ativa_obrigatoria
from app.core.uploads import MAX_ANEXO, ler_arquivo, validar_anexo
from app.database import get_db
from app.models.core import Anexo, Ativo, Manutencao, Movimentacao, Usuario
from app.models.enums import StatusAtivo, StatusManut, TipoMov
from app.schemas.common import Page
from app.schemas.manutencoes import ManutencaoCreate, ManutencaoOut, ManutencaoUpdate
from app.services.audit_service import audit

router = APIRouter(prefix="/manutencoes", tags=["manutencoes"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _restaurar_status_ativo(db: Session, ativo: Ativo) -> str:
    """Restaura o status do ativo após conclusão/cancelamento da manutenção."""
    tinha_atribuicao = (
        db.query(Movimentacao)
        .filter(
            Movimentacao.ativo_id == ativo.id,
            Movimentacao.tipo == TipoMov.ATRIBUICAO,
            Movimentacao.deleted_at.is_(None),
        )
        .first()
        is not None
    )
    novo = StatusAtivo.EM_USO if tinha_atribuicao else StatusAtivo.ESTOQUE
    ativo.status = novo
    return novo.value


def _consulta_manutencoes(db: Session, planta: int | None):
    q = db.query(Manutencao).filter(Manutencao.deleted_at.is_(None))
    if planta is not None:
        q = q.filter(
            Manutencao.ativo_id.in_(select(Ativo.id).where(
                Ativo.planta_id == planta, Ativo.deleted_at.is_(None)
            ))
        )
    return q


def _buscar_manutencao(db: Session, manut_id: int, planta: int | None) -> Manutencao:
    manut = _consulta_manutencoes(db, planta).filter(Manutencao.id == manut_id).first()
    if manut is None:
        raise HTTPException(404, "Manutenção não encontrada")
    return manut


@router.get("", response_model=Page[ManutencaoOut])
def list_manutencoes(
    ativo_id: int | None = Query(default=None),
    status: StatusManut | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta: int | None = Depends(planta_ativa_obrigatoria),
):
    q = _consulta_manutencoes(db, planta)
    if ativo_id is not None:
        q = q.filter(Manutencao.ativo_id == ativo_id)
    if status is not None:
        q = q.filter(Manutencao.status == status)
    result = paginate(q.order_by(Manutencao.data_abertura.desc()), page, size)
    return Page[ManutencaoOut](**result)


@router.get("/{manut_id}", response_model=ManutencaoOut)
def get_manutencao(
    manut_id: int, db: Session = Depends(get_db), _: Usuario = Depends(get_current_user),
    planta: int | None = Depends(planta_ativa_obrigatoria),
):
    return _buscar_manutencao(db, manut_id, planta)


@router.post("", response_model=ManutencaoOut, status_code=201)
def create_manutencao(
    body: ManutencaoCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write),
    planta: int | None = Depends(planta_ativa_obrigatoria),
):
    q = db.query(Ativo).filter(Ativo.id == body.ativo_id, Ativo.deleted_at.is_(None))
    ativo = aplicar_filtro(q, Ativo, planta).first()
    if ativo is None:
        raise HTTPException(404, "Ativo não encontrado")
    if ativo.status == StatusAtivo.DESCARTADO:
        raise HTTPException(400, "Ativo descartado não pode ir para manutenção")

    manut = Manutencao(**body.model_dump())
    db.add(manut)
    db.flush()
    # Abrir manutenção → status do ativo vira manutencao.
    ativo.status = StatusAtivo.MANUTENCAO
    audit(db, user, "create", "manutencao", manut.id, ip=_ip(request), diff=body.model_dump())
    db.commit()
    db.refresh(manut)
    return manut


@router.patch("/{manut_id}", response_model=ManutencaoOut)
def update_manutencao(
    manut_id: int, body: ManutencaoUpdate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write),
    planta: int | None = Depends(planta_ativa_obrigatoria),
):
    manut = _buscar_manutencao(db, manut_id, planta)
    data = body.model_dump(exclude_unset=True)
    novo_status = data.get("status")

    # Concluir EXIGE comentário (o que foi feito / laudo). A validação fica aqui
    # e não só na tela: a tela pode ser contornada, a regra de negócio não.
    if novo_status == StatusManut.CONCLUIDA:
        comentario = (data.get("comentario_conclusao") or manut.comentario_conclusao or "").strip()
        if not comentario:
            raise HTTPException(
                400,
                "Informe um comentário do que foi feito para concluir a manutenção.",
            )
        data["comentario_conclusao"] = comentario

    for k, v in data.items():
        setattr(manut, k, v)

    if novo_status in (StatusManut.CONCLUIDA, StatusManut.CANCELADA):
        manut.data_conclusao = manut.data_conclusao or datetime.now(timezone.utc)
        # Registra AUTOMATICAMENTE quem fechou a ordem, pelo usuário logado.
        if manut.concluido_por_id is None:
            manut.concluido_por_id = user.id
        _restaurar_status_ativo(db, manut.ativo)
    elif novo_status in (StatusManut.ABERTA, StatusManut.EM_ANDAMENTO):
        manut.ativo.status = StatusAtivo.MANUTENCAO
        # Reabrir a ordem limpa a conclusão anterior.
        manut.data_conclusao = None
        manut.concluido_por_id = None
        manut.comentario_conclusao = None

    audit(db, user, "update", "manutencao", manut.id, ip=_ip(request), diff=data)
    db.commit()
    db.refresh(manut)
    return manut


@router.delete("/{manut_id}", status_code=204)
def delete_manutencao(
    manut_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_delete),
    planta: int | None = Depends(planta_ativa_obrigatoria),
):
    manut = _buscar_manutencao(db, manut_id, planta)
    manut.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "manutencao", manut.id, ip=_ip(request))
    db.commit()


# ---------------------------------------------------------------------------
# Anexos
# ---------------------------------------------------------------------------
@router.post("/{manut_id}/anexos")
def upload_anexo(
    manut_id: int,
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
    planta: int | None = Depends(planta_ativa_obrigatoria),
):
    _buscar_manutencao(db, manut_id, planta)

    conteudo = ler_arquivo(file, MAX_ANEXO)
    nome = (file.filename or "arquivo").replace("\\", "/").rsplit("/", 1)[-1]
    mime, extensao = validar_anexo(conteudo, nome)
    radical = "".join(c for c in Path(nome).stem if c.isprintable()).strip(" .") or "arquivo"
    pasta = Path(settings.media_dir) / "anexos"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / uuid4().hex
    anexo = Anexo(
        entidade="manutencao",
        entidade_id=manut_id,
        nome_arquivo=f"{radical[:240]}{extensao}",
        caminho=str(destino),
        mime_type=mime,
        tamanho=len(conteudo),
        uploaded_by=user.id,
    )
    try:
        destino.write_bytes(conteudo)
        db.add(anexo)
        audit(db, user, "anexo", "manutencao", manut_id, ip=_ip(request), diff={"arquivo": anexo.nome_arquivo})
        db.commit()
    except Exception:
        db.rollback()
        destino.unlink(missing_ok=True)
        raise
    db.refresh(anexo)
    return {"id": anexo.id, "nome_arquivo": anexo.nome_arquivo, "tamanho": anexo.tamanho, "mime_type": anexo.mime_type}


@router.get("/{manut_id}/anexos")
def list_anexos(
    manut_id: int, db: Session = Depends(get_db), _: Usuario = Depends(get_current_user),
    planta: int | None = Depends(planta_ativa_obrigatoria),
):
    _buscar_manutencao(db, manut_id, planta)
    return db.query(Anexo).filter(Anexo.entidade == "manutencao", Anexo.entidade_id == manut_id, Anexo.deleted_at.is_(None)).all()


@router.get("/{manut_id}/anexos/{anexo_id}/download")
def download_anexo(
    manut_id: int, anexo_id: int, db: Session = Depends(get_db), _: Usuario = Depends(get_current_user),
    planta: int | None = Depends(planta_ativa_obrigatoria),
):
    _buscar_manutencao(db, manut_id, planta)
    anexo = (
        db.query(Anexo)
        .filter(Anexo.id == anexo_id, Anexo.entidade == "manutencao", Anexo.entidade_id == manut_id, Anexo.deleted_at.is_(None))
        .first()
    )
    if anexo is None or not os.path.exists(anexo.caminho):
        raise HTTPException(404, "Anexo não encontrado")
    return FileResponse(anexo.caminho, media_type=anexo.mime_type or "application/octet-stream",
                        filename=anexo.nome_arquivo, headers={"Cache-Control": "private, no-store"})
