"""Estado persistente das credenciais de autenticação."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SessaoUsuario(Base):
    __tablename__ = "sessoes_usuarios"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    refresh_hash: Mapped[str | None] = mapped_column(String(64))
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revogada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultima_atividade_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
