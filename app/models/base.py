"""Base declarativa e mixins compartilhados.

Decisão arquitetural: usamos tipos portáteis (string para enums, JSON em vez
de JSONB, string para MAC) para que o MESMO código rode em SQLite (dev) e
PostgreSQL (produção) sem bifurcação de modelos.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base de todos os modelos ORM."""


def sa_enum(enum_cls: type, length: int = 30) -> SAEnum:
    """Cria um SAEnum portátil que persiste o `.value` (string) do enum."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        values_callable=lambda x: [e.value for e in x],
        length=length,
    )


class TimestampMixin:
    """created_at + updated_at com atualização automática via onupdate."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CreatedAtMixin:
    """Apenas created_at (para entidades append-only, ex.: auditoria)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SoftDeleteMixin:
    """Soft delete — nada é apagado fisicamente (LGPD + auditabilidade)."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BaseModel(TimestampMixin, SoftDeleteMixin):
    """Modelo com timestamps e soft delete (maioria das tabelas)."""


class CreatedAtModel(CreatedAtMixin, SoftDeleteMixin):
    """Modelo com created_at e soft delete (ex.: leituras_contador, anexos)."""
