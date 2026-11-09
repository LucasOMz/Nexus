"""Acesso à configuração global do sistema (linha única em `configuracoes`)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.core import ConfiguracaoSistema


def obter_config(db: Session) -> ConfiguracaoSistema:
    """Retorna a configuração global, criando a linha padrão se não existir."""
    cfg = db.get(ConfiguracaoSistema, 1)
    if cfg is None:
        cfg = ConfiguracaoSistema(id=1)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def obter_template_padrao(db: Session):
    """Template de etiqueta padrão (o marcado como `padrao`, senão o primeiro)."""
    from app.models.core import TemplateEtiqueta

    q = db.query(TemplateEtiqueta).filter(TemplateEtiqueta.deleted_at.is_(None))
    return q.filter(TemplateEtiqueta.padrao.is_(True)).first() or q.order_by(TemplateEtiqueta.id).first()
