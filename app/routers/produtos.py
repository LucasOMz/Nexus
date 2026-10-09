"""CRUD de produtos (consumíveis e itens de estoque)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_write
from app.core.pagination import paginate, parse_pagination
from app.database import get_db
from app.models.core import Produto, Usuario
from app.models.enums import Dominio
from app.schemas.common import Page as PageModel
from app.schemas.produtos import ProdutoCreate, ProdutoOut, ProdutoUpdate
from app.services.audit_service import audit

router = APIRouter(prefix="/produtos", tags=["produtos"])


@router.get("", response_model=PageModel[ProdutoOut])
def list_produtos(
    dominio: Dominio | None = Query(default=None),
    search: str | None = Query(default=None),
    categoria_id: int | None = Query(default=None),
    abaixo_minimo: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    q = db.query(Produto).filter(Produto.deleted_at.is_(None))
    if dominio is not None:
        q = q.filter(Produto.dominio == dominio)
    if categoria_id is not None:
        q = q.filter(Produto.categoria_id == categoria_id)
    if search:
        like = f"%{search}%"
        q = q.filter(or_(Produto.nome.ilike(like), Produto.sku.ilike(like), Produto.descricao.ilike(like)))
    if abaixo_minimo:
        # Consumíveis cujo estoque efetivo (movimentações) está abaixo do mínimo.
        q = q.filter(Produto.estoque_minimo > 0)
    _, _, sort_field, sort_dir = parse_pagination(page, size, None)
    result = paginate(q.order_by(Produto.nome), page, size)
    return PageModel[ProdutoOut](**result)


@router.get("/{produto_id}", response_model=ProdutoOut)
def get_produto(produto_id: int, db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    obj = db.get(Produto, produto_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Produto não encontrado")
    return obj


@router.post("", response_model=ProdutoOut, status_code=201)
def create_produto(
    body: ProdutoCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
):
    if db.query(Produto).filter(Produto.sku == body.sku, Produto.deleted_at.is_(None)).first():
        raise HTTPException(409, "SKU já cadastrado")
    obj = Produto(**body.model_dump())
    db.add(obj)
    db.flush()
    audit(db, user, "create", "produto", obj.id, ip=request.client.host if request.client else None, diff=body.model_dump())
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/{produto_id}", response_model=ProdutoOut)
def update_produto(
    produto_id: int, body: ProdutoUpdate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
):
    obj = db.get(Produto, produto_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Produto não encontrado")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    audit(db, user, "update", "produto", obj.id, ip=request.client.host if request.client else None, diff=body.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{produto_id}", status_code=204)
def delete_produto(
    produto_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
):
    obj = db.get(Produto, produto_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Produto não encontrado")
    obj.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "produto", obj.id, ip=request.client.host if request.client else None)
    db.commit()
