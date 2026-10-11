"""Inventário de software e licenças.

## Por que três entidades, e não um campo em `Ativo`

**Uma licença não é um bem único.** Você compra "50 seats de Office" e instala
em 63 máquinas. O que existe fisicamente são *as instalações*; o direito é *a
licença*. Guardar isso como um ativo com quantidade não caberia em `Ativo`.

```
Software (o produto)     Licença (o direito)      Atribuição (o uso)
```

Uma `Licença` tem várias `Atribuições` — 50 seats, 50 linhas. E a `Atribuição`
aponta para **um ativo ou um usuário**, porque nem toda licença é por máquina:
Adobe e Microsoft 365 são por pessoa.

## A chave é um segredo

Ver `app/core/segredos.py`. Aqui ficam só as colunas: o valor **cifrado**, a
**versão** da chave mestra, a **impressão** (4 últimas posições, para
conferência) e o **hash** (para achar duplicata sem decifrar).

**Nenhuma coluna guarda a chave em claro.**
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel, sa_enum
from app.models.enums import PlataformaSoftware, SituacaoLicenca, TipoLicenca

if TYPE_CHECKING:
    from app.models.core import Ativo, Planta, Usuario


class Software(BaseModel, Base):
    """O produto de software, sem relação com quantas licenças existem dele.

    ## `padroes` — o campo que faz o cruzamento com o OCS funcionar

    O OCS Inventory reporta `Microsoft Office LTSC Professional Plus 2021`.
    A licença está cadastrada como `Office 2021`. Comparar por igualdade **não
    acha nada** — e um relatório de conformidade que não acha nada é inútil.

    Cada software guarda padrões de reconhecimento (`microsoft office*2021`).
    Sem eles, o inventário de software vira uma lista bonita que ninguém usa
    para decidir.
    """

    __tablename__ = "softwares"

    id: Mapped[int] = mapped_column(primary_key=True)

    nome: Mapped[str] = mapped_column(String(200), index=True)
    fabricante: Mapped[str | None] = mapped_column(String(120), index=True)
    versao: Mapped[str | None] = mapped_column(String(60))
    categoria: Mapped[str | None] = mapped_column(String(80), index=True)
    plataforma: Mapped[PlataformaSoftware] = mapped_column(
        sa_enum(PlataformaSoftware), default=PlataformaSoftware.WINDOWS
    )
    descricao: Mapped[str | None] = mapped_column(Text)

    # Padrões separados por `;`. Casados contra o nome reportado pelo OCS.
    padroes: Mapped[str | None] = mapped_column(Text)
    site: Mapped[str | None] = mapped_column(String(300))

    # Software que a empresa exige em toda máquina. Serve para o relatório
    # apontar o que FALTA, e não só o que sobra.
    obrigatorio: Mapped[bool] = mapped_column(Boolean, default=False)

    planta_id: Mapped[int | None] = mapped_column(ForeignKey("plantas.id"))
    planta: Mapped["Planta | None"] = relationship()

    licencas: Mapped[list["Licenca"]] = relationship(
        back_populates="software", cascade="all, delete-orphan"
    )

    def lista_de_padroes(self) -> list[str]:
        """Os padrões em lista, sem vazios."""
        if not self.padroes:
            return []
        return [p.strip().lower() for p in self.padroes.split(";") if p.strip()]


class Licenca(BaseModel, Base):
    """O direito de uso: uma compra, uma assinatura ou um contrato.

    ## A chave nunca é gravada em claro

    | Coluna | Guarda | Serve para |
    |---|---|---|
    | `chave_cifrada` | o valor cifrado | recuperar a chave, com permissão |
    | `chave_versao` | a versão da chave mestra | rotação sem recadastro |
    | `chave_impressao` | as 4 últimas posições | conferir de qual licença se trata |
    | `chave_hash` | SHA-256 normalizado | achar duplicata **sem decifrar** |
    """

    __tablename__ = "licencas"

    id: Mapped[int] = mapped_column(primary_key=True)

    software_id: Mapped[int] = mapped_column(ForeignKey("softwares.id"), index=True)
    software: Mapped["Software"] = relationship(back_populates="licencas")

    tipo: Mapped[TipoLicenca] = mapped_column(sa_enum(TipoLicenca), index=True)
    situacao: Mapped[SituacaoLicenca] = mapped_column(
        sa_enum(SituacaoLicenca), default=SituacaoLicenca.ATIVA, index=True
    )

    # --- O segredo -------------------------------------------------------
    chave_cifrada: Mapped[bytes | None] = mapped_column(LargeBinary)
    chave_versao: Mapped[int] = mapped_column(Integer, default=1)
    chave_impressao: Mapped[str | None] = mapped_column(String(8))
    chave_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    # --- O direito -------------------------------------------------------
    seats: Mapped[int] = mapped_column(Integer, default=1)
    # Nulo em perpétua e em open source: perpétua não vence.
    validade: Mapped[date | None] = mapped_column(Date, index=True)

    numero_pedido: Mapped[str | None] = mapped_column(String(80))
    fornecedor_id: Mapped[int | None] = mapped_column(ForeignKey("fornecedores.id"))

    # Assinatura SaaS É locação — reusa o contrato que já existe, com
    # mensalidade, vigência e o alerta de vencimento já funcionando.
    contrato_id: Mapped[int | None] = mapped_column(ForeignKey("contratos.id"))

    valor: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    valor_mensal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    data_compra: Mapped[date | None] = mapped_column(Date)

    observacoes: Mapped[str | None] = mapped_column(Text)
    planta_id: Mapped[int | None] = mapped_column(ForeignKey("plantas.id"))

    atribuicoes: Mapped[list["AtribuicaoLicenca"]] = relationship(
        back_populates="licenca", cascade="all, delete-orphan"
    )

    # --- Derivados (nunca gravados) --------------------------------------

    @property
    def vencida(self) -> bool:
        """Só assinatura e trial vencem. Perpétua não tem data para vencer."""
        if self.validade is None:
            return False
        if self.tipo in (TipoLicenca.PERPETUA, TipoLicenca.OPEN_SOURCE):
            return False
        return self.validade < date.today()

    @property
    def dias_para_vencer(self) -> int | None:
        if self.validade is None:
            return None
        return (self.validade - date.today()).days

    @property
    def seats_usados(self) -> int:
        """Atribuições vivas. Contado no banco, não em memória, quando possível."""
        return len([a for a in self.atribuicoes if a.deleted_at is None])

    @property
    def seats_livres(self) -> int:
        return max(0, self.seats - self.seats_usados)

    @property
    def chave_mascarada(self) -> str:
        """O que a tela mostra. Nunca o valor."""
        from app.core import segredos

        return segredos.mascarar(self.chave_impressao)

    def tem_chave(self) -> bool:
        return bool(self.chave_cifrada)


class AtribuicaoLicenca(BaseModel, Base):
    """Onde uma licença está aplicada: numa máquina ou numa pessoa.

    ## Por que aceita os dois

    Licença por dispositivo (Office LTSC, AutoCAD) acompanha o **ativo**.
    Licença por pessoa (Microsoft 365, Adobe CC) acompanha o **usuário** — e
    a mesma pessoa usa duas máquinas com um único direito.

    Exatamente um dos dois é preenchido. Modelar só um dos casos obrigaria a
    inventar um "ativo virtual" para representar pessoas.
    """

    __tablename__ = "atribuicoes_licenca"

    id: Mapped[int] = mapped_column(primary_key=True)

    licenca_id: Mapped[int] = mapped_column(ForeignKey("licencas.id"), index=True)
    licenca: Mapped["Licenca"] = relationship(back_populates="atribuicoes")

    ativo_id: Mapped[int | None] = mapped_column(ForeignKey("ativos.id"), index=True)
    ativo: Mapped["Ativo | None"] = relationship()

    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), index=True)
    usuario: Mapped["Usuario | None"] = relationship()

    # Versão instalada, quando difere da licenciada — comum em parque misto.
    versao_instalada: Mapped[str | None] = mapped_column(String(60))
    data_atribuicao: Mapped[date | None] = mapped_column(Date)
    # Nome como o OCS reportou. É o que permite explicar por que a
    # conformidade contou (ou não) esta instalação.
    origem: Mapped[str | None] = mapped_column(String(40))
    observacoes: Mapped[str | None] = mapped_column(Text)


class SoftwareInstalado(BaseModel, Base):
    """O que o OCS Inventory reportou instalado numa máquina.

    ## Por que é uma tabela, e não um campo

    Uma máquina tem dezenas de programas, e o OCS reenvia a lista a cada
    coleta. Guardar como campo repetiria a lista inteira a cada sincronização.

    ## Por que o nome cru é guardado

    `conformidade.casa()` compara este nome com os padrões cadastrados em
    `Software.padroes`. Guardar o nome **como veio** é o que permite explicar
    depois por que uma instalação contou (ou não) — e ajustar o padrão quando
    ele estiver errado.

    Normalizar na entrada perderia a evidência: o operador veria o padrão
    falhar e não teria com o que comparar.
    """

    __tablename__ = "softwares_instalados"

    id: Mapped[int] = mapped_column(primary_key=True)

    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), index=True)
    ativo: Mapped["Ativo | None"] = relationship()

    # Nome exatamente como o OCS reportou, sem normalização.
    nome: Mapped[str] = mapped_column(String(300), index=True)
    versao: Mapped[str | None] = mapped_column(String(80))
    fabricante: Mapped[str | None] = mapped_column(String(120))
    # Para o relatório poder separar TI de impressoras.
    dominio: Mapped[str | None] = mapped_column(String(20), index=True)
    origem: Mapped[str] = mapped_column(String(40), default="ocs")
    coletado_em: Mapped[datetime | None] = mapped_column(DateTime)

    # Qual software cadastrado reconheceu esta instalação. Nulo = nenhum.
    #
    # Gravado na reconciliação, e não calculado a cada consulta: com 300 mil
    # linhas, casar tudo de novo a cada abertura da tela seria inviável.
    software_id: Mapped[int | None] = mapped_column(ForeignKey("softwares.id"), index=True)
