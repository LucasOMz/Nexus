"""Schemas de QR Code."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import SemVazios


class QRGenerateOut(BaseModel):
    ativo_id: int
    patrimonio: str
    qr_payload: str
    qr_data_url: str


class QRBatchRequest(SemVazios):
    model_config = ConfigDict(extra="forbid")

    ativo_ids: list[int] = Field(min_length=1, max_length=200)


class QRValidateRequest(SemVazios):
    model_config = ConfigDict(extra="forbid")

    payload: str = Field(min_length=1)


class QRValidateOut(BaseModel):
    valid: bool
    ativo_id: int | None = None
    detail: str | None = None
