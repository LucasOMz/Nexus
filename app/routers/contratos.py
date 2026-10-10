"""Contratos de locação, comodato e compra.

## O endpoint que importa

`POST /contratos/{id}/exercer-compra` — a transição **locado → comprado**.

É o único ponto do sistema em que um ativo muda de natureza patrimonial. As
cinco regras dela estão em `_exercer_compra`, cada uma com o motivo.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_write
from app.core.planta import aplicar_filtro, planta_ativa
from app.database import get_db
from app.models.contrato import Contrato
from app.models.core import Ativo, Usuario
from app.models.enums import FormaAquisicao
from app.schemas.contratos import (
    ContratoIn,
    ContratoOut,
    ExercerCompraIn,
    VincularAtivosIn,
)
from app.services.audit_service import audit

log = logging.getLogger(__name__)

router = APIRouter(prefix="/contratos", tags=["contratos"])


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _carregar(db: Session, contrato_id: int) -> Contrato:
    c = (
        db.query(Contrato)
        .filter(Contrato.id == contrato_id, Contrato.deleted_at.is_(None))
        .first()
    )
    if c is None:
        raise HTTPException(404, "Contrato não encontrado.")
    return c


def _com_derivados(db: Session, c: Contrato) -> ContratoOut:
    """Serializa com os números calculados (contagem, rateio, vencimento)."""
    vivos = (
        db.query(func.count(Ativo.id))
        .filter(Ativo.contrato_id == c.id, Ativo.deleted_at.is_(None))
        .scalar()
        or 0
    )
    out = ContratoOut.model_validate(c)
    out.total_ativos = vivos
    out.em_aberto = c.em_aberto
    out.dias_para_vencer = c.dias_para_vencer
    out.valor_mensal_por_ativo = c.valor_mensal_por_ativo
    return out


@router.get("", response_model=list[ContratoOut])
def listar(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
    apenas_abertos: bool = Query(default=False),
    busca: str | None = Query(default=None),
):
    """Lista os contratos visíveis para o usuário."""
    q = db.query(Contrato).filter(Contrato.deleted_at.is_(None))
    # `Contrato` não tem coluna `planta_id` homônima em `aplicar_filtro`?
    # Tem — e é o que impede um contrato aparecer em outra unidade.
    q = aplicar_filtro(q, Contrato, planta_id)

    if busca:
        q = q.filter(Contrato.numero.ilike(f"%{busca.strip()}%"))

    contratos = q.order_by(Contrato.inicio.desc()).all()
    if apenas_abertos:
        contratos = [c for c in contratos if c.em_aberto]
    return [_com_derivados(db, c) for c in contratos]


@router.get("/{contrato_id}", response_model=ContratoOut)
def detalhe(
    contrato_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    return _com_derivados(db, _carregar(db, contrato_id))


@router.post("", response_model=ContratoOut, status_code=status.HTTP_201_CREATED)
def criar(
    body: ContratoIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    _: Usuario = Depends(require_write),
):
    """Cadastra um contrato."""
    numero = body.numero.strip()
    if (
        db.query(Contrato)
        .filter(func.lower(Contrato.numero) == numero.lower(), Contrato.deleted_at.is_(None))
        .first()
    ):
        raise HTTPException(409, f"Já existe um contrato com o número '{numero}'.")

    # Admin (planta None) escolhe a planta; usuário comum cria na dele.
    planta_destino = body.planta_id if user.planta_id is None else user.planta_id

    obj = Contrato(**body.model_dump(exclude={"planta_id"}), planta_id=planta_destino)
    db.add(obj)
    db.flush()
    audit(db, user, "create", "contrato", obj.id, ip=_ip(request),
          diff={**body.model_dump(mode="json")})
    db.commit()
    db.refresh(obj)
    return _com_derivados(db, obj)


@router.put("/{contrato_id}", response_model=ContratoOut)
def atualizar(
    contrato_id: int,
    body: ContratoIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    _: Usuario = Depends(require_write),
):
    c = _carregar(db, contrato_id)

    repetido = (
        db.query(Contrato)
        .filter(
            func.lower(Contrato.numero) == body.numero.strip().lower(),
            Contrato.id != c.id,
            Contrato.deleted_at.is_(None),
        )
        .first()
    )
    if repetido is not None:
        raise HTTPException(409, f"O número '{body.numero}' já é do contrato {repetido.id}.")

    for campo, valor in body.model_dump(exclude={"planta_id"}).items():
        setattr(c, campo, valor)

    audit(db, user, "update", "contrato", c.id, ip=_ip(request),
          diff={**body.model_dump(mode="json")})
    db.commit()
    db.refresh(c)
    return _com_derivados(db, c)


@router.delete("/{contrato_id}", status_code=status.HTTP_204_NO_CONTENT)
def encerrar(
    contrato_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    _: Usuario = Depends(require_write),
):
    """Encerra o contrato (exclusão lógica).

    **Não desvincula os ativos.** Eles continuam apontando para o contrato
    encerrado — o histórico de onde cada equipamento veio não se apaga. Quem
    quiser tirá-los usa `DELETE /contratos/{id}/ativos`.
    """
    c = _carregar(db, contrato_id)
    c.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "contrato", c.id, ip=_ip(request))
    db.commit()


# ===========================================================================
# Vínculo de ativos
# ===========================================================================
@router.post("/{contrato_id}/ativos", response_model=ContratoOut)
def vincular_ativos(
    contrato_id: int,
    body: VincularAtivosIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    _: Usuario = Depends(require_write),
):
    """Coloca ativos no contrato.

    Marcar como `locado` é o padrão e o caso comum. Desmarcar serve para o
    contrato de compra em lote, em que os ativos são comprados.
    """
    c = _carregar(db, contrato_id)

    ativos = (
        db.query(Ativo)
        .filter(Ativo.id.in_(body.ativo_ids), Ativo.deleted_at.is_(None))
        .all()
    )
    faltando = set(body.ativo_ids) - {a.id for a in ativos}
    if faltando:
        raise HTTPException(404, f"Ativos não encontrados: {sorted(faltando)}")

    for a in ativos:
        a.contrato_id = c.id
        if body.marcar_como_locado:
            a.forma_aquisicao = FormaAquisicao.LOCADO
            # Locado não tem valor de compra. Se havia um (vindo de quando era
            # comprado), ele sai — senão o patrimônio continuaria contando um
            # bem que passou a ser alugado.
            a.valor = None
            a.data_aquisicao = None

    audit(db, user, "vincular", "contrato", c.id, ip=_ip(request),
          diff={"ativos": [a.id for a in ativos], "marcar_como_locado": body.marcar_como_locado})
    db.commit()
    db.refresh(c)
    return _com_derivados(db, c)


@router.delete("/{contrato_id}/ativos", response_model=ContratoOut)
def desvincular_ativos(
    contrato_id: int,
    request: Request,
    ativo_ids: list[int] = Query(..., description="Ids dos ativos a retirar"),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    _: Usuario = Depends(require_write),
):
    """Retira ativos do contrato.

    **Não apaga nem devolve o equipamento** — só desfaz o vínculo. Quem
    recebeu de volta dá baixa pelo fluxo normal de movimentação.

    O rateio dos que ficam **sobe**: a mensalidade do contrato não cai.
    """
    c = _carregar(db, contrato_id)
    ativos = (
        db.query(Ativo)
        .filter(Ativo.id.in_(ativo_ids), Ativo.contrato_id == c.id)
        .all()
    )
    for a in ativos:
        a.contrato_id = None

    audit(db, user, "desvincular", "contrato", c.id, ip=_ip(request),
          diff={"ativos": [a.id for a in ativos]})
    db.commit()
    db.refresh(c)
    return _com_derivados(db, c)


# ===========================================================================
# Transição locado -> comprado
# ===========================================================================
@router.post("/{contrato_id}/ativos/{ativo_id}/exercer-compra", response_model=dict)
def exercer_compra(
    contrato_id: int,
    ativo_id: int,
    body: ExercerCompraIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    _: Usuario = Depends(require_write),
):
    """**Exercer a opção de compra** de um ativo locado.

    É o único ponto em que um ativo muda de natureza patrimonial. As cinco
    regras estão comentadas no corpo — cada uma existe por um motivo, e
    inverter qualquer delas produz número errado que ninguém percebe.
    """
    c = _carregar(db, contrato_id)
    a = (
        db.query(Ativo)
        .filter(Ativo.id == ativo_id, Ativo.contrato_id == c.id, Ativo.deleted_at.is_(None))
        .first()
    )
    if a is None:
        raise HTTPException(404, "Ativo não encontrado neste contrato.")

    if a.forma_aquisicao == FormaAquisicao.COMPRADO:
        raise HTTPException(400, "Este ativo já é comprado.")

    antes = {
        "forma_aquisicao": getattr(a.forma_aquisicao, "value", a.forma_aquisicao),
        "valor": float(a.valor) if a.valor else None,
        "data_aquisicao": a.data_aquisicao.isoformat() if a.data_aquisicao else None,
        "contrato_id": a.contrato_id,
    }

    quando = body.data or date.today()

    # 1. Muda a natureza.
    a.forma_aquisicao = FormaAquisicao.COMPRADO
    # 2. O valor passa a ser o preço pago — é o que entra no patrimônio.
    a.valor = body.valor
    # 3. A aquisição é a data da compra, não o início da locação.
    a.data_aquisicao = quando
    # 4. Sai do rateio do contrato: deixa de ser custo mensal e passa a ser
    #    patrimônio. Continuar vinculado faria o rateio dos que ficaram
    #    dividir por um ativo que não é mais alugado.
    a.contrato_id = None
    # O preço do buyout já foi pago e virou `valor`. Mantê-lo faria parecer
    # que ainda há uma compra futura a fazer.
    a.valor_residual = None

    # 5. A depreciação começa AQUI — e não retroage ao início da locação.
    #    Antes desta data o equipamento não era patrimônio da empresa;
    #    depreciar desde o início inventaria perda de valor de um bem que não
    #    era dela. `data_aquisicao` acima é o que garante isso.

    audit(db, user, "exercer_compra", "ativo", a.id, ip=_ip(request),
          diff={"contrato": c.numero, "antes": antes,
                "depois": {"forma_aquisicao": "comprado", "valor": float(body.valor),
                           "data_aquisicao": quando.isoformat()},
                "observacoes": body.observacoes})
    db.commit()
    db.refresh(a)
    db.refresh(c)

    return {
        "ok": True,
        "ativo_id": a.id,
        "patrimonio": a.patrimonio,
        "forma_aquisicao": "comprado",
        "valor": float(a.valor or 0),
        "data_aquisicao": a.data_aquisicao.isoformat() if a.data_aquisicao else None,
        "mensagem": (
            f"Compra registrada. O ativo {a.patrimonio} saiu da locação e passou a "
            "depreciar a partir da data da compra."
        ),
        # O rateio dos que ficaram subiu — é a informação que a tela precisa
        # dar, senão o gestor não entende por que o custo por equipamento
        # mudou.
        "rateio_apos_compra": (
            float(c.valor_mensal_por_ativo) if c.valor_mensal_por_ativo else None
        ),
        "ativos_restantes": (
            db.query(func.count(Ativo.id))
            .filter(Ativo.contrato_id == c.id, Ativo.deleted_at.is_(None))
            .scalar()
            or 0
        ),
    }
