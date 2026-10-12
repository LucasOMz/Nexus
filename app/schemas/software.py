"""Schemas do inventário de software e licenças.

## 🚨 A regra que este arquivo existe para garantir

**`LicencaOut` não tem o campo `chave`.**

Não basta "não usar" o campo: se ele existir no schema de saída, qualquer
listagem devolve a chave para todo mundo — inclusive para quem não tem a
permissão, e inclusive na tela que ninguém revisou.

Por isso a separação é explícita:

| Schema | Tem a chave? | Onde é usado |
|---|---|---|
| `LicencaIn` | **sim**, na entrada | criar e editar |
| `LicencaOut` | **não** — só `chave_mascarada` | listar, detalhar |
| `ChaveRevelada` | **sim**, na saída | **só** em `GET /licencas/{id}/revelar` |

O endpoint de revelar é único, exige permissão própria e **grava auditoria a
cada chamada**. É o gargalo por onde a chave sai — e é isso que o torna
controlável.

## Por que `extra="forbid"` também importa aqui

Com `extra` liberado, um `POST` que mande `chave_mascarada` ou qualquer campo
inesperado passaria em silêncio. Proibido, ele falha — e o erro aparece no
teste, não em produção.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    PlataformaSoftware,
    SituacaoConformidade,
    SituacaoLicenca,
    TipoLicenca,
)


class SemVazios(BaseModel):
    """Recusa string vazia onde se espera conteúdo."""

    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def _limpar(cls, v):
        return v.strip() if isinstance(v, str) else v


# ---------------------------------------------------------------------------
# Software
# ---------------------------------------------------------------------------
class SoftwareIn(SemVazios):
    nome: str = Field(min_length=1, max_length=200)
    fabricante: str | None = Field(default=None, max_length=120)
    versao: str | None = Field(default=None, max_length=60)
    categoria: str | None = Field(default=None, max_length=80)
    plataforma: PlataformaSoftware = PlataformaSoftware.WINDOWS
    descricao: str | None = None
    # Padrões separados por `;`, casados contra o nome reportado pelo OCS.
    padroes: str | None = None
    site: str | None = Field(default=None, max_length=300)
    obrigatorio: bool = False
    planta_id: int | None = None


class SoftwareOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    fabricante: str | None = None
    versao: str | None = None
    categoria: str | None = None
    plataforma: PlataformaSoftware
    descricao: str | None = None
    padroes: str | None = None
    site: str | None = None
    obrigatorio: bool = False
    planta_id: int | None = None
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Licença
# ---------------------------------------------------------------------------
class LicencaIn(SemVazios):
    """Entrada — **aqui** a chave vem em claro, para ser cifrada pelo serviço."""

    software_id: int
    tipo: TipoLicenca = TipoLicenca.PERPETUA
    situacao: SituacaoLicenca = SituacaoLicenca.ATIVA
    seats: int = Field(default=1, ge=1)

    # Texto puro na entrada. O router cifra e **descarta** o valor original;
    # ele nunca é gravado nem devolvido.
    chave: str | None = Field(default=None, max_length=500)

    validade: date | None = None
    numero_pedido: str | None = Field(default=None, max_length=80)
    fornecedor_id: int | None = None
    contrato_id: int | None = None
    valor: Decimal | None = Field(default=None, ge=0)
    valor_mensal: Decimal | None = Field(default=None, ge=0)
    data_compra: date | None = None
    observacoes: str | None = None
    planta_id: int | None = None

    @model_validator(mode="after")
    def _coerente(self):
        # Assinatura sem valor mensal deixaria o custo do parque errado em
        # silêncio — e o financeiro mostraria menos do que se paga.
        if self.tipo == TipoLicenca.ASSINATURA and self.valor_mensal is None:
            raise ValueError("Assinatura exige valor mensal.")

        # Perpétua não vence: uma data aqui faria o alerta de vencimento
        # disparar para sempre, num direito que não expira.
        if self.tipo == TipoLicenca.PERPETUA and self.validade is not None:
            raise ValueError("Licença perpétua não tem data de validade.")

        # OEM vem colada na máquina — não é escolha do comprador.
        if self.tipo == TipoLicenca.OEM and self.valor_mensal is not None:
            raise ValueError("Licença OEM não tem mensalidade.")
        return self


class LicencaOut(BaseModel):
    """Saída — **a chave não está aqui, de propósito.**

    Só `chave_mascarada` (as 4 últimas posições) e `tem_chave`. Quem precisa
    do valor usa `GET /licencas/{id}/revelar`, com permissão e auditoria.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    software_id: int
    tipo: TipoLicenca
    situacao: SituacaoLicenca
    seats: int
    validade: date | None = None
    numero_pedido: str | None = None
    fornecedor_id: int | None = None
    contrato_id: int | None = None
    valor: Decimal | None = None
    valor_mensal: Decimal | None = None
    data_compra: date | None = None
    observacoes: str | None = None
    planta_id: int | None = None
    created_at: datetime | None = None

    # Derivados, calculados na hora — nunca gravados.
    chave_mascarada: str = "—"
    tem_chave: bool = False
    vencida: bool = False
    dias_para_vencer: int | None = None
    seats_usados: int = 0
    seats_livres: int = 0


class ChaveRevelada(BaseModel):
    """A chave em claro. **Só** o endpoint `/revelar` devolve este schema."""

    id: int
    chave: str
    revelada_em: datetime
    aviso: str = (
        "Esta consulta foi registrada na auditoria. Não compartilhe a chave "
        "por e-mail ou mensagem — ela permite uso irregular e pode ser "
        "revogada pelo fabricante."
    )


# ---------------------------------------------------------------------------
# Atribuição
# ---------------------------------------------------------------------------
class AtribuicaoIn(SemVazios):
    """Onde a licença está aplicada: numa máquina **ou** numa pessoa.

    Exatamente um dos dois. Modelar só um caso obrigaria a inventar um "ativo
    virtual" para representar pessoas — e é por isso que a validação é aqui.
    """

    ativo_id: int | None = None
    usuario_id: int | None = None
    versao_instalada: str | None = Field(default=None, max_length=60)
    data_atribuicao: date | None = None
    observacoes: str | None = None

    @model_validator(mode="after")
    def _exatamente_um(self):
        if bool(self.ativo_id) == bool(self.usuario_id):
            raise ValueError(
                "Informe um ativo OU um usuário — não os dois, nem nenhum."
            )
        return self


class AtribuicaoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    licenca_id: int
    ativo_id: int | None = None
    usuario_id: int | None = None
    versao_instalada: str | None = None
    data_atribuicao: date | None = None
    origem: str | None = None
    observacoes: str | None = None
    # Resolvidos para a tela não precisar de uma segunda chamada por linha.
    ativo_patrimonio: str | None = None
    usuario_nome: str | None = None


# ---------------------------------------------------------------------------
# Conformidade — o cruzamento instalado × licenciado
# ---------------------------------------------------------------------------
class LinhaConformidade(BaseModel):
    software_id: int
    software: str
    fabricante: str | None = None
    licenciado: int
    instalado: int
    diferenca: int
    situacao: SituacaoConformidade
    # Os nomes que o OCS reportou, para explicar POR QUE contou assim.
    origens: list[str] = Field(default_factory=list)
    # Software que a empresa exige em toda máquina. Quando aparece com
    # `instalado = 0`, é a pendência mais importante do relatório: alguém
    # decidiu que deveria estar em todas, e não está em nenhuma.
    obrigatorio: bool = False


class ResumoConformidade(BaseModel):
    titulos: int
    excedente: int
    ocioso: int
    sem_licenca: int
    custo_mensal: Decimal
    linhas: list[LinhaConformidade] = Field(default_factory=list)
    atualizado_em: datetime
