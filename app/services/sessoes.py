"""Persistência, rotação e revogação das sessões da API."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models.core import Usuario
from app.models.sessao import SessaoUsuario


def _hash(credencial: str) -> str:
    return sha256(credencial.encode("utf-8")).hexdigest()


def registrar(db: Session, sid: str, usuario_id: int, ttl: timedelta, refresh: str | None = None) -> None:
    agora = datetime.now(timezone.utc)
    db.execute(delete(SessaoUsuario).where(SessaoUsuario.expira_em <= agora))
    db.add(SessaoUsuario(
        id=sid, usuario_id=usuario_id, expira_em=agora + ttl,
        refresh_hash=_hash(refresh) if refresh is not None else None,
    ))


def _filtro_ativo(sid: str, usuario_id: int, agora: datetime) -> tuple:
    return (
        SessaoUsuario.id == sid,
        SessaoUsuario.usuario_id == usuario_id,
        SessaoUsuario.revogada_em.is_(None),
        SessaoUsuario.expira_em > agora,
    )


def ativa(db: Session, sid: str, usuario_id: int, *, setup: bool) -> bool:
    q = select(SessaoUsuario.id).where(
        *_filtro_ativo(sid, usuario_id, datetime.now(timezone.utc)),
        SessaoUsuario.refresh_hash.is_(None) if setup else SessaoUsuario.refresh_hash.is_not(None),
    )
    return db.scalar(q) is not None


def renovar(db: Session, sid: str, usuario_id: int, anterior: str, novo: str, ttl: timedelta) -> bool:
    agora = datetime.now(timezone.utc)
    q = update(SessaoUsuario).where(
        *_filtro_ativo(sid, usuario_id, agora), SessaoUsuario.refresh_hash == _hash(anterior),
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


def limpar_em_banco_restaurado(bind) -> None:
    # Backups antigos podem anteceder a tabela. Sessões nunca são restauradas.
    SessaoUsuario.__table__.create(bind=bind, checkfirst=True)
    with bind.begin() as conn:
        conn.execute(delete(SessaoUsuario))
