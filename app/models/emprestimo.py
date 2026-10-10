"""Empréstimo de equipamento — ciclo completo e checklist configurável.

O que existia (três campos no ativo) registrava **que** estava emprestado. Aqui
entra o ciclo de verdade:

    Reserva → Retirada → Uso → Devolução → Vistoria

E o **checklist configurável**: os itens conferidos na entrega e na devolução
não são fixos no código — são cadastrados na Administração, e podem variar por
categoria. Conferir "bateria segura carga" num switch não faz sentido.

`ChecklistItem` é o **modelo** (o que perguntar); `EmprestimoItem` é a
**resposta** (o que foi conferido naquele empréstimo). Guardar os dois é o que
permite comparar entrega e devolução — e é a comparação que revela a avaria.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, sa_enum

if TYPE_CHECKING:
    from app.models.core import Ativo, Categoria, Planta, Usuario


class SituacaoEmprestimo(str, enum.Enum):
    RESERVADO = "reservado"
    RETIRADO = "retirado"
    DEVOLVIDO = "devolvido"
    VISTORIADO = "vistoriado"
    CANCELADO = "cancelado"


class MomentoChecklist(str, enum.Enum):
    """O checklist é conferido duas vezes, e comparar os dois é o ponto."""

    ENTREGA = "entrega"
    DEVOLUCAO = "devolucao"


class ChecklistItem(BaseModel, Base):
    """Um item do modelo de checklist — o que se pergunta.

    Configurável na Administração. `categoria_id` nulo = vale para tudo; com
    categoria, vale só para ela (um notebook e um switch não se conferem
    igual).
    """

    __tablename__ = "checklist_itens"

    id: Mapped[int] = mapped_column(primary_key=True)
    ordem: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rotulo: Mapped[str] = mapped_column(String(160), nullable=False)
    ajuda: Mapped[str | None] = mapped_column(Text)

    # Em que momentos este item é conferido.
    na_entrega: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    na_devolucao: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Restringe a uma categoria. Nulo = item geral.
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categorias.id"))
    dominio: Mapped[str | None] = mapped_column(String(20))

    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Marcar como avaria aqui significa: se este item voltar pior do que saiu,
    # abre manutenção automaticamente. Nem todo item justifica (um cabo
    # faltando não é uma avaria do equipamento).
    abre_manutencao: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    categoria: Mapped[Categoria | None] = relationship()


class Emprestimo(BaseModel, Base):
    """Um empréstimo, do pedido ao encerramento."""

    __tablename__ = "emprestimos"

    id: Mapped[int] = mapped_column(primary_key=True)
    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), nullable=False, index=True)
    planta_id: Mapped[int | None] = mapped_column(ForeignKey("plantas.id"), index=True)

    # Para quem vai. `usuario_id` é quem tem login; `retirado_por_nome` cobre
    # quem não tem (visitante, terceiro) — senão o empréstimo não se registra.
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    retirado_por_nome: Mapped[str | None] = mapped_column(String(160))
    departamento_id: Mapped[int | None] = mapped_column(ForeignKey("departamentos.id"))

    situacao: Mapped[SituacaoEmprestimo] = mapped_column(
        sa_enum(SituacaoEmprestimo), default=SituacaoEmprestimo.RESERVADO,
        nullable=False, index=True,
    )

    finalidade: Mapped[str | None] = mapped_column(String(200))
    observacoes: Mapped[str | None] = mapped_column(Text)

    # --- Datas de cada etapa ---------------------------------------------
    reservado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    retirada_prevista: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retirado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    devolucao_prevista: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    devolvido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vistoriado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Quem fez cada etapa ---------------------------------------------
    reservado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    retirada_registrada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    devolucao_registrada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    vistoriado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))

    # --- Termo de responsabilidade ---------------------------------------
    # O modelo `Termo` já existia (hash SHA-256 + PDF); aqui só o vínculo.
    termo_id: Mapped[int | None] = mapped_column(ForeignKey("termos.id"))

    # --- Resultado da devolução ------------------------------------------
    tem_avaria: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    manutencao_id: Mapped[int | None] = mapped_column(ForeignKey("manutencoes.id"))
    bloqueado: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    ativo: Mapped[Ativo] = relationship()
    planta: Mapped[Planta | None] = relationship()
    usuario: Mapped[Usuario | None] = relationship(foreign_keys=[usuario_id])
    itens: Mapped[list[EmprestimoItem]] = relationship(
        back_populates="emprestimo", cascade="all, delete-orphan"
    )

    @property
    def retirado_por_nome_final(self) -> str | None:
        u = getattr(self, "usuario", None)
        return u.nome if u is not None else self.retirado_por_nome

    @property
    def ativo_patrimonio(self) -> str | None:
        a = getattr(self, "ativo", None)
        return a.patrimonio if a is not None else None


class EmprestimoItem(BaseModel, Base):
    """A resposta de um item do checklist num empréstimo.

    Guarda o **rótulo do momento**, e não só a referência: se o item do modelo
    for renomeado ou apagado depois, o histórico do que foi conferido continua
    legível. Um registro de conferência que muda sozinho não serve para nada.
    """

    __tablename__ = "emprestimo_itens"

    id: Mapped[int] = mapped_column(primary_key=True)
    emprestimo_id: Mapped[int] = mapped_column(
        ForeignKey("emprestimos.id"), nullable=False, index=True
    )
    checklist_item_id: Mapped[int | None] = mapped_column(ForeignKey("checklist_itens.id"))

    momento: Mapped[MomentoChecklist] = mapped_column(
        sa_enum(MomentoChecklist), nullable=False, index=True
    )
    rotulo: Mapped[str] = mapped_column(String(160), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    observacoes: Mapped[str | None] = mapped_column(Text)
    conferido_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    conferido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    emprestimo: Mapped[Emprestimo] = relationship(back_populates="itens")
