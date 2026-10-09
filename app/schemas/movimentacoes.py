"""Schemas de movimentações."""
from __future__ import annotations

from datetime import datetime

from pydantic import ConfigDict, Field, model_validator

from app.models.enums import TipoMov
from app.schemas.common import SemVazios
from app.schemas.datas import DatasComFuso


class MovimentacaoCreate(SemVazios):
    model_config = ConfigDict(extra="forbid")

    tipo: TipoMov
    ativo_id: int | None = None
    produto_id: int | None = None
    quantidade: int = Field(default=1, ge=1)
    origem_localizacao_id: int | None = None
    destino_localizacao_id: int | None = None
    origem_usuario_id: int | None = None
    destino_usuario_id: int | None = None
    observacoes: str | None = None
    # Finalidade da SAÍDA de consumível. Numa entrada não se aplica.
    finalidade: str | None = None
    ativo_instalado_id: int | None = None

    @model_validator(mode="after")
    def _finalidade_valida(self) -> MovimentacaoCreate:
        """A finalidade só existe em saída de consumível.

        `descarte` não precisa de equipamento. `instalacao` precisa — é o que
        dá sentido ao registro: saber em QUAL máquina o consumível foi usado.
        """
        if self.finalidade is None:
            # Sem finalidade, um equipamento informado não faz sentido.
            if self.ativo_instalado_id is not None:
                raise ValueError(
                    "Informe a finalidade para dizer em qual ativo o consumível foi instalado."
                )
            return self

        if self.finalidade not in ("descarte", "instalacao"):
            raise ValueError("A finalidade deve ser 'descarte' ou 'instalacao'.")

        if self.tipo != TipoMov.SAIDA:
            raise ValueError("A finalidade só se aplica a uma SAÍDA de consumível.")

        if self.produto_id is None:
            raise ValueError("A finalidade só se aplica a consumíveis.")

        if self.finalidade == "instalacao" and self.ativo_instalado_id is None:
            raise ValueError(
                "Para instalação, informe em qual ativo o consumível foi instalado."
            )

        if self.finalidade == "descarte" and self.ativo_instalado_id is not None:
            raise ValueError("Descarte não deve indicar um ativo de instalação.")

        return self

    @model_validator(mode="after")
    def _exactly_one_ref(self) -> MovimentacaoCreate:
        # Movimentação referencia OU um ativo OU um produto (nunca ambos/nem nenhum).
        if (self.ativo_id is None) == (self.produto_id is None):
            raise ValueError("Informe exatamente um de: ativo_id ou produto_id")
        return self


class MovimentacaoOut(DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: TipoMov
    ativo_id: int | None
    produto_id: int | None
    quantidade: int
    origem_localizacao_id: int | None
    destino_localizacao_id: int | None
    origem_usuario_id: int | None
    destino_usuario_id: int | None
    data_mov: datetime
    observacoes: str | None
    usuario_id: int | None
    # Nomes resolvidos, para o histórico ser legível ("Fulano", "Tonner HP 26A")
    # em vez de "usuário 3", "produto 7".
    usuario_nome: str | None = None
    produto_nome: str | None = None
    produto_sku: str | None = None
    ativo_patrimonio: str | None = None
    # Finalidade da saída: "Descarte" ou "Instalação", já em texto.
    finalidade: str | None = None
    finalidade_rotulo: str | None = None
    ativo_instalado_id: int | None = None
    ativo_instalado_patrimonio: str | None = None
    ativo_instalado_hostname: str | None = None
