"""Camada financeira — endpoints de leitura.

Junta os dados que já existem (`Ativo`, `Manutencao`, `Movimentacao`,
`Produto`, `Departamento`, `LeituraContador`) e entrega os cálculos do serviço
`financeiro`. **Só lê**: nenhum valor é gravado ou recalculado no banco, porque
depreciação é derivada — guardá-la só criaria dado velho para manter.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.planta import aplicar_filtro, planta_ativa
from app.database import get_db
from app.models.core import Ativo, Departamento, Manutencao, Movimentacao, Produto, Usuario
from app.models.impressora import LeituraContador
from app.services import financeiro

router = APIRouter(prefix="/financeiro", tags=["financeiro"])


# ---------------------------------------------------------------------------
def _custos_de_manutencao(db: Session, planta_id: int | None) -> dict[int, float]:
    """Soma o custo de manutenção por ativo, numa consulta só."""
    q = (
        db.query(Manutencao.ativo_id, func.sum(Manutencao.custo))
        .filter(Manutencao.deleted_at.is_(None), Manutencao.custo.isnot(None))
        .group_by(Manutencao.ativo_id)
    )
    return {aid: float(total or 0) for aid, total in q.all() if aid is not None}


def _custos_de_consumivel(db: Session, planta_id: int | None) -> dict[int, float]:
    """Consumível instalado em cada ativo: quantidade × preço unitário.

    Usa o vínculo criado na saída com finalidade "instalação" — é ele que diz
    qual tonner foi para qual impressora.
    """
    q = (
        db.query(
            Movimentacao.ativo_instalado_id,
            func.sum(Movimentacao.quantidade * func.coalesce(Produto.preco_unitario, 0)),
        )
        .join(Produto, Produto.id == Movimentacao.produto_id)
        .filter(
            Movimentacao.deleted_at.is_(None),
            Movimentacao.ativo_instalado_id.isnot(None),
        )
        .group_by(Movimentacao.ativo_instalado_id)
    )
    return {aid: float(total or 0) for aid, total in q.all() if aid is not None}


def _ativos(db: Session, planta_id: int | None, dominio: str | None = None) -> list[Ativo]:
    q = db.query(Ativo).filter(Ativo.deleted_at.is_(None))
    q = aplicar_filtro(q, Ativo, planta_id)
    if dominio:
        q = q.filter(Ativo.dominio == dominio)
    return q.all()


def _montar(db: Session, ativos: list[Ativo]) -> list[dict]:
    """Converte os ativos no formato que o serviço financeiro entende."""
    manut = _custos_de_manutencao(db, None)
    consum = _custos_de_consumivel(db, None)
    deps = {d.id: (d.sigla or d.nome) for d in db.query(Departamento).all()}

    saida = []
    for a in ativos:
        saida.append({
            "ativo_id": a.id,
            "patrimonio": a.patrimonio,
            "modelo": a.modelo,
            "marca": a.marca,
            "dominio": getattr(a.dominio, "value", a.dominio),
            "valor": float(a.valor or 0),
            "data_aquisicao": a.data_aquisicao.isoformat() if a.data_aquisicao else None,
            "data_garantia": a.data_garantia.isoformat() if a.data_garantia else None,
            "departamento": deps.get(a.departamento_id),
            "custo_manutencao": manut.get(a.id, 0.0),
            "custo_consumiveis": consum.get(a.id, 0.0),
        })
    return saida


def _paginado(itens: list, page: int, size: int) -> dict:
    total = len(itens)
    ini = (page - 1) * size
    return {
        "items": itens[ini:ini + size],
        "total": total,
        "page": page,
        "size": size,
        "pages": max(1, (total + size - 1) // size),
    }


# ---------------------------------------------------------------------------
@router.get("/resumo")
def resumo(
    dominio: str | None = Query(default=None, pattern="^(ti|impressora)$"),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    """Números do parque: valor hoje, depreciação, TCO e garantias."""
    itens = _montar(db, _ativos(db, planta_id, dominio))
    return financeiro.resumo_do_parque(itens)


@router.get("/depreciacao")
def depreciacao(
    dominio: str | None = Query(default=None, pattern="^(ti|impressora)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    """Valor atual de cada ativo, do mais depreciado para o menos."""
    itens = _montar(db, _ativos(db, planta_id, dominio))

    saida = []
    for it in itens:
        d = financeiro.depreciacao(it["valor"], it["data_aquisicao"], dominio=it["dominio"])
        saida.append({**{k: it[k] for k in ("ativo_id", "patrimonio", "modelo",
                                            "marca", "dominio", "departamento")}, **d})

    saida.sort(key=lambda x: x.get("percentual_depreciado", 0), reverse=True)
    return _paginado(saida, page, size)


@router.get("/garantias")
def garantias(
    dias: int = Query(default=90, ge=1, le=730,
                      description="Janela de atenção, em dias"),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    """Garantias vencendo — o que evita pagar reparo que estava coberto."""
    itens = _montar(db, _ativos(db, planta_id))

    saida = []
    for it in itens:
        g = financeiro.garantia(it["data_garantia"])
        if g["situacao"] in ("nao_informada", "vencida"):
            continue
        if g["dias_restantes"] is not None and g["dias_restantes"] > dias:
            continue
        saida.append({
            "ativo_id": it["ativo_id"], "patrimonio": it["patrimonio"],
            "modelo": it["modelo"], "marca": it["marca"],
            "departamento": it["departamento"], "valor": it["valor"], **g,
        })

    saida.sort(key=lambda x: x["dias_restantes"] or 0)
    return {"itens": saida, "total": len(saida), "janela_dias": dias}


@router.get("/tco")
def tco(
    dominio: str | None = Query(default=None, pattern="^(ti|impressora)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    """Custo total de propriedade por ativo — do mais caro para o mais barato."""
    itens = _montar(db, _ativos(db, planta_id, dominio))

    saida = []
    for it in itens:
        t = financeiro.tco(
            it["valor"],
            custo_manutencao=it["custo_manutencao"],
            custo_consumiveis=it["custo_consumiveis"],
            data_aquisicao=it["data_aquisicao"],
        )
        saida.append({**{k: it[k] for k in ("ativo_id", "patrimonio", "modelo",
                                            "marca", "dominio", "departamento")}, **t})

    saida.sort(key=lambda x: x["total"], reverse=True)
    return _paginado(saida, page, size)


@router.get("/rateio")
def rateio(
    dominio: str | None = Query(default=None, pattern="^(ti|impressora)$"),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    """Quanto cada centro de custo consome — para cobrar do departamento certo."""
    itens = _montar(db, _ativos(db, planta_id, dominio))
    return {"itens": financeiro.rateio_por_departamento(itens)}


@router.get("/custo-por-pagina")
def custo_por_pagina(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    """Custo por página das impressoras — o diferencial do sistema.

    Usa o **contador real** de cada impressora. O preço do tonner vem do
    consumível instalado nela (saída com finalidade "instalação"); sem esse
    vínculo, a linha sai marcada como incompleta em vez de mentir um número.
    """
    itens = _montar(db, _ativos(db, planta_id, "impressora"))
    manut = {i["ativo_id"]: i["custo_manutencao"] for i in itens}
    consum = {i["ativo_id"]: i["custo_consumiveis"] for i in itens}

    # Páginas por impressora: do menor ao maior contador já lido.
    contadores = (
        db.query(
            LeituraContador.ativo_id,
            func.min(LeituraContador.contador),
            func.max(LeituraContador.contador),
        )
        .filter(LeituraContador.deleted_at.is_(None))
        .group_by(LeituraContador.ativo_id)
        .all()
    )
    paginas = {
        aid: int((mx or 0) - (mn or 0)) for aid, mn, mx in contadores if aid is not None
    }

    saida = []
    for it in itens:
        aid = it["ativo_id"]
        pag = paginas.get(aid, 0)
        # O tonner médio sai do consumível gasto dividido pelas páginas do
        # período: é o custo REAL, não o de catálogo.
        custo_consumivel = consum.get(aid, 0.0)
        cpp_real = (custo_consumivel / pag) if pag > 0 and custo_consumivel > 0 else None

        d = financeiro.custo_por_pagina(
            custo_tonner=None, rendimento_paginas=None,
            custo_manutencao=manut.get(aid, 0.0),
            paginas_impressas=pag,
            custo_aquisicao=it["valor"],
            vida_util_paginas=100_000 if it["valor"] else None,
        )
        if cpp_real is not None:
            d["custo_por_pagina_consumivel_real"] = round(cpp_real, 4)
            partes = [x for x in (d["custo_por_pagina_total"], cpp_real) if x is not None]
            d["custo_por_pagina_total"] = round(sum(partes), 4)
            d["completo"] = True

        saida.append({
            "ativo_id": aid, "patrimonio": it["patrimonio"],
            "modelo": it["modelo"], "marca": it["marca"],
            "departamento": it["departamento"],
            "custo_consumiveis": custo_consumivel, **d,
        })

    # Só as que têm número confiável entram no ranking.
    confiaveis = [x for x in saida if x.get("custo_por_pagina_total") is not None]
    confiaveis.sort(key=lambda x: x["custo_por_pagina_total"], reverse=True)
    sem_dados = [x for x in saida if x.get("custo_por_pagina_total") is None]

    return {**_paginado(confiaveis, page, size), "sem_dados": len(sem_dados)}
