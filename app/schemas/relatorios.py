"""Schemas de relatórios e filtros salvos."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field

from app.schemas.common import SemVazios
from app.schemas.datas import DatasComFuso


class FiltroSalvoCreate(SemVazios):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1, max_length=120)
    tipo: str = Field(min_length=1, max_length=40)
    filtros: dict[str, Any]


class FiltroSalvoUpdate(SemVazios):
    model_config = ConfigDict(extra="forbid")

    nome: str | None = Field(default=None, min_length=1, max_length=120)
    filtros: dict[str, Any] | None = None


class FiltroSalvoOut(DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    tipo: str
    filtros: dict[str, Any]
    created_at: datetime
