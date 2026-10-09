"""Extensão de domínio TI — atributos específicos de equipamentos de TI."""
from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.core import Ativo


class AtivoTI(Base):
    """Relacionamento 1:1 com `Ativo` (ativo_id é PK e FK)."""

    __tablename__ = "ativos_ti"

    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id", ondelete="CASCADE"), primary_key=True)
    hostname: Mapped[str | None] = mapped_column(String(120), index=True)
    mac_address: Mapped[str | None] = mapped_column(String(17))  # MACADDR nativo no schema.sql de produção
    ip: Mapped[str | None] = mapped_column(String(45))
    so: Mapped[str | None] = mapped_column(String(120))
    dominio_ad: Mapped[str | None] = mapped_column(String(120))
    cpu: Mapped[str | None] = mapped_column(String(120))
    ram_gb: Mapped[int | None] = mapped_column(Integer)
    armazenamento_gb: Mapped[int | None] = mapped_column(Integer)

    # --- Origem no OCS Inventory ---
    # Preenchido só quando o ativo veio da integração. Serve para (a) não
    # recriar o que já existe e (b) saber quanto do parque é inventariado.
    ocs_id: Mapped[str | None] = mapped_column(String(40), index=True)
    # Quando o OCS viu a máquina pela última vez (texto, como o OCS envia).
    ocs_ultimo_contato: Mapped[str | None] = mapped_column(String(40))

    ativo: Mapped["Ativo"] = relationship(back_populates="ti")
