"""Schemas de produtos (consumíveis e itens de estoque)."""
from __future__ import annotations

from datetime import datetime

from pydantic import ConfigDict, Field

from app.models.enums import Dominio, TipoItem
from app.schemas.common import SemVazios
from app.schemas.datas import DatasComFuso


class ProdutoBase(SemVazios):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=1, max_length=80)
    nome: str = Field(min_length=1, max_length=200)
    descricao: str | None = None
    categoria_id: int | None = None
    fornecedor_id: int | None = None
    dominio: Dominio
    tipo_item: TipoItem = TipoItem.CONSUMIVEL
    unidade: str = "un"
    estoque_minimo: int = Field(default=0, ge=0)
    preco_unitario: float | None = Field(default=None, ge=0)


class ProdutoCreate(ProdutoBase):
    pass


class ProdutoUpdate(SemVazios):
    model_config = ConfigDict(extra="forbid")

    sku: str | None = Field(default=None, min_length=1, max_length=80)
    nome: str | None = Field(default=None, min_length=1, max_length=200)
    descricao: str | None = None
    categoria_id: int | None = None
    fornecedor_id: int | None = None
    dominio: Dominio | None = None
    tipo_item: TipoItem | None = None
    unidade: str | None = None
    estoque_minimo: int | None = Field(default=None, ge=0)
    preco_unitario: float | None = Field(default=None, ge=0)


class ProdutoOut(ProdutoBase, DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
