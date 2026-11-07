"""Usuários que já usaram cada ativo.

## O que é

O agente reporta `usuario_logado` a cada coleta. Isso alimenta:

* **`Ativo.ultimo_usuario`** — uma coluna denormalizada, para a lista de
  ativos mostrar direto, sem consulta por linha
* **`UsuarioDoAtivo`** — a lista de quem já logou naquela máquina

## Por que denormalizar o último usuário

A lista de ativos carrega centenas de linhas. Descobrir o último usuário de
cada uma exigiria uma subconsulta por ativo — ou um `JOIN` com `GROUP BY`,
que também custa. Uma coluna atualizada no envio resolve com zero consulta.

## Por que a lista, e não um log

Máquina compartilhada tem mais de uma pessoa. Saber **quem já usou** é útil;
um histórico completo de cada logon seria lixo — o `Movimentacao` já cobre o
que acontece com o equipamento.

Aqui é só uma lista corrente: um registro por pessoa, com a última vez que
apareceu. **Sem linha por evento.**

## Histórico, sem expiração

A lista guarda **todo mundo** que já se logou na máquina, com a data do
último acesso de cada um. Nada é removido por tempo.

O tamanho é limitado pelo número de pessoas que passam pelo equipamento,
não pelo prazo: um computador de balcão usado por trinta pessoas terá
trinta linhas — e é exatamente a informação que se quer.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BaseModel


class UsuarioDoAtivo(BaseModel, Base):
    __tablename__ = "usuarios_do_ativo"

    id: Mapped[int] = mapped_column(primary_key=True)

    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), index=True)

    # Como o Windows reporta: `DOMINIO\usuario` ou só `usuario`.
    nome: Mapped[str] = mapped_column(String(120), index=True)

    primeira_vez: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ultimo_login: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
