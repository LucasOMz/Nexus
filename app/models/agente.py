"""Agentes — códigos de instalação, tokens de máquina e fila de cadastro.

## O modelo em três peças

1. **`CodigoInstalacao`** — o portão. Gerado no painel, com validade e limite
   de usos. Serve **só para registrar**: não lê inventário, não altera ativo.

2. **`TokenAgente`** — a credencial de operação. Nasce na troca do código e
   vale para **uma** máquina. É o que o agente usa em toda coleta.

3. **`EquipamentoPendente`** — a fila. Máquina que apareceu sem serial válido
   (ou sem ativo cadastrado) fica aqui até alguém decidir o identificador.

## Duas decisões de segurança que valem explicar

### Segredos são guardados com hash

Nem o código de instalação nem o token ficam em texto no banco. Se o dump
vazar, ninguém consegue usá-los.

**O custo**: o código só pode ser **mostrado uma vez**, na criação. Perdeu,
gera outro. É o comportamento certo para um segredo — e é o mesmo que o
sistema já faz com a senha.

### O token pertence a um ativo

`TokenAgente.ativo_id` não é decoração: o endpoint de inventário usa esse
vínculo para decidir **em qual ativo escrever**. Um token vazado escreve
inventário de **uma** máquina, e nada mais.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, BaseModel


class CodigoInstalacao(BaseModel, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    """Código que autoriza o registro de máquinas.

    ## Por que não um código fixo de frota

    Um código permanente significa que uma cópia vazada permite registrar
    máquinas para sempre. Com validade e limite de usos, a janela de
    exposição é **a implantação** — não a vida do parque.

    Para 3.000 máquinas, usa-se **um** código com `usos_max = 3500` e
    validade de alguns dias, revogado ao fim da distribuição.
    """

    __tablename__ = "codigos_instalacao"

    # Guarda o SHA-256, não o código. Mostrado uma única vez, na criação.
    # Planta dona das máquinas registradas com este código.
    #
    # O agente não tem sessão: sem isto, toda máquina da frota nasce na
    # primeira planta ativa. Quem monta o pacote de implantação é que sabe
    # para qual filial ele vai.
    #
    # Nulo nos códigos criados antes desta coluna: eles continuam válidos e
    # caem na primeira planta ativa, como antes.
    planta_id: Mapped[int | None] = mapped_column(ForeignKey("plantas.id"), index=True)

    codigo_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # Valor em claro, para poder ser mostrado de novo na lista.
    # Nullable porque códigos criados antes desta coluna não o têm —
    # para eles a tela mostra só o prefixo.
    codigo_valor: Mapped[str | None] = mapped_column(String(32))
    # Prefixo legível ("A7K2-…") para o administrador identificar qual é qual
    # na lista sem precisar do valor completo.
    prefixo: Mapped[str] = mapped_column(String(16))

    rotulo: Mapped[str | None] = mapped_column(String(120))
    usos_max: Mapped[int] = mapped_column(Integer, default=1)
    usos_feitos: Mapped[int] = mapped_column(Integer, default=0)

    expira_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revogado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    criado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    criado_por: Mapped[object | None] = relationship("Usuario", foreign_keys=[criado_por_id])

    @property
    def esgotado(self) -> bool:
        # None antes do primeiro flush: default=0 vale no INSERT, não na
        # construção do objeto. Sem o or 0, comparar com >= estoura
        # TypeError e a tela quebra ao montar um código novo.
        return (self.usos_feitos or 0) >= (self.usos_max or 1)

    @property
    def util(self) -> bool:
        """Pode ser usado agora?

        Três condições: não revogado, não esgotado, não expirado. Ficam juntas
        aqui para que a regra exista num lugar só — o endpoint de registro e a
        tela precisam da mesma resposta.
        """
        if self.revogado_em is not None:
            return False
        if self.esgotado:
            return False
        if self.expira_em is None:
            return True
        # SQLite devolve datetime sem fuso; comparar com um com fuso estoura
        # TypeError. Normalizar para UTC cobre os dois bancos.
        expira = self.expira_em
        if expira.tzinfo is None:
            expira = expira.replace(tzinfo=timezone.utc)
        return expira > datetime.now(timezone.utc)


class TokenAgente(BaseModel, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    """Credencial de uma máquina registrada.

    O token em claro só existe duas vezes: na resposta do registro e no DPAPI
    da máquina. Aqui fica o hash.
    """

    __tablename__ = "tokens_agente"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    prefixo: Mapped[str] = mapped_column(String(16))

    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), index=True)
    ativo: Mapped[object | None] = relationship("Ativo", foreign_keys=[ativo_id])

    hostname: Mapped[str | None] = mapped_column(String(120))
    serial: Mapped[str | None] = mapped_column(String(120))

    ultimo_uso_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_ip: Mapped[str | None] = mapped_column(String(64))
    revogado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EquipamentoPendente(BaseModel, Base):
    id: Mapped[int] = mapped_column(primary_key=True)
    """Máquina que o agente encontrou e o servidor não reconheceu.

    ## Por que não criar direto

    Sem serial confiável — placa branca devolve `To be filled by O.E.M.` —,
    criar automaticamente faria quarenta máquinas distintas casarem com o
    mesmo identificador e virarem uma só.

    Aqui elas esperam decisão humana: qual MAC, hostname ou patrimônio é o
    identificador desta máquina.
    """

    __tablename__ = "equipamentos_pendentes"

    serial_bruto: Mapped[str | None] = mapped_column(String(120), index=True)
    hostname: Mapped[str | None] = mapped_column(String(120), index=True)
    mac: Mapped[str | None] = mapped_column(String(64), index=True)
    ip: Mapped[str | None] = mapped_column(String(64))

    # O payload inteiro, para o administrador ver o que é a máquina antes de
    # decidir. É dado de origem não confiável: guardado, nunca interpretado
    # sem validação.
    payload_json: Mapped[str] = mapped_column(Text, default="{}")

    # Por que entrou na fila — "sem_serial", "serial_nao_cadastrado",
    # "serial_invalido". A tela agrupa por isto.
    motivo: Mapped[str] = mapped_column(String(40), default="sem_serial", index=True)

    visto_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Última vez que a mesma máquina se apresentou sem ser resolvida. Serve
    # para ordenar por atividade e para não criar linha nova a cada coleta.
    ultima_vez_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolvido_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    ativo_criado_id: Mapped[int | None] = mapped_column(ForeignKey("ativos.id"))
