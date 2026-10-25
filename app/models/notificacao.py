"""Notificações por e-mail — configuração, preferências e histórico.

## A separação em três tabelas

| Tabela | Quem manda |
|---|---|
| `config_smtp` | o **administrador** — uma configuração para todo o sistema |
| `templates_notificacao` | o **administrador** — o texto de cada aviso |
| `preferencias_notificacao` | **cada técnico** — o que quer receber e quando |

## Por que o texto é do administrador, e não de cada usuário

O aviso de "devolução atrasada" é comunicação da **empresa** com o técnico.
Se cada um escrevesse o seu, o tom e a informação variariam sem controle, e
não haveria como corrigir uma orientação errada que já foi enviada a trinta
pessoas.

O que o técnico decide é **o que receber e com que frequência** — e isso é o
que resolve o problema real dele (caixa de entrada cheia).

## Por que há histórico, e não só envio

Três motivos práticos:

1. **Não repetir** o mesmo aviso a cada ciclo do agendador (tonel é um estado
   contínuo — sem isto, seriam e-mails a cada hora)
2. **Provar** o que foi enviado, para quem e quando
3. **Diagnosticar** falha de SMTP sem acesso ao log do servidor
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _agora() -> datetime:
    return datetime.now(timezone.utc)


class ConfiguracaoSMTP(Base):
    """A conta de envio do sistema.

    Linha única (`id = 1`). Não é por planta de propósito: o servidor de
    e-mail é da empresa, e multiplicar a configuração por unidade só criaria
    divergência — um dia uma planta envia e outra não, e ninguém sabe por quê.
    """

    __tablename__ = "config_smtp"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    ativo: Mapped[bool] = mapped_column(Boolean, default=False)

    host: Mapped[str | None] = mapped_column(String(200))
    porta: Mapped[int] = mapped_column(Integer, default=587)
    # "tls" (STARTTLS, porta 587) · "ssl" (porta 465) · "nenhuma" (porta 25)
    seguranca: Mapped[str] = mapped_column(String(12), default="tls")

    usuario: Mapped[str | None] = mapped_column(String(200))

    # A senha é segredo: cifrada em repouso, com a mesma chave mestra das
    # licenças. Ficar em claro no banco faria o backup do banco ser também o
    # backup da credencial de e-mail da empresa.
    senha_cifrada: Mapped[bytes | None] = mapped_column(LargeBinary)
    senha_versao: Mapped[int | None] = mapped_column(Integer)

    remetente_email: Mapped[str | None] = mapped_column(String(200))
    remetente_nome: Mapped[str] = mapped_column(String(120), default="Nexus")
    responder_para: Mapped[str | None] = mapped_column(String(200))

    # Prefixo que entra em todo assunto — ajuda a criar regra na caixa de
    # entrada ("se começa com [Nexus], move para Notificações").
    assunto_prefixo: Mapped[str] = mapped_column(String(40), default="[Nexus]")

    # Janela em que os e-mails comuns podem sair. Aviso urgente passa por
    # cima — ver `despachar` em `notificacoes_email`.
    hora_inicio: Mapped[int] = mapped_column(Integer, default=7)
    hora_fim: Mapped[int] = mapped_column(Integer, default=19)

    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora)
    atualizado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL")
    )


class TemplateNotificacao(Base):
    """O texto de cada aviso, editável pelo administrador.

    ## Variáveis

    O corpo aceita `{{variavel}}`. A lista do que existe por aviso vem de
    `notificacoes_email.CATALOGO` — a mesma que a tela mostra, para não haver
    um conjunto documentado e outro real.

    ## Por que não há template obrigatório

    Sem linha nesta tabela, o aviso usa o texto padrão do catálogo. Isso
    permite acrescentar um aviso novo ao sistema sem exigir que alguém o
    configure antes de ele funcionar.
    """

    __tablename__ = "templates_notificacao"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chave: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    assunto: Mapped[str | None] = mapped_column(String(300))
    corpo: Mapped[str | None] = mapped_column(Text)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora)
    atualizado_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL")
    )


class PreferenciaNotificacao(Base):
    """O que cada técnico quer receber, e quando.

    ## Por que a frequência é por aviso, e não global

    Os avisos têm naturezas diferentes: "devolução atrasada" precisa chegar no
    dia; "toner abaixo de 10%" pode ser um resumo diário; "contrato vencendo"
    cabe semanalmente. Uma frequência única obrigaria a escolher entre
    spam e cegueira.
    """

    __tablename__ = "preferencias_notificacao"
    __table_args__ = (
        UniqueConstraint("usuario_id", "chave", name="uq_preferencia_usuario_chave"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), index=True
    )
    chave: Mapped[str] = mapped_column(String(60), index=True)

    ativo: Mapped[bool] = mapped_column(Boolean, default=True)

    # imediata · diaria · semanal · desligada
    frequencia: Mapped[str] = mapped_column(String(12), default="diaria")

    # Hora local (0–23) em que o resumo sai, para as frequências agrupadas.
    # "Imediata" ignora este campo.
    hora: Mapped[int] = mapped_column(Integer, default=8)

    # Dias da semana para "semanal": "1,3,5" (ISO, segunda = 1).
    dias_semana: Mapped[str | None] = mapped_column(String(20))

    atualizado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_agora)


class EmailEnviado(Base):
    """Histórico de envios — e a memória que evita repetir.

    ## A chave de não-repetição

    `(usuario_id, chave, referencia)` identifica um aviso concreto: "o
    empréstimo #42 atrasado para a Ana". Consultada antes de enviar, ela
    impede o mesmo aviso a cada ciclo.

    `referencia` é o identificador do objeto dentro do tipo — o id do
    empréstimo, o id do ativo. Sem ela, só haveria "já avisei sobre atraso",
    e a Ana nunca saberia do **segundo** empréstimo atrasado.
    """

    __tablename__ = "emails_enviados"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), index=True
    )
    chave: Mapped[str] = mapped_column(String(60), index=True)
    referencia: Mapped[str | None] = mapped_column(String(80), index=True)

    destinatario: Mapped[str] = mapped_column(String(200))
    assunto: Mapped[str] = mapped_column(String(300))
    resumo: Mapped[str | None] = mapped_column(Text)

    enviado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_agora, index=True
    )

    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    erro: Mapped[str | None] = mapped_column(Text)
