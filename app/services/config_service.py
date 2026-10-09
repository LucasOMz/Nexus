"""Acesso à configuração global do sistema (linha única em `configuracoes`)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.core import ConfiguracaoSistema
from app.models.ocs import ConfiguracaoOCS


def obter_config(db: Session) -> ConfiguracaoSistema:
    """Retorna a configuração global, criando a linha padrão se não existir."""
    cfg = db.get(ConfiguracaoSistema, 1)
    if cfg is None:
        cfg = ConfiguracaoSistema(id=1)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def obter_config_ocs(db: Session) -> ConfiguracaoOCS:
    """Configuração da integração com o OCS (cria a linha padrão se faltar)."""
    cfg = db.get(ConfiguracaoOCS, 1)
    if cfg is None:
        cfg = ConfiguracaoOCS(id=1)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)

    # Migração pontual: a primeira versão guardava o intervalo em HORAS. Se o
    # valor antigo existe e o novo ainda está no padrão, converte uma vez só.
    #
    # Zera o campo antigo em vez de anulá-lo: a coluna foi criada como NOT NULL
    # e gravar NULL ali quebraria a leitura da configuração.
    horas = getattr(cfg, "sync_intervalo_horas", None)
    if horas and cfg.sync_intervalo_minutos == 60:
        cfg.sync_intervalo_minutos = max(5, int(horas) * 60)
        cfg.sync_intervalo_horas = 0
        db.commit()
        db.refresh(cfg)
    return cfg


def obter_template_padrao(db: Session):
    """Template de etiqueta padrão (o marcado como `padrao`, senão o primeiro)."""
    from app.models.core import TemplateEtiqueta

    q = db.query(TemplateEtiqueta).filter(TemplateEtiqueta.deleted_at.is_(None))
    return q.filter(TemplateEtiqueta.padrao.is_(True)).first() or q.order_by(TemplateEtiqueta.id).first()
