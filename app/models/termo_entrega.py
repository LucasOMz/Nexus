"""Modelos versionados e comprovantes de entrega de equipamentos."""
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin


class ModeloTermoEntrega(CreatedAtMixin, Base):
    __tablename__ = "modelos_termo_entrega"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    url_publica: Mapped[str] = mapped_column(String(300))
    prazo_horas: Mapped[int]
    exigir_agente: Mapped[bool]
    campos: Mapped[list[dict]] = mapped_column(JSON)
    paginas: Mapped[list[list[float]]] = mapped_column(JSON)
    pdf: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class EntregaTermo(CreatedAtMixin, Base):
    __tablename__ = "entregas_termo"

    id: Mapped[int] = mapped_column(primary_key=True)
    termo_id: Mapped[int] = mapped_column(ForeignKey("termos.id", ondelete="CASCADE"), index=True)
    modelo_id: Mapped[int] = mapped_column(ForeignKey("modelos_termo_entrega.id"))
    modelo: Mapped[ModeloTermoEntrega] = relationship()
    criado_por: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))
    destinatario: Mapped[str] = mapped_column(String(160))
    login_ad: Mapped[str] = mapped_column(String(120))
    colaborador: Mapped[str] = mapped_column(String(160))
    estado: Mapped[str] = mapped_column(String(24))
    convite_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sessao_hash: Mapped[str | None] = mapped_column(String(64))
    sessao_expira_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    desafio_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    desafio_expira_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    respostas: Mapped[dict | None] = mapped_column(JSON)
    imagem_assinatura: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    aceite_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assinado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comprovante: Mapped[dict | None] = mapped_column(JSON)
    pdf_assinado: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
