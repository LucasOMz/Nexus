"""Schemas de ativos e suas extensões (TI / Impressora)."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import ConfigDict, Field

from app.models.enums import (
    Conectividade,
    Dominio,
    FormaAquisicao,
    StatusAtivo,
    TipoImpressao,
    TipoItem,
    TipoSuprimento,
)
from app.schemas.common import SemVazios
from app.schemas.datas import DatasComFuso


class AtivoTIBase(SemVazios):
    model_config = ConfigDict(extra="forbid")

    hostname: str | None = Field(default=None, max_length=120)
    mac_address: str | None = Field(default=None, max_length=17)
    ip: str | None = Field(default=None, max_length=45)
    so: str | None = Field(default=None, max_length=120)
    dominio_ad: str | None = Field(default=None, max_length=120)
    cpu: str | None = Field(default=None, max_length=120)
    ram_gb: int | None = Field(default=None, ge=0)
    armazenamento_gb: int | None = Field(default=None, ge=0)


class AtivoTIOut(AtivoTIBase):
    model_config = ConfigDict(from_attributes=True)

    ativo_id: int


class AtivoImpressoraBase(SemVazios):
    model_config = ConfigDict(extra="forbid")

    ip: str | None = Field(default=None, max_length=45)
    hostname: str | None = Field(default=None, max_length=120)
    driver: str | None = Field(default=None, max_length=200)
    tipo_impressao: TipoImpressao = TipoImpressao.LASER
    colorida: bool = False
    contador_paginas: int = Field(default=0, ge=0)
    conectividade: Conectividade = Conectividade.REDE


class AtivoImpressoraOut(AtivoImpressoraBase):
    model_config = ConfigDict(from_attributes=True)

    ativo_id: int


class AtivoBase(SemVazios):
    model_config = ConfigDict(extra="forbid")

    patrimonio: str = Field(min_length=1, max_length=80)
    numero_serie: str | None = Field(default=None, max_length=160)
    modelo: str | None = Field(default=None, max_length=160)
    marca: str | None = Field(default=None, max_length=120)
    categoria_id: int | None = None
    fornecedor_id: int | None = None
    localizacao_id: int | None = None
    departamento_id: int | None = None
    data_aquisicao: date | None = None
    data_garantia: date | None = None
    valor: float | None = Field(default=None, ge=0)
    observacoes: str | None = None
    foto_id: int | None = None

    # --- Como o equipamento chegou ao parque ------------------------------
    # O padrão COMPRADO preserva o comportamento anterior: todo ativo
    # cadastrado por um cliente que não conhece o campo continua comprado,
    # que é o que ele sempre foi.
    forma_aquisicao: FormaAquisicao = FormaAquisicao.COMPRADO
    # Contrato do qual o ativo faz parte (locação/comodato/compra em lote).
    contrato_id: int | None = None
    # Preço de compra ao fim da locação, quando o contrato já o define.
    valor_residual: float | None = Field(default=None, ge=0)


class AtivoCreate(AtivoBase):
    dominio: Dominio
    tipo_item: TipoItem = TipoItem.ATIVO
    status: StatusAtivo = StatusAtivo.ESTOQUE
    # Payload da etiqueta EM BRANCO que foi lida (TIZERADO:...). Serve para
    # vincular a etiqueta já impressa ao equipamento que está sendo cadastrado.
    # Payload TIATIVO vindo do cliente é ignorado (o sistema gera o seu).
    qr_payload: str | None = None
    ti: AtivoTIBase | None = None
    impressora: AtivoImpressoraBase | None = None


class AtivoUpdate(SemVazios):
    """Atualização de ativo.

    `dominio` e `tipo_item` são aceitos **apenas por compatibilidade**: o
    formulário envia os dois no mesmo corpo do cadastro e da edição. Eles NÃO
    alteram o ativo (o inventário é definido na criação, porque determina qual
    extensão 1:1 existe). Se vierem diferentes, a API responde com erro claro.
    """

    model_config = ConfigDict(extra="forbid")

    patrimonio: str | None = Field(default=None, min_length=1, max_length=80)
    numero_serie: str | None = Field(default=None, max_length=160)
    modelo: str | None = Field(default=None, max_length=160)
    marca: str | None = Field(default=None, max_length=120)
    status: StatusAtivo | None = None
    dominio: Dominio | None = None
    tipo_item: TipoItem | None = None
    categoria_id: int | None = None
    fornecedor_id: int | None = None
    localizacao_id: int | None = None
    departamento_id: int | None = None
    data_aquisicao: date | None = None
    data_garantia: date | None = None
    valor: float | None = Field(default=None, ge=0)
    observacoes: str | None = None
    foto_id: int | None = None
    ti: AtivoTIBase | None = None
    impressora: AtivoImpressoraBase | None = None


class AtivoOut(AtivoBase, DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int
    # Sigla da planta — aparece na coluna "Planta" da tela de Ativos.
    planta_id: int | None = None
    planta_sigla: str | None = None
    # Nome de rede, venha de TI ou de impressora. Vem da propriedade
    # `Ativo.hostname`, que resolve qual das duas fichas está preenchida.
    #
    # Existe para a busca por hostname MOSTRAR o que casou: quem digita
    # "NTAT" precisa ver que o resultado é aquela máquina, e não desconfiar
    # de um item cujo texto não contém o que foi digitado.
    hostname: str | None = None
    # --- Empréstimo (preenchido enquanto o ativo está emprestado) ---------
    numero_chamado: str | None = None
    emprestado_em: date | None = None
    devolucao_prevista: date | None = None
    emprestado_para_id: int | None = None
    emprestado_para_nome: str | None = None
    emprestimo_atrasado: bool = False
    dominio: Dominio
    tipo_item: TipoItem
    status: StatusAtivo
    qr_payload: str | None = None
    ti: AtivoTIOut | None = None
    impressora: AtivoImpressoraOut | None = None
    created_at: datetime
    updated_at: datetime


class StatusChange(SemVazios):
    model_config = ConfigDict(extra="forbid")

    status: StatusAtivo


class AtribuirRequest(SemVazios):
    model_config = ConfigDict(extra="forbid")

    usuario_id: int
    localizacao_id: int | None = None
    observacoes: str | None = None


class SuprimentoBase(SemVazios):
    model_config = ConfigDict(extra="forbid")

    tipo: TipoSuprimento
    modelo: str | None = Field(default=None, max_length=160)
    cor: str | None = Field(default=None, max_length=60)
    rendimento_paginas: int | None = Field(default=None, ge=0)
    estoque_atual: int = Field(default=0, ge=0)
    estoque_minimo: int = Field(default=0, ge=0)


class SuprimentoCreate(SuprimentoBase):
    pass


class SuprimentoOut(SuprimentoBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ativo_id: int


class LeituraContadorCreate(SemVazios):
    model_config = ConfigDict(extra="forbid")

    contador: int = Field(ge=0)
    observacoes: str | None = None


class LeituraContadorOut(DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ativo_id: int
    contador: int
    data_leitura: datetime
    observacoes: str | None = None
