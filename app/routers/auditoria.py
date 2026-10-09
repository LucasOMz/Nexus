"""Auditoria — consulta do histórico (somente administrador).

A tabela `logs_auditoria` é **append-only**: o sistema só grava, nunca altera
nem apaga. Esta tela apenas lê. Cada registro guarda quem fez, o que fez,
quando, de qual IP e o que mudou (diff).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import ConfigDict
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.database import get_db
from app.models.core import Ativo, LogAuditoria, Usuario
from app.schemas.datas import DatasComFuso

router = APIRouter(prefix="/admin/auditoria", tags=["auditoria"])

# Nome amigável de cada ação registrada.
ROTULO_ACAO = {
    "create": "Criou",
    "update": "Alterou",
    "delete": "Excluiu",
    "delete_lote": "Excluiu em lote",
    "login": "Entrou no sistema",
    "scan": "Leu código",
    "qrcode": "Gerou QR Code",
    "qrcode_batch": "Gerou QR Codes (lote)",
    "gerar_zerados": "Gerou etiquetas em branco",
    "imprimir_zerados": "Imprimiu etiquetas em branco",
    "print": "Imprimiu etiqueta",
    "print_batch": "Imprimiu etiquetas (lote)",
    "print_teste": "Imprimiu teste",
    "status": "Mudou status",
    "atribuir": "Atribuiu ativo",
    "leitura_contador": "Lançou contador",
    "backup": "Gerou backup",
    "restaurar_backup": "Restaurou backup",
    "importar_csv": "Importou CSV",
    "provisionar": "Criou usuário (AD)",
    "testar_ldap": "Testou LDAP",
    "testar_login_ldap": "Testou login LDAP",
}

ROTULO_ENTIDADE = {
    "ativo": "Ativo",
    "ativos": "Ativos",
    "usuario": "Usuário",
    "qr_zerado": "Etiqueta em branco",
    "dispositivo_impressao": "Dispositivo de impressão",
    "template_etiqueta": "Template de etiqueta",
    "configuracao": "Configuração",
    "sistema": "Sistema",
    "suprimento": "Suprimento",
    "produto": "Produto",
    "movimentacao": "Movimentação",
    "manutencao": "Manutenção",
}


class LogOut(DatasComFuso):
    model_config = ConfigDict(from_attributes=True)

    id: int
    criado_em: datetime
    usuario_id: int | None = None
    usuario_nome: str | None = None
    usuario_email: str | None = None
    acao: str
    acao_rotulo: str
    entidade: str
    entidade_rotulo: str
    entidade_id: int | None = None
    referencia: str | None = None
    ip: str | None = None
    diff: dict[str, Any] | None = None


def _referencia(db: Session, entidade: str, entidade_id: int | None) -> str | None:
    """Patrimônio/nome legível do alvo, para a lista não mostrar só o id."""
    if entidade_id is None:
        return None
    if entidade in ("ativo", "ativos"):
        ativo = db.get(Ativo, entidade_id)
        return ativo.patrimonio if ativo is not None else None
    return None


@router.get("")
def listar(
    usuario_id: int | None = None,
    acao: str | None = None,
    entidade: str | None = None,
    entidade_id: int | None = None,
    busca: str | None = Query(default=None, description="Procura no IP, no diff e no nome do usuário"),
    inicio: datetime | None = None,
    fim: datetime | None = None,
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
) -> dict:
    """Lista o histórico de auditoria, do mais recente para o mais antigo."""
    consulta = db.query(LogAuditoria).outerjoin(Usuario, Usuario.id == LogAuditoria.usuario_id)

    if usuario_id is not None:
        consulta = consulta.filter(LogAuditoria.usuario_id == usuario_id)
    if acao:
        consulta = consulta.filter(LogAuditoria.acao == acao)
    if entidade:
        consulta = consulta.filter(LogAuditoria.entidade == entidade)
    if entidade_id is not None:
        consulta = consulta.filter(LogAuditoria.entidade_id == entidade_id)
    if inicio is not None:
        consulta = consulta.filter(LogAuditoria.created_at >= inicio)
    if fim is not None:
        consulta = consulta.filter(LogAuditoria.created_at <= fim)
    if busca:
        alvo = f"%{busca.strip()}%"
        consulta = consulta.filter(
            or_(
                LogAuditoria.ip.ilike(alvo),
                cast(LogAuditoria.diff, String).ilike(alvo),
                Usuario.nome.ilike(alvo),
                Usuario.email.ilike(alvo),
            )
        )

    total = consulta.count()
    linhas = (
        consulta.order_by(LogAuditoria.id.desc())
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
        .all()
    )

    usuarios = {u.id: u for u in db.query(Usuario).all()}
    itens = []
    for log in linhas:
        dono = usuarios.get(log.usuario_id) if log.usuario_id else None
        itens.append(
            LogOut(
                id=log.id,
                criado_em=log.created_at,
                usuario_id=log.usuario_id,
                usuario_nome=dono.nome if dono else ("(sistema)" if log.usuario_id is None else "(usuário removido)"),
                usuario_email=dono.email if dono else None,
                acao=log.acao,
                acao_rotulo=ROTULO_ACAO.get(log.acao, log.acao),
                entidade=log.entidade,
                entidade_rotulo=ROTULO_ENTIDADE.get(log.entidade, log.entidade),
                entidade_id=log.entidade_id,
                referencia=_referencia(db, log.entidade, log.entidade_id),
                ip=log.ip,
                diff=log.diff,
            )
        )

    return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "itens": itens}


@router.get("/filtros")
def opcoes_de_filtro(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)) -> dict:
    """Ações e usuários que aparecem no histórico, para montar os filtros."""
    acoes = [a for (a,) in db.query(LogAuditoria.acao).distinct().order_by(LogAuditoria.acao).all()]
    entidades = [e for (e,) in db.query(LogAuditoria.entidade).distinct().order_by(LogAuditoria.entidade).all()]
    usuarios = [
        {"id": u.id, "nome": u.nome, "email": u.email}
        for u in db.query(Usuario).order_by(Usuario.nome).all()
    ]
    return {
        "acoes": [{"valor": a, "rotulo": ROTULO_ACAO.get(a, a)} for a in acoes],
        "entidades": [{"valor": e, "rotulo": ROTULO_ENTIDADE.get(e, e)} for e in entidades],
        "usuarios": usuarios,
    }


@router.get("/resumo")
def resumo(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)) -> dict:
    """Números do topo da tela: total de registros e atividade recente."""
    total = db.query(LogAuditoria).count()
    ultimos = db.query(LogAuditoria).order_by(LogAuditoria.id.desc()).first()
    desde = datetime.now(timezone.utc) - timedelta(days=7)
    recentes = db.query(LogAuditoria).filter(LogAuditoria.created_at >= desde).count()
    return {
        "total": total,
        "ultimos_7_dias": recentes,
        "ultimo_em": ultimos.created_at.isoformat() if ultimos else None,
    }
