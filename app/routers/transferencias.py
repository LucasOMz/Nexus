"""Transferência de equipamentos entre plantas, com dupla aprovação.

Fluxo:

1. O técnico da planta de origem **solicita** a transferência, escolhendo o
   motivo (empréstimo, transferência de ativo ou outro).
2. **Quem vai receber** aprova — qualquer técnico ou administrador da planta de
   destino. O primeiro que decidir move o processo.
3. Aprovado pelo destino, vai para o **administrador** dar a palavra final.
4. Com as duas aprovações, o ativo muda de planta.

Em qualquer etapa alguém com poder de decisão pode **recusar**, com justificativa.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user
from app.core.planta import planta_ativa
from app.database import get_db
from app.models.core import Ativo, Planta, Transferencia, Usuario
from app.services.audit_service import audit

router = APIRouter(prefix="/transferencias", tags=["transferencias"])

MOTIVOS = {
    "emprestimo": "Empréstimo entre plantas",
    "transferencia": "Transferência definitiva do ativo",
    "outro": "Outro motivo",
}
STATUS_ROTULO = {
    "aguardando_destino": "Aguardando aprovação de quem recebe",
    "aguardando_admin": "Aguardando aprovação do administrador",
    "aprovada": "Aprovada",
    "recusada": "Recusada",
    "cancelada": "Cancelada",
}

# Situações em que a transferência ainda está em andamento.
PENDENTES = ("aguardando_destino", "aguardando_admin")


def _papel(user: Usuario) -> str:
    return getattr(user.papel, "value", user.papel)


def _serializar(t: Transferencia) -> dict:
    return {
        "id": t.id,
        "ativo_id": t.ativo_id,
        "patrimonio": t.ativo.patrimonio if t.ativo else None,
        "modelo": t.ativo.modelo if t.ativo else None,
        "planta_origem": t.planta_origem.sigla if t.planta_origem else None,
        "planta_origem_id": t.planta_origem_id,
        "planta_destino": t.planta_destino.sigla if t.planta_destino else None,
        "planta_destino_id": t.planta_destino_id,
        "motivo": t.motivo,
        "motivo_rotulo": MOTIVOS.get(t.motivo, t.motivo),
        "motivo_detalhe": t.motivo_detalhe,
        "observacoes": t.observacoes,
        "status": t.status,
        "status_rotulo": STATUS_ROTULO.get(t.status, t.status),
        "solicitado_por": t.solicitado_por.nome if t.solicitado_por else None,
        "criado_em": (t.created_at.isoformat() + ("" if t.created_at.tzinfo else "+00:00")) if t.created_at else None,
        "aprovado_destino_por": t.aprovado_destino_por.nome if t.aprovado_destino_por else None,
        "aprovado_destino_em": t.aprovado_destino_em.isoformat() if t.aprovado_destino_em else None,
        "aprovado_admin_por": t.aprovado_admin_por.nome if t.aprovado_admin_por else None,
        "aprovado_admin_em": t.aprovado_admin_em.isoformat() if t.aprovado_admin_em else None,
        "recusado_por": t.recusado_por.nome if t.recusado_por else None,
        "motivo_recusa": t.motivo_recusa,
    }


def _carregar(db: Session, transferencia_id: int) -> Transferencia:
    t = (
        db.query(Transferencia)
        .options(
            selectinload(Transferencia.ativo),
            selectinload(Transferencia.planta_origem),
            selectinload(Transferencia.planta_destino),
            selectinload(Transferencia.solicitado_por),
            selectinload(Transferencia.aprovado_destino_por),
            selectinload(Transferencia.aprovado_admin_por),
            selectinload(Transferencia.recusado_por),
        )
        .filter(Transferencia.id == transferencia_id)
        .first()
    )
    if t is None:
        raise HTTPException(404, "Transferência não encontrada")
    return t


def _pode_aprovar_destino(t: Transferencia, user: Usuario) -> bool:
    """Quem recebe aprova: administrador ou quem pertence à planta de destino."""
    if _papel(user) == "admin":
        return True
    return user.planta_id == t.planta_destino_id


@router.get("/motivos")
def motivos(_: Usuario = Depends(get_current_user)) -> list[dict]:
    return [{"valor": k, "rotulo": v} for k, v in MOTIVOS.items()]


@router.get("/pendentes")
def pendentes_para_mim(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """O que **este usuário** precisa decidir agora (alimenta o sino)."""
    itens: list[Transferencia] = []
    base = db.query(Transferencia).options(
        selectinload(Transferencia.ativo),
        selectinload(Transferencia.planta_origem),
        selectinload(Transferencia.planta_destino),
        selectinload(Transferencia.solicitado_por),
        selectinload(Transferencia.aprovado_destino_por),
        selectinload(Transferencia.aprovado_admin_por),
        selectinload(Transferencia.recusado_por),
    )

    if _papel(user) == "admin":
        # O administrador decide o que já passou pelo destino.
        itens = base.filter(Transferencia.status == "aguardando_admin").all()
    elif user.planta_id is not None:
        itens = base.filter(
            Transferencia.status == "aguardando_destino",
            Transferencia.planta_destino_id == user.planta_id,
        ).all()

    return {"total": len(itens), "itens": [_serializar(t) for t in itens]}


@router.get("")
def listar(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
) -> dict:
    """Transferências que envolvem a planta do usuário (origem ou destino).

    O administrador vê todas.
    """
    consulta = db.query(Transferencia).options(
        selectinload(Transferencia.ativo),
        selectinload(Transferencia.planta_origem),
        selectinload(Transferencia.planta_destino),
        selectinload(Transferencia.solicitado_por),
        selectinload(Transferencia.aprovado_destino_por),
        selectinload(Transferencia.aprovado_admin_por),
        selectinload(Transferencia.recusado_por),
    )

    if _papel(user) != "admin":
        if planta_id is None:
            return {"total": 0, "pendentes": 0, "itens": []}
        consulta = consulta.filter(
            or_(
                Transferencia.planta_origem_id == planta_id,
                Transferencia.planta_destino_id == planta_id,
            )
        )
    elif planta_id is not None:
        consulta = consulta.filter(
            or_(
                Transferencia.planta_origem_id == planta_id,
                Transferencia.planta_destino_id == planta_id,
            )
        )

    if status:
        consulta = consulta.filter(Transferencia.status == status)

    itens = consulta.order_by(Transferencia.id.desc()).all()
    return {
        "total": len(itens),
        "pendentes": sum(1 for t in itens if t.status in PENDENTES),
        "itens": [_serializar(t) for t in itens],
    }


@router.post("", status_code=201)
def solicitar(
    request: Request,
    ativo_id: int = Form(...),
    planta_destino_id: int = Form(...),
    motivo: str = Form(...),
    motivo_detalhe: str | None = Form(default=None),
    observacoes: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """Abre a solicitação de transferência (técnico da planta de origem)."""
    if motivo not in MOTIVOS:
        raise HTTPException(400, f"Motivo inválido. Use: {', '.join(MOTIVOS)}.")
    if motivo == "outro" and not (motivo_detalhe or "").strip():
        raise HTTPException(400, "Descreva o motivo da transferência.")

    ativo = db.get(Ativo, ativo_id)
    if ativo is None or ativo.deleted_at is not None:
        raise HTTPException(404, "Ativo não encontrado")
    if _papel(user) != "admin" and ativo.planta_id != user.planta_id:
        raise HTTPException(403, "Este ativo não é da sua planta.")

    destino = db.get(Planta, planta_destino_id)
    if destino is None:
        raise HTTPException(404, "Planta de destino não encontrada")
    if not destino.ativa:
        raise HTTPException(400, f"A planta {destino.sigla} está inativa.")
    if destino.id == ativo.planta_id:
        raise HTTPException(400, "O ativo já está nesta planta.")

    # Um ativo não pode ter duas transferências em andamento ao mesmo tempo.
    em_curso = (
        db.query(Transferencia)
        .filter(Transferencia.ativo_id == ativo.id, Transferencia.status.in_(PENDENTES))
        .first()
    )
    if em_curso:
        raise HTTPException(
            409,
            f"Este ativo já tem uma transferência em andamento "
            f"(#{em_curso.id}, {STATUS_ROTULO.get(em_curso.status, em_curso.status)}).",
        )

    t = Transferencia(
        ativo_id=ativo.id,
        planta_origem_id=ativo.planta_id,
        planta_destino_id=destino.id,
        motivo=motivo,
        motivo_detalhe=(motivo_detalhe or "").strip() or None,
        observacoes=(observacoes or "").strip() or None,
        solicitado_por_id=user.id,
        status="aguardando_destino",
    )
    db.add(t)
    db.flush()

    audit(db, user, "transferencia_solicitada", "transferencia", t.id,
          ip=request.client.host if request.client else None,
          diff={"ativo": ativo.patrimonio, "destino": destino.sigla, "motivo": motivo})
    db.commit()
    return _serializar(_carregar(db, t.id))


@router.post("/{transferencia_id}/aprovar")
def aprovar(
    transferencia_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """Aprova a etapa atual: quem recebe primeiro, depois o administrador."""
    t = _carregar(db, transferencia_id)
    agora = datetime.now(timezone.utc)
    ip = request.client.host if request.client else None

    if t.status == "aguardando_destino":
        if not _pode_aprovar_destino(t, user):
            raise HTTPException(403, "Só quem vai receber o equipamento pode aprovar esta etapa.")
        t.status = "aguardando_admin"
        t.aprovado_destino_por = user   # objeto, nao so o id: o relacionamento fica em cache
        t.aprovado_destino_em = agora
        audit(db, user, "transferencia_aprovada_destino", "transferencia", t.id, ip=ip)
        db.commit()
        return _serializar(_carregar(db, t.id))

    if t.status == "aguardando_admin":
        if _papel(user) != "admin":
            raise HTTPException(403, "Esta etapa é do administrador.")
        # Aprovação final: o ativo muda de planta e o histórico é registrado.
        ativo = db.get(Ativo, t.ativo_id)
        if ativo is None or ativo.deleted_at is not None:
            raise HTTPException(404, "O ativo desta transferência não existe mais.")

        origem = t.planta_origem_id
        ativo.planta_id = t.planta_destino_id
        t.status = "aprovada"
        t.aprovado_admin_por = user
        t.aprovado_admin_em = agora

        audit(db, user, "transferencia_aprovada", "transferencia", t.id, ip=ip,
              diff={"ativo": ativo.patrimonio, "de": origem, "para": t.planta_destino_id})
        db.commit()
        return _serializar(_carregar(db, t.id))

    raise HTTPException(400, f"Esta transferência está '{STATUS_ROTULO.get(t.status, t.status)}'.")


@router.post("/{transferencia_id}/recusar")
def recusar(
    transferencia_id: int,
    request: Request,
    motivo_recusa: str = Form(..., min_length=3),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """Recusa a transferência, com justificativa. Paralisa o processo."""
    t = _carregar(db, transferencia_id)

    if t.status not in PENDENTES:
        raise HTTPException(400, "Esta transferência já foi decidida.")

    # Só decide quem teria poder na etapa atual.
    if t.status == "aguardando_destino" and not _pode_aprovar_destino(t, user):
        raise HTTPException(403, "Só quem vai receber o equipamento pode recusar nesta etapa.")
    if t.status == "aguardando_admin" and _papel(user) != "admin":
        raise HTTPException(403, "Esta etapa é do administrador.")

    t.status = "recusada"
    t.recusado_por = user
    t.recusado_em = datetime.now(timezone.utc)
    t.motivo_recusa = motivo_recusa.strip()

    audit(db, user, "transferencia_recusada", "transferencia", t.id,
          ip=request.client.host if request.client else None, diff={"motivo": t.motivo_recusa})
    db.commit()
    return _serializar(_carregar(db, t.id))


@router.post("/{transferencia_id}/cancelar")
def cancelar(
    transferencia_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """Quem pediu (ou o administrador) desiste antes de qualquer aprovação."""
    t = _carregar(db, transferencia_id)
    if t.status not in PENDENTES:
        raise HTTPException(400, "Esta transferência já foi decidida.")
    if _papel(user) != "admin" and t.solicitado_por_id != user.id:
        raise HTTPException(403, "Só quem solicitou (ou o administrador) pode cancelar.")

    t.status = "cancelada"
    audit(db, user, "transferencia_cancelada", "transferencia", t.id,
          ip=request.client.host if request.client else None)
    db.commit()
    return _serializar(_carregar(db, t.id))
