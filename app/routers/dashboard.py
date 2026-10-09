"""KPIs por inventário — usados no topo da tela de Relatórios."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_module
from app.core.permissoes import pode_inventario
from app.database import get_db
from app.models.core import Ativo, Usuario
from app.models.enums import Dominio, StatusAtivo
from app.models.impressora import AtivoImpressora, SuprimentoImpressora
from app.models.ti import AtivoTI

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_module("relatorios"))])


@router.get("/stats")
def dashboard_stats(
    dominio: Dominio = Query(default=Dominio.TI),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """KPIs distintos por inventário."""
    if not pode_inventario(user, dominio.value):
        raise HTTPException(403, "Sem acesso a este inventário")

    base = db.query(Ativo).filter(Ativo.deleted_at.is_(None), Ativo.dominio == dominio)
    total = base.count()
    por_status = {s.value: base.filter(Ativo.status == s).count() for s in StatusAtivo}
    alocados = por_status[StatusAtivo.EM_USO.value] + por_status[StatusAtivo.EMPRESTADO.value]

    hoje = date.today()
    garantias = {
        str(d): base.filter(
            Ativo.data_garantia.isnot(None),
            Ativo.data_garantia >= hoje,
            Ativo.data_garantia <= hoje + timedelta(days=d),
        ).count()
        for d in (30, 60, 90)
    }

    extra: dict = {}
    if dominio == Dominio.TI:
        rows = (
            db.query(AtivoTI.so, func.count(AtivoTI.ativo_id))
            .join(Ativo, Ativo.id == AtivoTI.ativo_id)
            .filter(Ativo.deleted_at.is_(None), Ativo.dominio == Dominio.TI)
            .group_by(AtivoTI.so)
            .all()
        )
        extra["por_so"] = {so or "Desconhecido": c for so, c in rows}
        rows = (
            db.query(AtivoTI.ram_gb, func.count(AtivoTI.ativo_id))
            .join(Ativo, Ativo.id == AtivoTI.ativo_id)
            .filter(Ativo.deleted_at.is_(None), Ativo.dominio == Dominio.TI)
            .group_by(AtivoTI.ram_gb)
            .all()
        )
        extra["por_ram"] = {str(r or 0): c for r, c in rows}
    else:
        contador_total = (
            db.query(func.coalesce(func.sum(AtivoImpressora.contador_paginas), 0))
            .join(Ativo, Ativo.id == AtivoImpressora.ativo_id)
            .filter(Ativo.deleted_at.is_(None), Ativo.dominio == Dominio.IMPRESSORA)
            .scalar()
        )
        suprimentos_baixos = (
            db.query(func.count(SuprimentoImpressora.id))
            .join(Ativo, Ativo.id == SuprimentoImpressora.ativo_id)
            .filter(
                Ativo.deleted_at.is_(None),
                Ativo.dominio == Dominio.IMPRESSORA,
                SuprimentoImpressora.deleted_at.is_(None),
                SuprimentoImpressora.estoque_atual <= SuprimentoImpressora.estoque_minimo,
            )
            .scalar()
        )
        valor_total = (
            db.query(func.coalesce(func.sum(Ativo.valor), 0.0))
            .filter(Ativo.deleted_at.is_(None), Ativo.dominio == Dominio.IMPRESSORA)
            .scalar()
        )
        extra["contador_total"] = int(contador_total or 0)
        extra["suprimentos_baixos"] = int(suprimentos_baixos or 0)
        extra["custo_pagina"] = round((valor_total or 0) / contador_total, 4) if contador_total else 0.0

    return {
        "dominio": dominio.value,
        "total": total,
        "alocados": alocados,
        "por_status": por_status,
        "garantias": garantias,
        "extra": extra,
    }
