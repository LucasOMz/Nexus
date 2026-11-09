"""Consultas sobre o software instalado nos computadores.

## O que a tela precisa

A lista principal **nao pode repetir o mesmo programa por versao**: com
3.000 maquinas, "Google Chrome" apareceria 40 vezes.

Por isso a listagem agrupa por **nome** e devolve a contagem de versoes e de
maquinas. O detalhe abre as versoes, e cada versao lista as maquinas.

## Custo

Sao `GROUP BY` sobre `softwares_instalados`, que pode ter centenas de milhares
de linhas. A agregacao fica no banco — trazer as linhas para agrupar em Python
seria trafegar 450 mil registros por consulta.

O indice `ix_softwares_instalados_nome` cobre o agrupamento.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import require_module
from app.core.planta import planta_ativa
from app.database import get_db
from app.models.core import Ativo, Usuario
from app.models.software import SoftwareInstalado

router = APIRouter(tags=["software instalado"])


def _escopo(db: Session, planta: int | None):
    """Consulta base: software ativo, das maquinas da planta visivel."""
    base = (
        db.query(SoftwareInstalado)
        .join(Ativo, SoftwareInstalado.ativo_id == Ativo.id)
        .filter(
            SoftwareInstalado.deleted_at.is_(None),
            Ativo.deleted_at.is_(None),
        )
    )

    if planta is not None:
        base = base.filter(Ativo.planta_id == planta)

    return base


@router.get("/softwares/instalados")
def listar_instalados(
    busca: str | None = Query(default=None, max_length=120),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_module("software")),
    planta: int | None = Depends(planta_ativa),
) -> list[dict]:
    """Programas instalados, **um por nome**.

    Devolve quantas versoes diferentes existem e em quantas maquinas o
    programa aparece. O detalhe por versao fica em `/instalados/{nome}`.
    """
    q = _escopo(db, planta)

    if busca:
        q = q.filter(SoftwareInstalado.nome.ilike(f"%{busca.lower()}%"))

    # `func.lower` agrupa "Google Chrome" e "google chrome" juntos. Sem isso,
    # uma máquina com o nome em caixa diferente viraria dois programas.
    nome = func.lower(SoftwareInstalado.nome)

    linhas = (
        q.with_entities(
            func.min(SoftwareInstalado.nome).label("nome"),
            func.count(func.distinct(SoftwareInstalado.versao)).label("versoes"),
            func.count(func.distinct(SoftwareInstalado.ativo_id)).label("pcs"),
        )
        .group_by(nome)
        .order_by(func.min(SoftwareInstalado.nome))
        .all()
    )

    return [
        {"nome": n, "versoes": v, "pcs": p}
        for n, v, p in linhas
    ]


@router.get("/softwares/instalados/{nome}")
def detalhar_instalado(
    nome: str,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_module("software")),
    planta: int | None = Depends(planta_ativa),
) -> dict:
    """Versoes de um programa e as maquinas que tem cada uma.

    O `nome` vem da URL e é comparado sem diferenciar maiúsculas — a tela
    manda o nome que mostrou, e ele pode ter vindo com a caixa de qualquer
    máquina.
    """
    q = _escopo(db, planta).filter(
        func.lower(SoftwareInstalado.nome) == nome.strip().lower()
    )

    linhas = (
        q.with_entities(
            SoftwareInstalado.versao,
            SoftwareInstalado.ativo_id,
            Ativo.patrimonio,
            Ativo.numero_serie,
        )
        .order_by(SoftwareInstalado.versao, Ativo.patrimonio)
        .all()
    )

    if not linhas:
        return {"nome": nome, "versoes": []}

    from app.models.ti import AtivoTI

    # Hostname numa consulta só — evita N+1 ao montar a lista de máquinas.
    ids = {r[1] for r in linhas}
    nomes: dict[int, str] = {}
    for ativo_id, hostname in (
        db.query(AtivoTI.ativo_id, AtivoTI.hostname).filter(AtivoTI.ativo_id.in_(ids)).all()
    ):
        nomes[ativo_id] = hostname

    por_versao: dict[str, list[dict]] = {}
    for versao, ativo_id, patrimonio, serie in linhas:
        chave = versao or ""
        por_versao.setdefault(chave, []).append({
            "ativo_id": ativo_id,
            "patrimonio": patrimonio,
            "numero_serie": serie,
            "hostname": nomes.get(ativo_id),
        })

    return {
        "nome": linhas[0][0] or nome,
        "versoes": [
            {
                "versao": v,
                "pcs": sorted(pcs, key=lambda x: (x["hostname"] or x["patrimonio"] or "")),
            }
            for v, pcs in sorted(por_versao.items(), key=lambda kv: kv[0], reverse=True)
        ],
    }
