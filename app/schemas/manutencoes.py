"""Schemas de manutenções."""
from __future__ import annotations

from datetime import datetime

from pydantic import ConfigDict, Field

from app.models.enums import StatusManut
from app.schemas.common import SemVazios
from app.schemas.datas import DatasComFuso


class ManutencaoCreate(SemVazios):
    model_config = ConfigDict(extra="forbid")

    ativo_id: int
    fornecedor_id: int | None = None
    descricao: str | None = None
    custo: float | None = Field(default=None, ge=0)
    tecnico: str | None = Field(default=None, max_length=160)
    observacoes: str | None = None


class ManutencaoUpdate(SemVazios):
    model_config = ConfigDict(extra="forbid")

    fornecedor_id: int | None = None
    status: StatusManut | None = None
    descricao: str | None = None
    custo: float | None = Field(default=None, ge=0)
    tecnico: str | None = Field(default=None, max_length=160)
    observacoes: str | None = None
    data_conclusao: datetime | None = None
    # Comentário obrigatório para concluir a ordem.
    comentario_conclusao: str | None = None


class ManutencaoOut(DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ativo_id: int
    fornecedor_id: int | None
    status: StatusManut
    descricao: str | None
    custo: float | None
    data_abertura: datetime
    data_conclusao: datetime | None
    tecnico: str | None
    observacoes: str | None
    # Preenchidos automaticamente pelo sistema ao concluir a ordem.
    concluido_por_id: int | None = None
    concluido_por_nome: str | None = None
    # Comentário digitado por quem concluiu.
    comentario_conclusao: str | None = None
