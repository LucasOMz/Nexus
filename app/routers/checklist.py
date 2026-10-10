"""Checklist de empréstimo — configuração.

Os itens conferidos na entrega e na devolução não são fixos no código: quem
administra cadastra o que faz sentido. Conferir "bateria segura carga" num
switch não serve para nada.

Este router cuida do **modelo** (o que perguntar). As respostas ficam em
`emprestimo_itens` e não são tocadas por aqui — mudar o modelo não pode
reescrever o que já foi conferido.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.database import get_db
from app.models.core import Usuario
from app.models.emprestimo import ChecklistItem
from app.services.audit_service import audit

router = APIRouter(prefix="/checklist", tags=["checklist"])


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rotulo: str = Field(min_length=1, max_length=160)
    ajuda: str | None = None
    ordem: int = 0
    na_entrega: bool = True
    na_devolucao: bool = True
    categoria_id: int | None = None
    dominio: str | None = None
    # Se este item voltar pior do que saiu, abre manutenção?
    # Nem todo item justifica: um cabo faltando não é avaria do equipamento.
    abre_manutencao: bool = True
    ativo: bool = True


def _saida(i: ChecklistItem) -> dict:
    return {
        "id": i.id, "rotulo": i.rotulo, "ajuda": i.ajuda, "ordem": i.ordem,
        "na_entrega": i.na_entrega, "na_devolucao": i.na_devolucao,
        "categoria_id": i.categoria_id, "dominio": i.dominio,
        "abre_manutencao": i.abre_manutencao, "ativo": i.ativo,
    }


@router.get("", response_model=list[dict])
def listar(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Todos os itens, inclusive os desativados — a tela precisa mostrar o que
    foi desligado, senão parece que sumiu."""
    q = (
        db.query(ChecklistItem)
        .filter(ChecklistItem.deleted_at.is_(None))
        .order_by(ChecklistItem.ordem, ChecklistItem.id)
    )
    return [_saida(i) for i in q.all()]


@router.post("", response_model=dict, status_code=201)
def criar(
    body: ItemIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    item = ChecklistItem(**body.model_dump())
    db.add(item)
    db.flush()
    audit(db, user, "criar", "checklist_item", item.id,
          ip=request.client.host if request.client else None,
          diff={"rotulo": item.rotulo})
    db.commit()
    db.refresh(item)
    return _saida(item)


@router.put("/{item_id}", response_model=dict)
def atualizar(
    item_id: int,
    body: ItemIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    item = db.get(ChecklistItem, item_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(404, "Item não encontrado")

    for campo, valor in body.model_dump().items():
        setattr(item, campo, valor)
    db.commit()
    db.refresh(item)
    return _saida(item)


@router.delete("/{item_id}", status_code=204)
def excluir(
    item_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    """Desativa de verdade (soft delete).

    O histórico de conferências guarda o rótulo do momento, então apagar o item
    não apaga o que já foi conferido — mas tirá-lo da lista impede que apareça
    em conferências novas.
    """
    item = db.get(ChecklistItem, item_id)
    if item is None or item.deleted_at is not None:
        raise HTTPException(404, "Item não encontrado")
    from datetime import datetime, timezone

    item.deleted_at = datetime.now(timezone.utc)
    db.commit()


@router.post("/semente", response_model=list[dict], status_code=201)
def criar_padrao(
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    """Cria os itens padrão de uma vez.

    A tabela vazia impede a retirada — este atalho dá um ponto de partida para
    editar, em vez de obrigar a digitar sete itens à mão.
    """
    from app.services.emprestimo_service import CHECKLIST_PADRAO

    existentes = {
        i.rotulo
        for i in db.query(ChecklistItem).filter(ChecklistItem.deleted_at.is_(None)).all()
    }
    criados = []
    for ordem, rotulo in enumerate(CHECKLIST_PADRAO):
        if rotulo in existentes:
            continue
        item = ChecklistItem(rotulo=rotulo, ordem=ordem)
        db.add(item)
        criados.append(item)

    if criados:
        db.flush()
        audit(db, user, "criar_padrao", "checklist_item", None,
              diff={"criados": len(criados)})
    db.commit()
    for i in criados:
        db.refresh(i)
    return [_saida(i) for i in criados]
