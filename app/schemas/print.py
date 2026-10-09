"""Schemas de impressão."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import SemVazios


class PrintRequest(SemVazios):
    model_config = ConfigDict(extra="forbid")

    ativo_id: int
    formato: str = "zpl"
    printer: str | None = None
    copies: int = Field(default=1, ge=1, le=10)
    # Dispositivo cadastrado (admin); se omitido, usa o padrão do inventário.
    dispositivo_id: int | None = None


class PrintBatchRequest(SemVazios):
    model_config = ConfigDict(extra="forbid")

    ativo_ids: list[int] = Field(min_length=1, max_length=200)
    formato: str = "zpl"
    printer: str | None = None
    copies: int = Field(default=1, ge=1, le=10)
    dispositivo_id: int | None = None


class PrintJobItem(BaseModel):
    ativo_id: int
    job_id: str | None = None
    status: str
    detail: str | None = None
    retryable: bool = False


class PrintResponse(BaseModel):
    total: int
    jobs: list[PrintJobItem]
