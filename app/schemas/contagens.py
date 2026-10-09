"""Schemas do inventário cíclico (contagem)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.contagem import ResultadoItem, StatusContagem
from app.schemas.datas import DatasComFuso


class ContagemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=1, max_length=120)
    dominio: str | None = None
    categoria_id: int | None = None
    localizacao_id: int | None = None
    observacoes: str | None = None


class LeituraIn(BaseModel):
    """Uma leitura no modo sequencial.

    Aceita o mesmo que a tela de Leitura: QR assinado, patrimônio, número de
    série ou hostname. O técnico não deveria ter que saber qual é qual.
    """

    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1, max_length=500)
    observacoes: str | None = None


class ContagemItemOut(DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ativo_id: int | None
    codigo_lido: str
    resultado: ResultadoItem
    lido_em: datetime
    observacoes: str | None
    lido_por_nome: str | None = None
    ativo_patrimonio: str | None = None


class LeituraOut(DatasComFuso):
    """Resposta de uma leitura.

    Devolve o que a tela precisa para dar retorno imediato ao técnico — sem
    isso ele escaneia no escuro, sem saber se aquilo entrou ou não.
    """

    model_config = ConfigDict(from_attributes=True)

    item: ContagemItemOut
    # Texto pronto para exibir, ex.: "Conforme" / "Não cadastrado".
    mensagem: str
    # Já havia sido lido nesta contagem? (evita contar duas vezes a mesma coisa)
    repetido: bool = False
    total_lidos: int = 0


class ContagemOut(DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    planta_id: int | None
    status: StatusContagem
    dominio: str | None
    categoria_id: int | None
    localizacao_id: int | None
    observacoes: str | None
    aberta_em: datetime
    finalizada_em: datetime | None
    aprovada_em: datetime | None
    baixados: int
    lidos: int = 0
    nao_cadastrados: int = 0
    # Quantos ativos o escopo abrange. O técnico sabe o tamanho do trabalho
    # antes de começar a percorrer o setor.
    esperados: int = 0


class DivergenciaOut(BaseModel):
    """Relatório de divergências: o que a auditoria quer ver."""

    # Estava no escopo e não foi lido.
    nao_encontrados: list[dict] = Field(default_factory=list)
    # Foi lido e não pertence ao escopo.
    nao_cadastrados: list[dict] = Field(default_factory=list)
    # Lido mais de uma vez na mesma sessão.
    repetidos: list[dict] = Field(default_factory=list)

    esperados: int = 0
    lidos: int = 0
    conformes: int = 0
    percentual: float = 0.0


class AprovarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Baixar (soft delete) os ativos não encontrados. Desligado por padrão: a
    # aprovação do relatório não deve apagar patrimônio por engano.
    baixar_nao_encontrados: bool = False
    observacoes: str | None = None
