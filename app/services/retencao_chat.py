"""Prazo e limpeza do histórico do assistente."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.chat_ia import ChatInventarioMensagem
from app.models.core import ConfiguracaoSistema


def limite_historico(dias: int | None) -> datetime | None:
    return datetime.now(timezone.utc) - timedelta(days=dias) if dias is not None else None


def limpar_expirados(db: Session, dias: int | None) -> int:
    limite = limite_historico(dias)
    if limite is None:
        return 0
    resultado = db.execute(delete(ChatInventarioMensagem).where(ChatInventarioMensagem.created_at < limite))
    return resultado.rowcount


def executar_retencao(db: Session) -> int:
    dias = db.scalar(select(ConfiguracaoSistema.ollama_historico_dias)
                     .where(ConfiguracaoSistema.id == 1).with_for_update())
    removidos = limpar_expirados(db, dias)
    db.commit()
    return removidos
