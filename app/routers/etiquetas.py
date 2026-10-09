"""Templates de etiqueta (Administração → Etiquetas)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin
from app.database import get_db
from app.models.core import TemplateEtiqueta, Usuario
from app.models.enums import Dominio
from app.schemas.common import SemVazios
from app.services.audit_service import audit
from app.services.label_layout import CAMPOS_DISPONIVEIS, normalizar_config

router = APIRouter(prefix="/admin/etiquetas", tags=["etiquetas"])


class TemplateBase(SemVazios):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1, max_length=160)
    descricao: str | None = None
    largura_mm: float = Field(default=100, gt=5, le=1000)
    altura_mm: float = Field(default=50, gt=5, le=1000)
    dpi: int = Field(default=203, ge=72, le=1200)
    dominio: Dominio | None = None
    padrao: bool = False
    config: dict[str, Any] = {}


class TemplateCreate(TemplateBase):
    pass


class TemplateUpdate(TemplateBase):
    pass


class TemplateOut(TemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


@router.get("/campos")
def campos_disponiveis(_: Usuario = Depends(require_admin)) -> dict:
    """Campos que podem ser exibidos na etiqueta."""
    return {"campos": [{"chave": k, "rotulo": v} for k, v in CAMPOS_DISPONIVEIS.items()]}


@router.get("/padrao")
def config_padrao(_: Usuario = Depends(require_admin)) -> dict:
    """Configuração padrão (usada ao criar um template novo)."""
    return {"config": normalizar_config({})}


@router.get("", response_model=list[TemplateOut])
def listar(db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    return (
        db.query(TemplateEtiqueta)
        .filter(TemplateEtiqueta.deleted_at.is_(None))
        .order_by(TemplateEtiqueta.nome)
        .all()
    )


@router.post("", response_model=TemplateOut, status_code=201)
def criar(
    body: TemplateCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)
):
    obj = TemplateEtiqueta(**body.model_dump())
    obj.config = normalizar_config(body.config)
    if obj.padrao:
        _limpar_padrao(db, None)
    db.add(obj)
    db.flush()
    audit(db, user, "create", "template_etiqueta", obj.id, ip=request.client.host if request.client else None, diff=body.model_dump(mode="json"))
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/{template_id}", response_model=TemplateOut)
def atualizar(
    template_id: int, body: TemplateUpdate, request: Request,
    db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
):
    obj = db.get(TemplateEtiqueta, template_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Template não encontrado")
    dados = body.model_dump()
    dados["config"] = normalizar_config(body.config)
    if dados.get("padrao"):
        _limpar_padrao(db, template_id)
    for k, v in dados.items():
        setattr(obj, k, v)
    audit(db, user, "update", "template_etiqueta", obj.id, ip=request.client.host if request.client else None, diff=body.model_dump(mode="json"))
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{template_id}", status_code=204)
def excluir(
    template_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)
):
    obj = db.get(TemplateEtiqueta, template_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Template não encontrado")
    obj.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "template_etiqueta", obj.id, ip=request.client.host if request.client else None)
    db.commit()


def _limpar_padrao(db: Session, exceto_id: int | None) -> None:
    q = db.query(TemplateEtiqueta).filter(TemplateEtiqueta.padrao.is_(True), TemplateEtiqueta.deleted_at.is_(None))
    if exceto_id is not None:
        q = q.filter(TemplateEtiqueta.id != exceto_id)
    q.update({"padrao": False})
