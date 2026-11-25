"""Plantas / localidades — cadastro e consulta.

Cada planta é um inventário próprio: os ativos e as etiquetas carregam
`planta_id`, e o usuário só trabalha na planta dele. O administrador enxerga
todas e escolhe qual está vendo pelo seletor do topo.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin
from app.database import get_db
from app.models.core import Ativo, Planta, PlantaLocalidade, QRZerado, Usuario
from app.models.enums import PapelUsuario
from app.services.audit_service import audit

router = APIRouter(tags=["plantas"])


class PlantaBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=2, max_length=160)
    sigla: str = Field(min_length=2, max_length=20)
    cnpj: str | None = Field(default=None, max_length=18)
    endereco: str | None = Field(default=None, max_length=200)
    cidade: str | None = Field(default=None, max_length=120)
    uf: str | None = Field(default=None, max_length=2)
    observacoes: str | None = None
    ativa: bool = True
    codigos_localidade: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("codigos_localidade")
    @classmethod
    def normalizar_codigos(cls, valores: list[str]) -> list[str]:
        codigos = [valor.strip() for valor in valores]
        if any(re.fullmatch(r"[A-Za-z]{3}", codigo) is None for codigo in codigos):
            raise ValueError("Cada código de localidade deve ter três letras, como TAT ou MTZ.")
        return sorted({codigo.upper() for codigo in codigos})


class PlantaCreate(PlantaBase):
    pass


class PlantaUpdate(PlantaBase):
    pass


class PlantaOut(PlantaBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    total_ativos: int = 0
    total_usuarios: int = 0


def _serializar(db: Session, planta: Planta) -> PlantaOut:
    """Planta com a contagem de ativos e usuários (para a tela de administração)."""
    dados = PlantaOut.model_validate(planta)
    dados.total_ativos = db.query(func.count(Ativo.id)).filter(
        Ativo.planta_id == planta.id, Ativo.deleted_at.is_(None)
    ).scalar() or 0
    dados.total_usuarios = db.query(func.count(Usuario.id)).filter(
        Usuario.planta_id == planta.id, Usuario.deleted_at.is_(None)
    ).scalar() or 0
    return dados


def _atribuir_localidades(db: Session, planta: Planta, codigos: list[str]) -> None:
    if codigos:
        conflito = db.query(PlantaLocalidade).filter(PlantaLocalidade.codigo.in_(codigos))
        if planta.id is not None:
            conflito = conflito.filter(PlantaLocalidade.planta_id != planta.id)
        outra = conflito.first()
        if outra:
            raise HTTPException(409, f"O código de localidade {outra.codigo} já está vinculado à planta {outra.planta.sigla}.")
    atuais = {localidade.codigo: localidade for localidade in planta.localidades_hostname}
    planta.localidades_hostname = [atuais[codigo] if codigo in atuais else PlantaLocalidade(codigo=codigo) for codigo in codigos]


def _gravar_planta(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A sigla ou um código de localidade já está em uso. Reabra a planta para conferir.") from exc


@router.get("/admin/plantas", response_model=list[PlantaOut])
def listar(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)) -> list[PlantaOut]:
    """Todas as plantas, com quantos ativos e usuários cada uma tem."""
    plantas = db.query(Planta).order_by(Planta.nome).all()
    return [_serializar(db, p) for p in plantas]


@router.post("/admin/plantas", response_model=PlantaOut, status_code=201)
def criar(
    body: PlantaCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)
) -> PlantaOut:
    sigla = body.sigla.strip().upper()
    if db.query(Planta).filter(func.upper(Planta.sigla) == sigla).first():
        raise HTTPException(409, f"Já existe uma planta com a sigla {sigla}.")

    planta = Planta(**{**body.model_dump(exclude={"codigos_localidade"}), "sigla": sigla})
    _atribuir_localidades(db, planta, body.codigos_localidade)
    db.add(planta)
    _gravar_planta(db)
    audit(db, user, "create", "planta", planta.id, ip=request.client.host if request.client else None,
          diff={"nome": planta.nome, "sigla": planta.sigla, "codigos_localidade": body.codigos_localidade})
    db.commit()
    db.refresh(planta)
    return _serializar(db, planta)


@router.put("/admin/plantas/{planta_id}", response_model=PlantaOut)
def atualizar(
    planta_id: int, body: PlantaUpdate, request: Request,
    db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
) -> PlantaOut:
    planta = db.query(Planta).filter(Planta.id == planta_id).with_for_update().first()
    if planta is None:
        raise HTTPException(404, "Planta não encontrada")

    sigla = body.sigla.strip().upper()
    conflito = (
        db.query(Planta)
        .filter(func.upper(Planta.sigla) == sigla, Planta.id != planta_id)
        .first()
    )
    if conflito:
        raise HTTPException(409, f"Já existe outra planta com a sigla {sigla}.")

    if "codigos_localidade" in body.model_fields_set:
        _atribuir_localidades(db, planta, body.codigos_localidade)
    for chave, valor in {**body.model_dump(exclude={"codigos_localidade"}), "sigla": sigla}.items():
        setattr(planta, chave, valor)

    _gravar_planta(db)
    audit(db, user, "update", "planta", planta.id,
          ip=request.client.host if request.client else None, diff=body.model_dump(mode="json", exclude_unset=True))
    db.commit()
    db.refresh(planta)
    return _serializar(db, planta)


@router.delete("/admin/plantas/{planta_id}", status_code=204)
def excluir(
    planta_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)
):
    """Exclui a planta — somente se ela não tiver ativos nem usuários.

    Apagar uma planta com dados dentro deixaria registros órfãos. Para tirar de
    circulação sem perder o histórico, use `ativa = false`.
    """
    planta = db.get(Planta, planta_id)
    if planta is None:
        raise HTTPException(404, "Planta não encontrada")

    ativos = db.query(func.count(Ativo.id)).filter(
        Ativo.planta_id == planta_id, Ativo.deleted_at.is_(None)
    ).scalar() or 0
    usuarios = db.query(func.count(Usuario.id)).filter(
        Usuario.planta_id == planta_id, Usuario.deleted_at.is_(None)
    ).scalar() or 0

    if ativos or usuarios:
        raise HTTPException(
            409,
            f"A planta {planta.sigla} tem {ativos} ativo(s) e {usuarios} usuário(s). "
            "Transfira ou remova esses registros antes, ou desmarque 'Ativa' para "
            "tirá-la de circulação sem perder o histórico.",
        )

    if db.query(QRZerado).filter(QRZerado.planta_id == planta_id).count():
        db.query(QRZerado).filter(QRZerado.planta_id == planta_id).delete()

    audit(db, user, "delete", "planta", planta_id,
          ip=request.client.host if request.client else None, diff={"sigla": planta.sigla})
    db.delete(planta)
    db.commit()


@router.get("/plantas/opcoes", response_model=list[dict])
def opcoes(db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)) -> list[dict]:
    """Plantas ativas, para escolher como **destino** de uma transferência.

    Disponível para QUALQUER usuário autenticado: o técnico precisa ver as
    plantas de destino, mas `/admin/plantas` é restrito ao administrador (e
    devolvia 403, deixando a lista vazia — parecia que não havia outra planta).

    Traz só o necessário (id, sigla, nome): CNPJ e contagens são dados
    administrativos e não têm uso aqui.
    """
    plantas = db.query(Planta).filter(Planta.ativa.is_(True)).order_by(Planta.nome).all()
    return [{"id": p.id, "sigla": p.sigla, "nome": p.nome} for p in plantas]


@router.get("/plantas/minhas", response_model=list[PlantaOut])
def minhas(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)) -> list[PlantaOut]:
    """Plantas que o usuário pode escolher no seletor do topo.

    Administrador recebe todas as ativas (e a tela ainda oferece "Todas").
    Usuário comum recebe apenas a planta dele.
    """
    if user.papel == PapelUsuario.ADMIN:
        plantas = db.query(Planta).filter(Planta.ativa.is_(True)).order_by(Planta.nome).all()
        return [_serializar(db, p) for p in plantas]

    if user.planta_id is None:
        return []
    planta = db.get(Planta, user.planta_id)
    return [_serializar(db, planta)] if planta is not None and planta.ativa else []
