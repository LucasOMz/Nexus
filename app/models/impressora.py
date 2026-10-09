"""Extensão de domínio Impressora — atributos, suprimentos e contador."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, CreatedAtModel, sa_enum
from app.models.enums import Conectividade, TipoImpressao, TipoSuprimento

if TYPE_CHECKING:
    from app.models.core import Ativo


class AtivoImpressora(Base):
    """Relacionamento 1:1 com `Ativo` (ativo_id é PK e FK)."""

    __tablename__ = "ativos_impressora"

    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id", ondelete="CASCADE"), primary_key=True)
    ip: Mapped[str | None] = mapped_column(String(45), index=True)
    hostname: Mapped[str | None] = mapped_column(String(120))
    driver: Mapped[str | None] = mapped_column(String(200))
    tipo_impressao: Mapped[TipoImpressao] = mapped_column(sa_enum(TipoImpressao), default=TipoImpressao.LASER, nullable=False)
    colorida: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contador_paginas: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conectividade: Mapped[Conectividade] = mapped_column(sa_enum(Conectividade), default=Conectividade.REDE, nullable=False)

    ativo: Mapped["Ativo"] = relationship(back_populates="impressora")


class SuprimentoImpressora(BaseModel, Base):
    __tablename__ = "suprimentos_impressora"

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo: Mapped[TipoSuprimento] = mapped_column(sa_enum(TipoSuprimento), nullable=False)
    modelo: Mapped[str | None] = mapped_column(String(160))
    cor: Mapped[str | None] = mapped_column(String(60))
    rendimento_paginas: Mapped[int | None] = mapped_column(Integer)
    estoque_atual: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estoque_minimo: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    ativo: Mapped["Ativo"] = relationship(back_populates="suprimentos")


class LeituraContador(CreatedAtModel, Base):
    """Histórico de leitura do contador de páginas da impressora."""

    __tablename__ = "leituras_contador"

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id", ondelete="CASCADE"), nullable=False, index=True)
    data_leitura: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    contador: Mapped[int] = mapped_column(Integer, nullable=False)
    observacoes: Mapped[str | None] = mapped_column(Text)

    ativo: Mapped["Ativo"] = relationship()
