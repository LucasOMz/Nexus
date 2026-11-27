"""Persistência, rotação e revogação das sessões da API."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.core import ConfiguracaoSistema, Usuario
from app.models.sessao import SessaoUsuario

INATIVIDADE_PADRAO_MINUTOS = 10


def inatividade_minutos(db: Session) -> int:
    if "inatividade_minutos" not in db.info:
        db.info["inatividade_minutos"] = db.scalar(
            select(ConfiguracaoSistema.sessao_inatividade_minutos).where(ConfiguracaoSistema.id == 1)
        ) or INATIVIDADE_PADRAO_MINUTOS
    return db.info["inatividade_minutos"]


def _hash(credencial: str) -> str:
    return sha256(credencial.encode("utf-8")).hexdigest()


def registrar(db: Session, sid: str, usuario_id: int, ttl: timedelta, refresh: str | None = None) -> None:
    agora = datetime.now(timezone.utc)
    db.execute(delete(SessaoUsuario).where(SessaoUsuario.expira_em <= agora))
    db.add(SessaoUsuario(
        id=sid, usuario_id=usuario_id, expira_em=agora + ttl,
        refresh_hash=_hash(refresh) if refresh is not None else None,
        ultima_atividade_em=agora if refresh is not None else None,
    ))


def _filtro_ativo(sid: str, usuario_id: int, agora: datetime) -> tuple:
    return (
        SessaoUsuario.id == sid,
        SessaoUsuario.usuario_id == usuario_id,
        SessaoUsuario.revogada_em.is_(None),
        SessaoUsuario.expira_em > agora,
    )


def ativa(db: Session, sid: str, usuario_id: int, *, setup: bool) -> bool:
    agora = datetime.now(timezone.utc)
    q = select(SessaoUsuario.id).where(
        *_filtro_ativo(sid, usuario_id, agora),
        SessaoUsuario.refresh_hash.is_(None) if setup else _atividade_recente(db, agora),
    )
    return db.scalar(q) is not None


def _atividade_recente(db: Session, agora: datetime):
    return (
        SessaoUsuario.refresh_hash.is_not(None)
        & (SessaoUsuario.ultima_atividade_em > agora - timedelta(minutes=inatividade_minutos(db)))
    )


def registrar_atividade(db: Session, sid: str, usuario_id: int, atraso_ms: int) -> bool:
    agora = datetime.now(timezone.utc)
    momento = agora - timedelta(milliseconds=atraso_ms)
    # Uma aba com um evento mais antigo não pode reduzir o prazo de outra.
    q = update(SessaoUsuario).where(
        *_filtro_ativo(sid, usuario_id, agora),
        _atividade_recente(db, agora),
        SessaoUsuario.ultima_atividade_em < momento,
    ).values(ultima_atividade_em=momento)
    return db.execute(q).rowcount == 1 or ativa(db, sid, usuario_id, setup=False)


def renovar(db: Session, sid: str, usuario_id: int, anterior: str, novo: str, ttl: timedelta) -> bool:
    agora = datetime.now(timezone.utc)
    q = update(SessaoUsuario).where(
        *_filtro_ativo(sid, usuario_id, agora), SessaoUsuario.refresh_hash == _hash(anterior),
        _atividade_recente(db, agora),
    ).values(refresh_hash=_hash(novo), expira_em=agora + ttl)
    return db.execute(q).rowcount == 1


def revogar(db: Session, sid: str, usuario_id: int) -> None:
    agora = datetime.now(timezone.utc)
    db.execute(
        update(SessaoUsuario).where(*_filtro_ativo(sid, usuario_id, agora)).values(revogada_em=agora)
    )


def revogar_do_usuario(db: Session, usuario: Usuario) -> None:
    agora = datetime.now(timezone.utc)
    usuario.forcar_logout_em = agora
    db.execute(update(SessaoUsuario).where(
        SessaoUsuario.usuario_id == usuario.id, SessaoUsuario.revogada_em.is_(None),
    ).values(revogada_em=agora))


def revogar_inativas(db: Session, minutos: int) -> None:
    agora = datetime.now(timezone.utc)
    db.execute(update(SessaoUsuario).where(
        SessaoUsuario.revogada_em.is_(None),
        SessaoUsuario.expira_em > agora,
        SessaoUsuario.ultima_atividade_em <= agora - timedelta(minutes=minutos),
    ).values(revogada_em=agora))


def limpar_em_banco_restaurado(bind) -> None:
    # Backups antigos podem anteceder a tabela. Sessões nunca são restauradas.
    SessaoUsuario.__table__.create(bind=bind, checkfirst=True)
    with bind.begin() as conn:
        conn.execute(delete(SessaoUsuario))
