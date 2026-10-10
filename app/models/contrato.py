"""Contrato de locação (ou compra) que cobre um conjunto de ativos.

## Por que o contrato é uma entidade, e não campos no ativo

A mensalidade é **do contrato**, não do equipamento: um contrato cobre 50
notebooks por um valor único. Guardar `valor_mensal` em cada ativo obrigaria a
repetir o mesmo número 50 vezes — e a corrigi-lo 50 vezes quando o contrato
fosse reajustado.

O custo por equipamento é **derivado**: `valor_mensal / nº de ativos no
contrato`. Nunca gravado — porque quando um equipamento é devolvido a
mensalidade não cai, e o custo dos que ficaram sobe. Um valor gravado mentiria
a partir da primeira devolução.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, sa_enum
from app.models.enums import TipoContrato

if TYPE_CHECKING:
    from app.models.core import Ativo, Fornecedor, Planta


class Contrato(BaseModel, Base):
    """Contrato de locação, comodato ou compra.

    `fim` nulo significa prazo indeterminado — a locação segue enquanto
    alguém não encerrar. Não é o mesmo que "sem prazo definido ainda": o
    sistema não inventa uma data.
    """

    __tablename__ = "contratos"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Planta dona do contrato. `None` = cobre todas (contrato corporativo).
    #
    # Sem este campo, um contrato apareceria para o usuário de qualquer
    # planta — e o isolamento multi-tenant do resto do sistema não valeria
    # para o financeiro. É o mesmo padrão de `Usuario.planta_id`.
    planta_id: Mapped[int | None] = mapped_column(ForeignKey("plantas.id"), index=True)
    planta: Mapped[Planta | None] = relationship(lazy="joined")

    # Número do contrato no fornecedor. Único: é por ele que se acha o
    # documento quando alguém liga perguntando.
    numero: Mapped[str] = mapped_column(String(80), unique=True, index=True)

    tipo: Mapped[TipoContrato] = mapped_column(
        sa_enum(TipoContrato), default=TipoContrato.LOCACAO, nullable=False, index=True
    )

    fornecedor_id: Mapped[int | None] = mapped_column(ForeignKey("fornecedores.id"), index=True)
    fornecedor: Mapped[Fornecedor | None] = relationship(lazy="joined")

    inicio: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # Nulo = prazo indeterminado (renovação automática).
    fim: Mapped[date | None] = mapped_column(Date, index=True)

    # Locação: o que se paga todo mês. Nulo em comodato (não há cobrança).
    valor_mensal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    # Compra: o valor total, uma vez.
    valor_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    # Dia do mês em que vence. Serve para o calendário de pagamentos — sem
    # ele, o financeiro só sabe "todo mês", não "quando".
    dia_vencimento: Mapped[int | None] = mapped_column(Integer)

    observacoes: Mapped[str | None] = mapped_column(Text)

    # --- Relacionamentos --------------------------------------------------
    # `passive_deletes` deixa o banco cuidar do desvínculo; sem isso, o
    # SQLAlchemy tentaria carregar todos os ativos para anular um a um.
    ativos: Mapped[list[Ativo]] = relationship(
        back_populates="contrato", lazy="selectin", passive_deletes=True
    )

    # --- Derivados --------------------------------------------------------
    @property
    def em_aberto(self) -> bool:
        """Ainda vigente? Sem `fim`, é indeterminado e está sempre em aberto."""
        return self.fim is None or self.fim >= date.today()

    @property
    def dias_para_vencer(self) -> int | None:
        """Quantos dias faltam para o fim. `None` se indeterminado.

        Negativo quando já venceu — é o que o alerta usa para separar
        "vencendo" de "vencido".
        """
        if self.fim is None:
            return None
        return (self.fim - date.today()).days

    @property
    def valor_mensal_por_ativo(self) -> Decimal | None:
        """Rateio: quanto cada equipamento custa por mês.

        Calculado na hora, de propósito. Ver o docstring do módulo.
        """
        if not self.valor_mensal or not self.ativos:
            return None
        vivos = [a for a in self.ativos if getattr(a, "deleted_at", None) is None]
        if not vivos:
            return None
        return (Decimal(self.valor_mensal) / Decimal(len(vivos))).quantize(Decimal("0.01"))
