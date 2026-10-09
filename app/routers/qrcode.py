"""QR Code: geração (individual/massa) e validação server-side (HMAC)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_module, require_write
from app.core.rate_limit import scan_limiter
from app.database import get_db
from app.models.core import Ativo, Usuario
from app.schemas.qrcode import (
    QRBatchRequest,
    QRGenerateOut,
    QRValidateOut,
    QRValidateRequest,
)
from app.services.audit_service import audit
from app.services.qr_service import build_payload, qr_png_data_url, verify_payload

router = APIRouter(prefix="/qrcode", tags=["qrcode"], dependencies=[Depends(require_module("ativos"))])


def _generate(db: Session, ativo: Ativo) -> QRGenerateOut:
    """Gera (ou reutiliza) o payload assinado e o persiste no ativo."""
    if not ativo.qr_payload:
        ativo.qr_payload = build_payload(ativo.id)
        db.flush()
    return QRGenerateOut(
        ativo_id=ativo.id,
        patrimonio=ativo.patrimonio,
        qr_payload=ativo.qr_payload,
        qr_data_url=qr_png_data_url(ativo.qr_payload),
    )


@router.post("/generate/{ativo_id}", response_model=QRGenerateOut)
def generate_one(
    ativo_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
):
    ativo = db.get(Ativo, ativo_id)
    if ativo is None or ativo.deleted_at is not None:
        raise HTTPException(404, "Ativo não encontrado")
    out = _generate(db, ativo)
    audit(db, user, "qrcode", "ativo", ativo.id, ip=request.client.host if request.client else None)
    db.commit()
    return out


@router.post("/generate", response_model=list[QRGenerateOut])
def generate_batch(
    body: QRBatchRequest, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
):
    """Ação em massa: gera payloads para vários ativos de uma vez."""
    ativos = db.query(Ativo).filter(Ativo.id.in_(body.ativo_ids), Ativo.deleted_at.is_(None)).all()
    if not ativos:
        raise HTTPException(404, "Nenhum ativo encontrado")
    results = [_generate(db, a) for a in ativos]
    audit(db, user, "qrcode_batch", "ativos", None, ip=request.client.host if request.client else None, diff={"ids": body.ativo_ids})
    db.commit()
    return results


@router.get("/{ativo_id}", response_model=QRGenerateOut)
def get_qr(ativo_id: int, db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    ativo = db.get(Ativo, ativo_id)
    if ativo is None or ativo.deleted_at is not None:
        raise HTTPException(404, "Ativo não encontrado")
    return _generate(db, ativo)


@router.post("/validate", response_model=QRValidateOut)
def validate_qr(
    body: QRValidateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Valida o HMAC do payload antes de retornar o id do ativo.

    É a barreira server-side de segurança do scanner (rate limitada).
    """
    key = str(user.id)
    if not scan_limiter.is_allowed(key):
        raise HTTPException(429, "Muitas leituras. Aguarde um instante.")
    ativo_id = verify_payload(body.payload)
    if ativo_id is None:
        return QRValidateOut(valid=False, detail="Payload inválido ou assinatura não confere")
    ativo = db.query(Ativo).filter(Ativo.id == ativo_id, Ativo.deleted_at.is_(None)).first()
    if ativo is None:
        return QRValidateOut(valid=False, ativo_id=ativo_id, detail="Ativo não encontrado")
    return QRValidateOut(valid=True, ativo_id=ativo_id)
