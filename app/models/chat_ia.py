"""Perguntas e respostas do chat de inventário."""
from uuid import UUID

from sqlalchemy import ForeignKey, Index, JSON, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin


class ChatInventarioMensagem(CreatedAtMixin, Base):
    __tablename__ = "chat_inventario_mensagens"
    __table_args__ = (
        Index("ix_chat_inventario_escopo", "usuario_id", "planta_id", "inventarios", "conversa_id", "id"),
        Index("ix_chat_inventario_retencao", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversa_id: Mapped[UUID] = mapped_column(Uuid)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"))
    planta_id: Mapped[int | None] = mapped_column(ForeignKey("plantas.id", ondelete="CASCADE"))
    inventarios: Mapped[str] = mapped_column(String(128))
    pergunta: Mapped[str] = mapped_column(Text)
    resposta: Mapped[str] = mapped_column(Text)
    resultados: Mapped[list[dict]] = mapped_column(JSON)
