"""Dados agregados para os gráficos dos relatórios (módulo `relatorios`).

Retorna séries prontas para o frontend desenhar em SVG, sem dependências
externas. Todos os agrupamentos respeitam o inventário selecionado.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_module
from app.core.permissoes import pode_inventario
from app.database import get_db
from app.models.core import (
    Ativo,
    Categoria,
    Departamento,
    Localizacao,
    Manutencao,
    Movimentacao,
    Produto,
    Usuario,
)
from app.models.enums import Dominio, TipoMov
from app.models.impressora import AtivoImpressora, SuprimentoImpressora
from app.models.ti import AtivoTI

router = APIRouter(
    prefix="/relatorios/graficos",
    tags=["relatorios"],
    dependencies=[Depends(require_module("relatorios"))],
)

ROTULO_STATUS = {
    "estoque": "Em estoque",
    "reservado": "Reservado",
    "em_uso": "Em uso",
    "manutencao": "Manutenção",
    "descartado": "Descartado",
    "emprestado": "Emprestado",
}
ROTULO_MANUT = {"aberta": "Aberta", "em_andamento": "Em andamento", "concluida": "Concluída", "cancelada": "Cancelada"}


def _serie(rows: list[tuple], rotulos: dict[str, str] | None = None) -> list[dict]:
    """Converte [(chave, valor)] em [{rotulo, valor}] ordenado desc, sem nulos."""
    saida = []
    for chave, valor in rows:
        if chave is None or valor in (None, 0):
            continue
        rotulo = rotulos.get(str(chave), str(chave)) if rotulos else str(chave)
        saida.append({"rotulo": rotulo, "valor": valor})
    return sorted(saida, key=lambda x: x["valor"], reverse=True)


@router.get("")
def graficos(
    dominio: Dominio = Query(default=Dominio.TI),
    meses: int = Query(default=6, ge=1, le=24),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    if not pode_inventario(user, dominio.value):
        raise HTTPException(403, "Sem acesso a este inventário")

    base = db.query(Ativo).filter(Ativo.deleted_at.is_(None), Ativo.dominio == dominio)
    ativo_ids = [a.id for a in base.with_entities(Ativo.id).all()]

    # 1) Ativos por status.
    rows = (
        db.query(Ativo.status, func.count(Ativo.id))
        .filter(Ativo.deleted_at.is_(None), Ativo.dominio == dominio)
        .group_by(Ativo.status)
        .all()
    )
    status = _serie([(getattr(s, "value", s), c) for s, c in rows], ROTULO_STATUS)

    # 2) Ativos por categoria.
    rows = (
        db.query(Categoria.nome, func.count(Ativo.id))
        .outerjoin(Ativo, (Ativo.categoria_id == Categoria.id) & (Ativo.deleted_at.is_(None)) & (Ativo.dominio == dominio))
        .group_by(Categoria.nome)
        .all()
    )
    categoria = _serie([(n, c) for n, c in rows if c])

    # 3) Ativos por localização.
    rows = (
        db.query(Localizacao.nome, func.count(Ativo.id))
        .outerjoin(Ativo, (Ativo.localizacao_id == Localizacao.id) & (Ativo.deleted_at.is_(None)) & (Ativo.dominio == dominio))
        .group_by(Localizacao.nome)
        .all()
    )
    localizacao = _serie([(n, c) for n, c in rows if c])

    # 4) Ativos por departamento.
    rows = (
        db.query(Departamento.nome, func.count(Ativo.id))
        .outerjoin(Ativo, (Ativo.departamento_id == Departamento.id) & (Ativo.deleted_at.is_(None)) & (Ativo.dominio == dominio))
        .group_by(Departamento.nome)
        .all()
    )
    departamento = _serie([(n, c) for n, c in rows if c])

    # 5) Valor patrimonial por categoria.
    rows = (
        db.query(Categoria.nome, func.coalesce(func.sum(Ativo.valor), 0))
        .outerjoin(Ativo, (Ativo.categoria_id == Categoria.id) & (Ativo.deleted_at.is_(None)) & (Ativo.dominio == dominio))
        .group_by(Categoria.nome)
        .all()
    )
    valor_categoria = _serie([(n, float(v or 0)) for n, v in rows if v])

    # 6) Garantias a vencer.
    hoje = date.today()
    garantias = [
        {
            "rotulo": f"{d} dias",
            "valor": base.filter(
                Ativo.data_garantia.isnot(None),
                Ativo.data_garantia >= hoje,
                Ativo.data_garantia <= hoje + timedelta(days=d),
            ).count(),
        }
        for d in (30, 60, 90)
    ]

    # 7) Movimentações por mês (entradas x saídas) — agrupado em Python (portável).
    limite = datetime.now(timezone.utc) - timedelta(days=31 * meses)
    movs = (
        db.query(Movimentacao.tipo, Movimentacao.data_mov, Movimentacao.ativo_id, Movimentacao.produto_id)
        .filter(Movimentacao.deleted_at.is_(None), Movimentacao.data_mov >= limite)
        .all()
    )
    # Domínios por id, para filtrar movimentações do inventário atual.
    ids_produto = {p.id: getattr(p.dominio, "value", p.dominio) for p in db.query(Produto).all()}
    set_ativos = set(ativo_ids)
    buckets: dict[str, dict[str, int]] = {}
    for tipo, data_mov, ativo_id, produto_id in movs:
        pertence = (ativo_id in set_ativos) or (produto_id in ids_produto and ids_produto[produto_id] == dominio.value)
        if not pertence or data_mov is None:
            continue
        chave = data_mov.strftime("%Y-%m")
        b = buckets.setdefault(chave, {"entradas": 0, "saidas": 0})
        if getattr(tipo, "value", tipo) == TipoMov.ENTRADA.value:
            b["entradas"] += 1
        elif getattr(tipo, "value", tipo) == TipoMov.SAIDA.value:
            b["saidas"] += 1

    movimentacoes_mes = [
        {"rotulo": k, "entradas": v["entradas"], "saidas": v["saidas"]} for k, v in sorted(buckets.items())
    ]

    # 8) Manutenções por status (do inventário).
    rows = (
        db.query(Manutencao.status, func.count(Manutencao.id))
        .join(Ativo, Ativo.id == Manutencao.ativo_id)
        .filter(Manutencao.deleted_at.is_(None), Ativo.deleted_at.is_(None), Ativo.dominio == dominio)
        .group_by(Manutencao.status)
        .all()
    )
    manutencoes_status = _serie([(getattr(s, "value", s), c) for s, c in rows], ROTULO_MANUT)

    # 9) Séries específicas de cada inventário.
    extra: dict = {}
    if dominio == Dominio.TI:
        rows = (
            db.query(AtivoTI.so, func.count(AtivoTI.ativo_id))
            .join(Ativo, Ativo.id == AtivoTI.ativo_id)
            .filter(Ativo.deleted_at.is_(None), Ativo.dominio == Dominio.TI)
            .group_by(AtivoTI.so)
            .all()
        )
        extra["por_so"] = _serie([(n or "Desconhecido", c) for n, c in rows])
        rows = (
            db.query(AtivoTI.ram_gb, func.count(AtivoTI.ativo_id))
            .join(Ativo, Ativo.id == AtivoTI.ativo_id)
            .filter(Ativo.deleted_at.is_(None), Ativo.dominio == Dominio.TI)
            .group_by(AtivoTI.ram_gb)
            .all()
        )
        extra["por_ram"] = _serie([(f"{int(r)} GB" if r else "Não informado", c) for r, c in rows])
    else:
        rows = (
            db.query(Ativo.patrimonio, AtivoImpressora.contador_paginas)
            .join(AtivoImpressora, AtivoImpressora.ativo_id == Ativo.id)
            .filter(Ativo.deleted_at.is_(None), Ativo.dominio == Dominio.IMPRESSORA)
            .order_by(AtivoImpressora.contador_paginas.desc())
            .limit(12)
            .all()
        )
        extra["contador_por_impressora"] = _serie([(p, int(c or 0)) for p, c in rows])
        rows = (
            db.query(SuprimentoImpressora.modelo, SuprimentoImpressora.tipo, SuprimentoImpressora.estoque_atual)
            .join(Ativo, Ativo.id == SuprimentoImpressora.ativo_id)
            .filter(
                Ativo.deleted_at.is_(None),
                Ativo.dominio == Dominio.IMPRESSORA,
                SuprimentoImpressora.deleted_at.is_(None),
                SuprimentoImpressora.estoque_atual <= SuprimentoImpressora.estoque_minimo,
            )
            .all()
        )
        extra["suprimentos_baixos"] = _serie(
            [(f"{m or getattr(t, 'value', t)}", 1) for m, t, _e in rows]
        )

    return {
        "dominio": dominio.value,
        "status": status,
        "categoria": categoria,
        "localizacao": localizacao,
        "departamento": departamento,
        "valor_categoria": valor_categoria,
        "garantias": garantias,
        "movimentacoes_mes": movimentacoes_mes,
        "manutencoes_status": manutencoes_status,
        "extra": extra,
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
    }
