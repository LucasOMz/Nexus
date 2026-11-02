"""Histórico de alterações de hardware.

## Por que só quando muda

O agente coleta duas vezes por dia. Gravar uma linha a cada coleta seriam
3.000 × 2 × 365 = **2 milhões de linhas por ano**, quase todas idênticas.

Aqui só entra o que **mudou**. Coleta sem mudança atualiza apenas
`inventario_em` no ativo — e a tela mostra "última coleta" em vez de poluir
o histórico.

## O diff, não a foto

`mudancas_json` guarda só os campos alterados, com valor antigo e novo.
Guardar o payload inteiro a cada mudança encheria o banco sem responder a
pergunta que importa: *"o que mudou nesta máquina"*.

## Campos voláteis ficam de fora do hash

`uptime`, `ip` e `usuario_logado` mudam a cada coleta. Se entrassem no hash,
**toda** coleta pareceria mudança e o histórico viraria um log inútil.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, BaseModel


class HistoricoInventario(BaseModel, Base):
    __tablename__ = "historico_inventario"

    id: Mapped[int] = mapped_column(primary_key=True)

    ativo_id: Mapped[int] = mapped_column(ForeignKey("ativos.id"), index=True)

    quando: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    # Hash dos campos ESTÁVEIS — é o que decide se houve mudança.
    hash: Mapped[str] = mapped_column(String(64))

    # Os campos estáveis desta coleta, para calcular o diff da próxima.
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")

    # {"cpu": {"de": "...", "para": "..."}, ...}
    mudancas_json: Mapped[str] = mapped_column(Text, default="{}")

    # Origem: "agente", "manual", "importacao".
    origem: Mapped[str] = mapped_column(String(20), default="agente")
