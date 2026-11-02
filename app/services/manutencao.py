"""Modo manutenção — estado e mensagem.

## O que é

Uma flag no banco que, ligada, faz duas coisas:

1. **Recusa o login** de quem não é administrador, com a mensagem escrita
   pelo administrador.
2. **Derruba as sessões abertas** na próxima requisição de cada usuário —
   via `get_current_user`, que devolve 503 em vez de 401.

O administrador continua entrando. É o ponto: alguém precisa poder desligar.

## Por que 503 e não 401

401 significa "credencial errada" e manda a pessoa para o login — onde ela
bate na mesma parede. 503 significa "indisponível, tente depois", e é o que
o frontend usa para mostrar a tela de manutenção com a mensagem certa.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.core import ConfiguracaoSistema

MENSAGEM_PADRAO = (
    "O sistema está em manutenção. Voltamos em breve."
)


def configuracao(db: Session) -> ConfiguracaoSistema:
    """A linha única de configuração, criada se ainda não existir."""
    cfg = db.query(ConfiguracaoSistema).first()
    if cfg is None:
        cfg = ConfiguracaoSistema()
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def esta_ativa(db: Session) -> bool:
    return bool(configuracao(db).manutencao_ativa)


def mensagem(db: Session) -> str:
    cfg = configuracao(db)
    return (cfg.manutencao_mensagem or "").strip() or MENSAGEM_PADRAO


def ligar(db: Session, usuario_id: int | None, texto: str | None = None) -> ConfiguracaoSistema:
    cfg = configuracao(db)
    cfg.manutencao_ativa = True
    cfg.manutencao_mensagem = (texto or "").strip() or MENSAGEM_PADRAO
    cfg.manutencao_desde = datetime.now(timezone.utc)
    cfg.manutencao_por_id = usuario_id
    db.commit()
    db.refresh(cfg)
    return cfg


def desligar(db: Session) -> ConfiguracaoSistema:
    cfg = configuracao(db)
    cfg.manutencao_ativa = False
    cfg.manutencao_desde = None
    cfg.manutencao_por_id = None
    db.commit()
    db.refresh(cfg)
    return cfg
