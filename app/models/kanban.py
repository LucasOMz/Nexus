"""Kanban — buckets, atividades e checklist.

## O modelo

```
Bucket 1 ──── n Atividade ──── n AtividadeItem  (checklist)
                    │
                    └──── n AtividadeResponsavel ──── Usuario
```

**Bucket** é a coluna ("A fazer", "Em andamento", "Concluído").
**Atividade** é o cartão. **Item** é a caixinha de checklist dentro do cartão.

## Por que `ordem` é inteiro e não data

Arrastar não tem "quando". A posição é uma **sequência explícita**, e mover
um cartão reescreve a ordem dos vizinhos. Guardar data de modificação
funcionaria por acaso até dois cartões serem movidos no mesmo segundo.

## Por que a planta fica no bucket

Atividade herda a planta do bucket. Duplicar a coluna nas duas tabelas
abriria espaço para divergência — e a consulta já passa pelo bucket.

## Escopo por planta, como o resto

Um técnico da planta A não vê o quadro da planta B. É a mesma regra de
`aplicar_filtro` usada em ativos e contratos.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel


class Bucket(BaseModel, Base):
    __tablename__ = "kanban_buckets"

    id: Mapped[int] = mapped_column(primary_key=True)

    planta_id: Mapped[int | None] = mapped_column(ForeignKey("plantas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(80))
    ordem: Mapped[int] = mapped_column(Integer, default=0, index=True)

    # Cor do cabeçalho, no padrão do sistema. Vazio usa a cor padrão da tela.
    cor: Mapped[str | None] = mapped_column(String(20))

    atividades: Mapped[list["Atividade"]] = relationship(
        back_populates="bucket", cascade="all, delete-orphan"
    )


class Atividade(BaseModel, Base):
    __tablename__ = "kanban_atividades"

    id: Mapped[int] = mapped_column(primary_key=True)

    bucket_id: Mapped[int] = mapped_column(ForeignKey("kanban_buckets.id"), index=True)
    bucket: Mapped[Bucket] = relationship(back_populates="atividades")

    titulo: Mapped[str] = mapped_column(String(200), index=True)
    descricao: Mapped[str | None] = mapped_column(Text)

    ordem: Mapped[int] = mapped_column(Integer, default=0, index=True)

    # Prazo. É o que aparece na agenda e dispara o aviso de vencimento.
    prazo: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    # Nulo enquanto aberta; carimbado ao marcar como concluída. Guardar a data
    # permite "concluídas nos últimos 30 dias" sem depender do bucket.
    concluida_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- prioridade e progresso ----------------------------------------
    #
    # Prioridade ordena a atenção: urgente pinta a borda do cartão. Guardar
    # como texto simples evita migração de enum no PostgreSQL.
    prioridade: Mapped[str] = mapped_column(String(10), default="normal", index=True)

    # Progresso declarado à mão, 0 a 100. Independente do checklist: serve
    # para "estou na metade" sem marcar item nenhum.
    progresso: Mapped[int] = mapped_column(Integer, default=0)

    # Quando começa. O prazo já existia; juntos dão o intervalo da tarefa.
    data_inicio: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    criado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))

    itens: Mapped[list["AtividadeItem"]] = relationship(
        back_populates="atividade", cascade="all, delete-orphan"
    )
    responsaveis: Mapped[list["AtividadeResponsavel"]] = relationship(
        back_populates="atividade", cascade="all, delete-orphan"
    )

    @property
    def total_itens(self) -> int:
        return len(self.itens)

    @property
    def itens_feitos(self) -> int:
        return sum(1 for i in self.itens if i.feito)

    @property
    def concluida(self) -> bool:
        return self.concluida_em is not None

    @property
    def atrasada(self) -> bool:
        if self.prazo is None or self.concluida_em is not None:
            return False
        return self.prazo < datetime.now(self.prazo.tzinfo)


class AtividadeItem(BaseModel, Base):
    """Uma caixinha de checklist dentro do cartão."""

    __tablename__ = "kanban_itens"

    id: Mapped[int] = mapped_column(primary_key=True)

    atividade_id: Mapped[int] = mapped_column(
        ForeignKey("kanban_atividades.id"), index=True
    )
    atividade: Mapped[Atividade] = relationship(back_populates="itens")

    texto: Mapped[str] = mapped_column(String(300))
    feito: Mapped[bool] = mapped_column(Boolean, default=False)
    ordem: Mapped[int] = mapped_column(Integer, default=0)


class AtividadeResponsavel(BaseModel, Base):
    """Quem responde pela atividade.

    Tabela própria e não uma coluna: uma atividade pode ter mais de um
    responsável, e um responsável pode ter várias atividades.
    """

    __tablename__ = "kanban_responsaveis"
    __table_args__ = (
        UniqueConstraint("atividade_id", "usuario_id", name="uq_kanban_responsavel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    atividade_id: Mapped[int] = mapped_column(
        ForeignKey("kanban_atividades.id"), index=True
    )
    atividade: Mapped[Atividade] = relationship(back_populates="responsaveis")

    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
