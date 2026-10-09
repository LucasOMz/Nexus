"""Calendário de empréstimos.

Mostra, em visão mensal, quais ativos estão emprestados e até quando — a
"agenda" de devoluções. Alimentado pelos campos de empréstimo do ativo
(`numero_chamado`, `emprestado_em`, `devolucao_prevista`).
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user
from app.core.planta import aplicar_filtro, exigir_planta_do_usuario, planta_ativa
from app.database import get_db
from app.models.core import Ativo, Usuario
from app.models.enums import StatusAtivo

router = APIRouter(prefix="/calendario", tags=["calendario"])


class EmprestimoNoCalendario(BaseModel):
    ativo_id: int
    patrimonio: str
    modelo: str | None = None
    marca: str | None = None
    planta_sigla: str | None = None
    numero_chamado: str | None = None
    emprestado_em: date
    devolucao_prevista: date
    emprestado_para_nome: str | None = None
    localizacao: str | None = None
    atrasado: bool = False
    dias_restantes: int = 0


@router.get("/emprestimos")
def emprestimos(
    inicio: date | None = Query(default=None, description="Primeiro dia do período"),
    fim: date | None = Query(default=None, description="Último dia do período"),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
) -> dict:
    """Empréstimos que **atravessam** o período pedido.

    Um empréstimo de 01/10 a 20/10 aparece em todos os dias entre eles — por
    isso o filtro é por interseção de intervalo, não por data exata.

    Cada usuário vê apenas a **sua planta**; o administrador vê todas.
    """
    planta_id = exigir_planta_do_usuario(user, planta_id)
    hoje = date.today()
    primeiro = inicio or hoje.replace(day=1)
    ultimo = fim or (primeiro + timedelta(days=45))

    consulta = (
        db.query(Ativo)
        .options(selectinload(Ativo.planta), selectinload(Ativo.emprestado_para), selectinload(Ativo.localizacao))
        .filter(
            Ativo.deleted_at.is_(None),
            Ativo.status == StatusAtivo.EMPRESTADO,
            Ativo.devolucao_prevista.isnot(None),
            # Intersecção: começou antes do fim E termina depois do início.
            Ativo.emprestado_em <= ultimo,
            Ativo.devolucao_prevista >= primeiro,
        )
    )
    consulta = aplicar_filtro(consulta, Ativo, planta_id)

    itens = []
    for a in consulta.order_by(Ativo.devolucao_prevista).all():
        prevista = a.devolucao_prevista
        itens.append(
            EmprestimoNoCalendario(
                ativo_id=a.id,
                patrimonio=a.patrimonio,
                modelo=a.modelo,
                marca=a.marca,
                planta_sigla=a.planta_sigla,
                numero_chamado=a.numero_chamado,
                emprestado_em=a.emprestado_em or prevista,
                devolucao_prevista=prevista,
                emprestado_para_nome=a.emprestado_para_nome,
                localizacao=a.localizacao.nome if a.localizacao else None,
                atrasado=prevista < hoje,
                dias_restantes=(prevista - hoje).days,
            )
        )

    # Totais para o topo da tela.
    atrasados = [i for i in itens if i.atrasado]
    vencendo = [i for i in itens if not i.atrasado and i.dias_restantes <= 7]

    return {
        "periodo": {"inicio": primeiro.isoformat(), "fim": ultimo.isoformat()},
        "total": len(itens),
        "atrasados": len(atrasados),
        "vencendo_em_7_dias": len(vencendo),
        "itens": [i.model_dump() for i in itens],
    }


@router.get("/resumo")
def resumo(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
) -> dict:
    """Números do calendário: quantos emprestados, atrasados e devolvidos hoje."""
    planta_id = exigir_planta_do_usuario(user, planta_id)
    hoje = date.today()
    base = db.query(Ativo).filter(
        Ativo.deleted_at.is_(None),
        Ativo.status == StatusAtivo.EMPRESTADO,
        Ativo.devolucao_prevista.isnot(None),
    )
    base = aplicar_filtro(base, Ativo, planta_id)

    emprestados = base.count()
    atrasados = base.filter(Ativo.devolucao_prevista < hoje).count()
    hoje_mesmo = base.filter(Ativo.devolucao_prevista == hoje).count()
    semana = base.filter(
        Ativo.devolucao_prevista >= hoje, Ativo.devolucao_prevista <= hoje + timedelta(days=7)
    ).count()

    # Chamados distintos: um mesmo ticket pode cobrir vários equipamentos.
    chamados = (
        aplicar_filtro(
            db.query(Ativo.numero_chamado).filter(
                Ativo.deleted_at.is_(None),
                Ativo.status == StatusAtivo.EMPRESTADO,
                Ativo.numero_chamado.isnot(None),
            ),
            Ativo,
            planta_id,
        )
        .distinct()
        .count()
    )

    return {
        "emprestados": emprestados,
        "atrasados": atrasados,
        "devolvem_hoje": hoje_mesmo,
        "proximos_7_dias": semana,
        "chamados_abertos": chamados,
    }


@router.get("/busca")
def busca_por_chamado(
    chamado: str = Query(min_length=1),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
) -> list[dict]:
    """Localiza empréstimos pelo número de chamado (ou parte dele)."""
    planta_id = exigir_planta_do_usuario(user, planta_id)
    consulta = (
        db.query(Ativo)
        .options(selectinload(Ativo.planta))
        .filter(
            Ativo.deleted_at.is_(None),
            Ativo.status == StatusAtivo.EMPRESTADO,
            or_(
                Ativo.numero_chamado.ilike(f"%{chamado}%"),
                Ativo.patrimonio.ilike(f"%{chamado}%"),
            ),
        )
    )
    consulta = aplicar_filtro(consulta, Ativo, planta_id)
    return [
        {
            "ativo_id": a.id,
            "patrimonio": a.patrimonio,
            "modelo": a.modelo,
            "numero_chamado": a.numero_chamado,
            "devolucao_prevista": a.devolucao_prevista.isoformat() if a.devolucao_prevista else None,
            "planta_sigla": a.planta_sigla,
        }
        for a in consulta.order_by(Ativo.devolucao_prevista).all()
    ]
