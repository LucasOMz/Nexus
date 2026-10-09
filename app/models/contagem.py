"""Inventário cíclico (contagem).

Uma **contagem** é uma sessão de conferência física: o técnico percorre o
setor escaneando tudo que encontra, e o sistema compara com o que o banco diz
que deveria estar lá.

O resultado é o relatório de divergências:

* **encontrado** — estava no escopo e foi lido (conforme)
* **não encontrado** — está no banco, não foi lido (possível extravio)
* **não cadastrado** — foi lido, mas não pertence ao escopo (achado)

Este módulo é **aditivo**: não altera nenhuma tabela existente. Só lê o que já
existe (ativos, plantas, categorias, localizações).
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, sa_enum

if TYPE_CHECKING:
    from app.models.core import Ativo, Categoria, Localizacao, Planta, Usuario


class StatusContagem(str, enum.Enum):
    """Ciclo de vida de uma contagem."""

    ABERTA = "aberta"            # criada, ninguém começou a ler
    EM_CONTAGEM = "em_contagem"  # já há leituras
    FINALIZADA = "finalizada"    # leitura encerrada, aguardando decisão
    APROVADA = "aprovada"        # divergências aceitas; baixas aplicadas
    CANCELADA = "cancelada"


class ResultadoItem(str, enum.Enum):
    """Como cada leitura se comportou em relação ao escopo."""

    CONFORME = "conforme"              # estava no escopo e foi lido
    NAO_CADASTRADO = "nao_cadastrado"  # lido, mas fora do escopo


class Contagem(BaseModel, Base):
    """Uma sessão de contagem física."""

    __tablename__ = "contagens"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    # Planta dona da contagem (mesma regra de multi-planta do resto do sistema).
    planta_id: Mapped[int | None] = mapped_column(ForeignKey("plantas.id"), index=True)

    status: Mapped[StatusContagem] = mapped_column(
        sa_enum(StatusContagem), default=StatusContagem.ABERTA, nullable=False, index=True
    )

    # --- Escopo -----------------------------------------------------------
    # Nulo = sem restrição naquela dimensão. Todos os campos nulos = inventário
    # completo da planta (o mais comum na primeira vez).
    dominio: Mapped[str | None] = mapped_column(String(20))
    categoria_id: Mapped[int | None] = mapped_column(ForeignKey("categorias.id"))
    localizacao_id: Mapped[int | None] = mapped_column(ForeignKey("localizacoes.id"))

    observacoes: Mapped[str | None] = mapped_column(Text)

    # --- Ciclo de vida ----------------------------------------------------
    aberta_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    aberta_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finalizada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    aprovada_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    aprovada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Quantos ativos foram baixados na aprovação (guarda o rastro da decisão).
    baixados: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    planta: Mapped[Planta | None] = relationship()
    categoria: Mapped[Categoria | None] = relationship()
    localizacao: Mapped[Localizacao | None] = relationship()
    aberta_por: Mapped[Usuario | None] = relationship(foreign_keys=[aberta_por_id])
    aprovada_por: Mapped[Usuario | None] = relationship(foreign_keys=[aprovada_por_id])

    itens: Mapped[list[ContagemItem]] = relationship(
        back_populates="contagem", cascade="all, delete-orphan"
    )

    # --- Contadores para o relatório --------------------------------------
    @property
    def lidos(self) -> int:
        return len(self.itens)

    @property
    def nao_cadastrados(self) -> int:
        return len([i for i in self.itens if i.resultado == ResultadoItem.NAO_CADASTRADO])


class ContagemItem(BaseModel, Base):
    """Uma leitura dentro de uma contagem.

    Guarda o **código lido** mesmo quando não corresponde a nenhum ativo: é
    justamente esse caso ("não cadastrado") que interessa à auditoria.
    """

    __tablename__ = "contagem_itens"

    id: Mapped[int] = mapped_column(primary_key=True)
    contagem_id: Mapped[int] = mapped_column(
        ForeignKey("contagens.id"), nullable=False, index=True
    )
    ativo_id: Mapped[int | None] = mapped_column(ForeignKey("ativos.id"), index=True)

    codigo_lido: Mapped[str] = mapped_column(String(500), nullable=False)
    resultado: Mapped[ResultadoItem] = mapped_column(
        sa_enum(ResultadoItem), default=ResultadoItem.CONFORME, nullable=False
    )

    lido_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    lido_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    observacoes: Mapped[str | None] = mapped_column(Text)

    contagem: Mapped[Contagem] = relationship(back_populates="itens")
    ativo: Mapped[Ativo | None] = relationship()
    lido_por: Mapped[Usuario | None] = relationship(foreign_keys=[lido_por_id])

    @property
    def lido_por_nome(self) -> str | None:
        u = getattr(self, "lido_por", None)
        return u.nome if u is not None else None

    @property
    def ativo_patrimonio(self) -> str | None:
        a = getattr(self, "ativo", None)
        return a.patrimonio if a is not None else None
