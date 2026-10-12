"""Camada financeira — endpoints de leitura.

Junta os dados que já existem (`Ativo`, `Manutencao`, `Movimentacao`,
`Produto`, `Departamento`, `LeituraContador`) e entrega os cálculos do serviço
`financeiro`. **Só lê**: nenhum valor é gravado ou recalculado no banco, porque
depreciação é derivada — guardá-la só criaria dado velho para manter.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.planta import aplicar_filtro, planta_ativa
from app.database import get_db
from app.models.contrato import Contrato
from app.models.core import Ativo, Departamento, Manutencao, Movimentacao, Produto, Usuario
from app.models.enums import SituacaoLicenca, TipoLicenca
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

    # --- Locação ---------------------------------------------------------
    # O valor mensal é do CONTRATO, não do equipamento: um contrato cobre 50
    # notebooks por um valor único. O custo por ativo é o rateio.
    contratos = {
        c.id: c
        for c in db.query(Contrato).filter(Contrato.deleted_at.is_(None)).all()
    }
    # Quantos ativos vivos cada contrato cobre — o divisor do rateio. Contado
    # de uma vez para todos os contratos: contar por ativo faria uma consulta
    # por linha da lista.
    cobertos = dict(
        db.query(Ativo.contrato_id, func.count(Ativo.id))
        .filter(Ativo.deleted_at.is_(None), Ativo.contrato_id.isnot(None))
        .group_by(Ativo.contrato_id)
        .all()
    )

    saida = []
    for a in ativos:
        forma = getattr(a.forma_aquisicao, "value", a.forma_aquisicao) or "comprado"
        contrato = contratos.get(a.contrato_id)
        quantos = cobertos.get(a.contrato_id) or 0

        # Rateio calculado na hora. Se um equipamento for devolvido, a
        # mensalidade não cai e o custo dos que ficaram SOBE — um valor
        # gravado mentiria a partir da primeira devolução.
        valor_mensal = None
        if contrato is not None and contrato.valor_mensal and quantos:
            valor_mensal = float(contrato.valor_mensal) / quantos

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
            # --- Locação --------------------------------------------------
            "forma_aquisicao": forma,
            "valor_mensal": valor_mensal,
            "contrato_id": a.contrato_id,
            "contrato_numero": contrato.numero if contrato else None,
            # O início da locação é do CONTRATO. Usar `data_aquisicao` do
            # ativo (que num locado é nula) zeraria o custo acumulado.
            "contrato_inicio": (
                contrato.inicio.isoformat() if contrato and contrato.inicio else None
            ),
            "contrato_fim": contrato.fim.isoformat() if contrato and contrato.fim else None,
            "valor_residual": float(a.valor_residual or 0) or None,
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
    """Números do parque: valor hoje, depreciação, TCO e garantias.

    ## Três naturezas, nunca somadas

    O retorno traz `comprado` e `locado` (do parque) e agora também
    `software` — as assinaturas. São coisas diferentes: patrimônio que
    deprecia, mensalidade de equipamento e mensalidade de serviço. Somá-las
    daria um número sem significado.
    """
    itens = _montar(db, _ativos(db, planta_id, dominio))
    r = financeiro.resumo_do_parque(itens)
    r["software"] = financeiro.resumo_de_software(
        _assinaturas(db, planta_id, dominio)
    )
    return r


def _assinaturas(db: Session, planta_id: int | None,
                 dominio: str | None = None) -> list[dict]:
    """As licenças de software do tipo **assinatura**, com o nome do produto.

    Só assinatura: licença perpétua é compra pontual — já foi paga, não tem
    mensalidade, e incluí-la faria o custo mensal saltar no mês da compra e
    desaparecer no seguinte.

    O filtro de domínio não se aplica: software não é de TI nem de
    impressora, é da empresa. Passar `dominio` aqui esconderia a assinatura
    ao olhar só as impressoras.
    """
    from app.models.software import Licenca, Software

    q = (
        db.query(
            Software.nome,
            Licenca.valor_mensal,
            Licenca.seats,
            Licenca.validade,
        )
        .join(Software, Software.id == Licenca.software_id)
        .filter(
            Licenca.deleted_at.is_(None),
            Software.deleted_at.is_(None),
            Licenca.tipo == TipoLicenca.ASSINATURA,
            Licenca.situacao == SituacaoLicenca.ATIVA,
        )
    )
    q = aplicar_filtro(q, Licenca, planta_id)

    return [
        {"nome": nome, "valor_mensal": valor, "seats": seats, "validade": validade}
        for nome, valor, seats, validade in q.all()
    ]


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


# ===========================================================================
# Exportação: custo mensal por contrato
# ===========================================================================
@router.get("/contratos.csv", response_class=Response)
def contratos_csv(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    """Custo mensal por contrato, em CSV.

    ## Por que este relatório existe

    O custo de locação não aparece em nenhum lugar do financeiro tradicional
    — ele não é patrimônio, não deprecia e não tem valor de compra. Sem esta
    planilha, a gestão não tem como conferir a fatura do fornecedor contra o
    que o sistema acha que está contratado.

    É a visão que responde "quanto eu pago por mês, e por quê".
    """
    import csv
    import io

    from sqlalchemy import func as _func

    contratos = aplicar_filtro(
        db.query(Contrato).filter(Contrato.deleted_at.is_(None)), Contrato, planta_id
    ).order_by(Contrato.numero).all()

    # Contagem por contrato numa consulta só — dentro do laço seria N+1.
    cobertos = dict(
        db.query(Ativo.contrato_id, _func.count(Ativo.id))
        .filter(Ativo.deleted_at.is_(None), Ativo.contrato_id.isnot(None))
        .group_by(Ativo.contrato_id)
        .all()
    )

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow([
        "contrato", "tipo", "fornecedor", "inicio", "fim", "dias_para_vencer",
        "equipamentos", "valor_mensal", "rateio_por_equipamento", "custo_12_meses",
    ])
    for c in contratos:
        quantos = cobertos.get(c.id) or 0
        mensal = float(c.valor_mensal or 0)
        w.writerow([
            c.numero,
            getattr(c.tipo, "value", c.tipo),
            getattr(c.fornecedor, "nome", "") if c.fornecedor else "",
            c.inicio.isoformat() if c.inicio else "",
            c.fim.isoformat() if c.fim else "",
            c.dias_para_vencer if c.dias_para_vencer is not None else "",
            quantos,
            f"{mensal:.2f}".replace(".", ","),
            f"{(mensal / quantos):.2f}".replace(".", ",") if quantos else "",
            f"{(mensal * 12):.2f}".replace(".", ","),
        ])

    # BOM: sem ele o Excel em português abre os acentos errado.
    conteudo = "\ufeff" + buf.getvalue()
    return Response(
        content=conteudo.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="nexus-contratos.csv"'},
    )
