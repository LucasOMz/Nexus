"""Movimentações de ativos e consumíveis."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user, require_write
from app.core.pagination import paginate
from app.database import get_db
from app.models.core import Ativo, Movimentacao, Produto, Usuario
from app.models.enums import StatusAtivo, TipoMov
from app.schemas.common import Page
from app.schemas.movimentacoes import MovimentacaoCreate, MovimentacaoOut
from app.services.audit_service import audit

router = APIRouter(prefix="/movimentacoes", tags=["movimentacoes"])

# Efeito colateral no status do ativo conforme o tipo de movimentação.
_ATIVO_STATUS_EFEITO = {
    TipoMov.ATRIBUICAO: StatusAtivo.EM_USO,
    TipoMov.DEVOLUCAO: StatusAtivo.ESTOQUE,
    TipoMov.BAIXA: StatusAtivo.DESCARTADO,
    TipoMov.TRANSFERENCIA: StatusAtivo.ESTOQUE,
}


@router.get("", response_model=Page[MovimentacaoOut])
def list_movimentacoes(
    tipo: TipoMov | None = Query(default=None),
    ativo_id: int | None = Query(default=None),
    produto_id: int | None = Query(default=None),
    data_inicio: datetime | None = Query(default=None),
    data_fim: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    q = db.query(Movimentacao).filter(Movimentacao.deleted_at.is_(None))
    # Carrega os relacionados de uma vez: o histórico mostra nomes, e sem isto
    # cada linha faria sua própria consulta (N+1).
    q = q.options(
        selectinload(Movimentacao.usuario),
        selectinload(Movimentacao.produto),
        selectinload(Movimentacao.ativo),
        # Encadeado: o hostname do equipamento vive na ficha técnica. Sem o
        # segundo nível, cada linha do histórico faria sua própria consulta.
        selectinload(Movimentacao.ativo_instalado).selectinload(Ativo.ti),
    )
    if tipo is not None:
        q = q.filter(Movimentacao.tipo == tipo)
    if ativo_id is not None:
        q = q.filter(Movimentacao.ativo_id == ativo_id)
    if produto_id is not None:
        q = q.filter(Movimentacao.produto_id == produto_id)
    if data_inicio is not None:
        q = q.filter(Movimentacao.data_mov >= data_inicio)
    if data_fim is not None:
        q = q.filter(Movimentacao.data_mov <= data_fim)
    result = paginate(q.order_by(Movimentacao.data_mov.desc()), page, size)
    return Page[MovimentacaoOut](**result)


@router.get("/{mov_id}", response_model=MovimentacaoOut)
def get_movimentacao(mov_id: int, db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    obj = db.get(Movimentacao, mov_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Movimentação não encontrada")
    return obj


@router.post("", response_model=MovimentacaoOut, status_code=201)
def create_movimentacao(
    body: MovimentacaoCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
):
    if body.ativo_id is not None:
        ativo = db.get(Ativo, body.ativo_id)
        if ativo is None or ativo.deleted_at is not None:
            raise HTTPException(404, "Ativo não encontrado")
    else:
        produto = db.get(Produto, body.produto_id)
        if produto is None or produto.deleted_at is not None:
            raise HTTPException(404, "Produto não encontrado")

    # O equipamento que recebeu o consumível precisa existir de verdade.
    if body.ativo_instalado_id is not None:
        equipamento = db.get(Ativo, body.ativo_instalado_id)
        if equipamento is None or equipamento.deleted_at is not None:
            raise HTTPException(404, "Ativo informado para a instalação não encontrado")

    data = body.model_dump()
    data["usuario_id"] = user.id
    mov = Movimentacao(**data)
    db.add(mov)

    # Efeito colateral no status do ativo (movimentações de ativo).
    if body.ativo_id is not None and body.tipo in _ATIVO_STATUS_EFEITO:
        novo_status = _ATIVO_STATUS_EFEITO[body.tipo]
        if ativo.status != StatusAtivo.DESCARTADO:
            ativo.status = novo_status

    db.flush()
    audit(db, user, "create", "movimentacao", mov.id, ip=request.client.host if request.client else None, diff=data)
    db.commit()
    db.refresh(mov)
    return mov
