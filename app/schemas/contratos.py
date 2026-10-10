"""Schemas de contrato — locação, comodato e compra."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import TipoContrato


class SemVazios(BaseModel):
    """Recusa string vazia onde se espera conteúdo."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def _limpar(cls, v):
        return v.strip() if isinstance(v, str) else v


class ContratoIn(SemVazios):
    numero: str = Field(min_length=1, max_length=80)
    tipo: TipoContrato = TipoContrato.LOCACAO
    planta_id: int | None = None
    fornecedor_id: int | None = None
    inicio: date
    fim: date | None = None
    valor_mensal: Decimal | None = None
    valor_total: Decimal | None = None
    dia_vencimento: int | None = Field(default=None, ge=1, le=31)
    observacoes: str | None = None

    @model_validator(mode="after")
    def _coerente(self):
        # Um contrato que termina antes de começar é erro de digitação, e
        # deixaria o alerta de vencimento disparando desde o primeiro dia.
        if self.fim is not None and self.fim < self.inicio:
            raise ValueError("A data de fim não pode ser anterior ao início.")

        # Locação sem mensalidade não é locação — é comodato. Recusar aqui
        # evita um contrato que nunca gera custo e ninguém entende por quê.
        if self.tipo == TipoContrato.LOCACAO and not self.valor_mensal:
            raise ValueError("Contrato de locação precisa do valor mensal.")

        if self.tipo == TipoContrato.COMODATO and self.valor_mensal:
            raise ValueError(
                "Comodato não tem mensalidade. Se há cobrança, o tipo é locação."
            )
        return self


class ContratoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    numero: str
    tipo: TipoContrato
    planta_id: int | None = None
    fornecedor_id: int | None = None
    inicio: date
    fim: date | None = None
    valor_mensal: Decimal | None = None
    valor_total: Decimal | None = None
    dia_vencimento: int | None = None
    observacoes: str | None = None

    # Derivados — calculados, não colunas.
    em_aberto: bool = True
    dias_para_vencer: int | None = None
    # Quantos equipamentos o contrato cobre hoje. A tela mostra o rateio a
    # partir dele, e ele muda quando alguém devolve um ativo.
    total_ativos: int = 0
    valor_mensal_por_ativo: Decimal | None = None


class VincularAtivosIn(SemVazios):
    """Quais ativos passam a fazer parte do contrato."""

    ativo_ids: list[int] = Field(min_length=1)
    # Ao vincular, marcar os ativos como locados. Padrão `True` porque é o
    # caso comum: quem está vinculando a uma locação está locando.
    marcar_como_locado: bool = True


class ExercerCompraIn(SemVazios):
    """Exercer a opção de compra ao fim da locação."""

    # Preço pago. Obrigatório: sem ele, o ativo entraria no patrimônio com
    # valor zero e a depreciação não teria sobre o que incidir.
    valor: Decimal = Field(gt=0)
    data: date | None = None
    observacoes: str | None = None
