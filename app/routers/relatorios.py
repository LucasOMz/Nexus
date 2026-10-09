"""Relatórios em CSV/PDF e filtros salvos por usuário."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.core import (
    Ativo,
    FiltroSalvo,
    Manutencao,
    Movimentacao,
    Produto,
    Usuario,
)
from app.models.enums import Dominio, TipoMov
from app.schemas.relatorios import FiltroSalvoCreate, FiltroSalvoOut, FiltroSalvoUpdate
from app.services.audit_service import audit
from app.services.pdf_service import build_relatorio_pdf

router = APIRouter(prefix="/relatorios", tags=["relatorios"])


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (date, datetime)):
        return v.strftime("%d/%m/%Y %H:%M" if isinstance(v, datetime) else "%d/%m/%Y")
    if hasattr(v, "value"):
        return str(v.value)
    return str(v)


def _respond_csv(headers: list[str], rows: list[list[Any]], filename: str) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_fmt(c) for c in row])
    # utf-8-sig (BOM) para abrir corretamente no Excel.
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _respond_pdf(titulo: str, headers: list[str], rows: list[list[Any]], filename: str, subtitulo: str = "") -> Response:
    pdf = build_relatorio_pdf(titulo, headers, rows, subtitulo)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _deliver(
    formato: str, filename: str, titulo: str, headers: list[str], rows: list[list[Any]], subtitulo: str = ""
) -> Response:
    if formato == "pdf":
        return _respond_pdf(titulo, headers, rows, filename, subtitulo)
    return _respond_csv(headers, rows, filename)


# ---------------------------------------------------------------------------
# Relatórios
# ---------------------------------------------------------------------------
@router.get("/inventario")
def relatorio_inventario(
    dominio: Dominio = Query(default=Dominio.TI),
    status: str | None = Query(default=None),
    formato: str = Query(default="csv"),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    q = db.query(Ativo).filter(Ativo.deleted_at.is_(None), Ativo.dominio == dominio)
    if status:
        q = q.filter(Ativo.status == status)
    ativos = q.order_by(Ativo.patrimonio).all()

    headers = ["Patrimônio", "Modelo", "Marca", "S/N", "Status", "Localização", "Departamento", "Garantia", "Valor"]
    rows = []
    for a in ativos:
        rows.append([
            a.patrimonio, a.modelo, a.marca, a.numero_serie, a.status.value,
            a.localizacao.nome if a.localizacao else "",
            a.departamento.nome if a.departamento else "",
            a.data_garantia, a.valor,
        ])
    return _deliver(formato, f"inventario_{dominio.value}.{formato}", "Inventário de Ativos", headers, rows, f"Domínio: {dominio.value}")


@router.get("/ativos-por-usuario")
def relatorio_ativos_por_usuario(
    formato: str = Query(default="csv"),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    rows_q = (
        db.query(Usuario.nome, Ativo.patrimonio, Ativo.modelo, Movimentacao.data_mov)
        .join(Movimentacao, Movimentacao.destino_usuario_id == Usuario.id)
        .join(Ativo, Ativo.id == Movimentacao.ativo_id)
        .filter(Movimentacao.tipo == TipoMov.ATRIBUICAO, Movimentacao.deleted_at.is_(None))
        .order_by(Usuario.nome, Ativo.patrimonio)
        .all()
    )
    headers = ["Colaborador", "Patrimônio", "Modelo", "Data Atribuição"]
    rows = [[r[0], r[1], r[2], r[3]] for r in rows_q]
    return _deliver(formato, f"ativos_por_usuario.{formato}", "Ativos por Usuário", headers, rows)


@router.get("/movimentacoes")
def relatorio_movimentacoes(
    data_inicio: datetime | None = Query(default=None),
    data_fim: datetime | None = Query(default=None),
    formato: str = Query(default="csv"),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    q = db.query(Movimentacao).filter(Movimentacao.deleted_at.is_(None))
    if data_inicio:
        q = q.filter(Movimentacao.data_mov >= data_inicio)
    if data_fim:
        q = q.filter(Movimentacao.data_mov <= data_fim)
    movs = q.order_by(Movimentacao.data_mov.desc()).all()
    headers = ["Data", "Tipo", "Ativo", "Produto", "Qtd", "Origem", "Destino", "Observações"]
    rows = []
    for m in movs:
        rows.append([
            m.data_mov, m.tipo.value,
            m.ativo.patrimonio if m.ativo else "",
            m.produto.nome if m.produto else "",
            m.quantidade,
            m.origem_localizacao_id, m.destino_localizacao_id, m.observacoes,
        ])
    return _deliver(formato, f"movimentacoes.{formato}", "Movimentações", headers, rows)


@router.get("/manutencoes")
def relatorio_manutencoes(
    formato: str = Query(default="csv"),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    manuts = (
        db.query(Manutencao).filter(Manutencao.deleted_at.is_(None)).order_by(Manutencao.data_abertura.desc()).all()
    )
    headers = ["Ativo", "Status", "Abertura", "Conclusão", "Fornecedor", "Custo", "Técnico"]
    rows = [
        [
            m.ativo.patrimonio if m.ativo else m.ativo_id, m.status.value, m.data_abertura,
            m.data_conclusao, m.fornecedor.nome if m.fornecedor else "", m.custo, m.tecnico,
        ]
        for m in manuts
    ]
    return _deliver(formato, f"manutencoes.{formato}", "Manutenções", headers, rows)


@router.get("/garantias")
def relatorio_garantias(
    dias: int = Query(default=90, ge=1, le=365),
    formato: str = Query(default="csv"),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    hoje = date.today()
    limite = hoje + timedelta(days=dias)
    ativos = (
        db.query(Ativo)
        .filter(
            Ativo.deleted_at.is_(None),
            Ativo.data_garantia.isnot(None),
            Ativo.data_garantia >= hoje,
            Ativo.data_garantia <= limite,
        )
        .order_by(Ativo.data_garantia)
        .all()
    )
    headers = ["Patrimônio", "Modelo", "Domínio", "Garantia", "Dias restantes"]
    rows = [
        [a.patrimonio, a.modelo, a.dominio.value, a.data_garantia, (a.data_garantia - hoje).days] for a in ativos
    ]
    return _deliver(formato, f"garantias.{formato}", f"Garantias ({dias} dias)", headers, rows)


@router.get("/consumiveis-minimo")
def relatorio_consumiveis_minimo(
    dominio: Dominio = Query(default=Dominio.TI),
    formato: str = Query(default="csv"),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    # Saldo derivado: entradas - saídas, comparado ao estoque mínimo.
    saldo = func.coalesce(
        func.sum(
            case(
                (Movimentacao.tipo == TipoMov.ENTRADA, Movimentacao.quantidade),
                (Movimentacao.tipo == TipoMov.SAIDA, -Movimentacao.quantidade),
                else_=0,
            )
        ),
        0,
    )
    produtos = (
        db.query(Produto, saldo.label("saldo"))
        .outerjoin(Movimentacao, Movimentacao.produto_id == Produto.id)
        .filter(Produto.deleted_at.is_(None), Produto.dominio == dominio, Produto.estoque_minimo > 0)
        .group_by(Produto.id)
        .order_by(Produto.nome)
        .all()
    )
    headers = ["SKU", "Nome", "Saldo", "Mínimo", "Situação"]
    rows = [
        [p.sku, p.nome, saldo_v, p.estoque_minimo, "ABAIXO DO MÍNIMO" if saldo_v <= p.estoque_minimo else "ok"]
        for p, saldo_v in produtos
    ]
    return _deliver(formato, f"consumiveis_minimo.{formato}", "Consumíveis abaixo do mínimo", headers, rows)


# ---------------------------------------------------------------------------
# Filtros salvos
# ---------------------------------------------------------------------------
@router.get("/filtros", response_model=list[FiltroSalvoOut])
def list_filtros(db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)):
    return (
        db.query(FiltroSalvo)
        .filter(FiltroSalvo.usuario_id == user.id, FiltroSalvo.deleted_at.is_(None))
        .order_by(FiltroSalvo.created_at.desc())
        .all()
    )


@router.post("/filtros", response_model=FiltroSalvoOut, status_code=201)
def create_filtro(
    body: FiltroSalvoCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)
):
    obj = FiltroSalvo(usuario_id=user.id, **body.model_dump())
    db.add(obj)
    db.flush()
    audit(db, user, "create", "filtro", obj.id, ip=request.client.host if request.client else None, diff=body.model_dump())
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/filtros/{filtro_id}", response_model=FiltroSalvoOut)
def update_filtro(
    filtro_id: int, body: FiltroSalvoUpdate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)
):
    obj = db.get(FiltroSalvo, filtro_id)
    if obj is None or obj.deleted_at is not None or obj.usuario_id != user.id:
        raise HTTPException(404, "Filtro não encontrado")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(obj, k, v)
    audit(db, user, "update", "filtro", obj.id, ip=request.client.host if request.client else None, diff=body.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/filtros/{filtro_id}", status_code=204)
def delete_filtro(
    filtro_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(get_current_user)
):
    obj = db.get(FiltroSalvo, filtro_id)
    if obj is None or obj.deleted_at is not None or obj.usuario_id != user.id:
        raise HTTPException(404, "Filtro não encontrado")
    obj.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "filtro", obj.id, ip=request.client.host if request.client else None)
    db.commit()
