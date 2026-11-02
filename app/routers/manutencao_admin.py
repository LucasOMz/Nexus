"""Administração — modo manutenção e presença de usuários.

## O que a tela faz

* Mostra **quem está usando o sistema agora** — a partir de
  `Usuario.ultimo_acesso_em`, atualizado no máximo uma vez por minuto pelo
  `get_current_user`.
* Liga e desliga o **modo manutenção**, que bloqueia o login de quem não é
  administrador e derruba as sessões abertas na próxima requisição.
* **Derruba** as sessões de uma pessoa específica, carimbando
  `forcar_logout_em`.

## Por que "presença" e não "sessões"

O token é stateless: o servidor não mantém registro de quem está logado. Uma
lista de sessões de verdade exigiria `sid` no JWT — o que invalidaria todo
token existente e mudaria o caminho de autenticação de cada requisição.

Para operação, "quem usou nos últimos N minutos" responde a mesma pergunta.
O que se perde é derrubar **uma** sessão específica: aqui, derrubar derruba
todas as daquela pessoa — que é o comportamento certo para manutenção.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.database import get_db
from app.models.core import Usuario
from app.services import manutencao as servico

router = APIRouter(prefix="/admin/manutencao", tags=["manutencao"])

# Janela de presença. Cinco minutos cobre o intervalo de atualização da tela
# (15 s) com folga suficiente para ninguém "piscar" fora da lista entre duas
# leituras.
JANELA_PRESENCA_MIN = 5


class EstadoManutencao(BaseModel):
    ativa: bool
    mensagem: str | None = None
    desde: datetime | None = None
    por_nome: str | None = None


class AtivarEntrada(BaseModel):
    mensagem: str | None = Field(default=None, max_length=500)


class UsuarioPresente(BaseModel):
    id: int
    nome: str
    email: str
    papel: str
    planta_sigla: str | None = None
    ultimo_acesso_em: datetime | None = None
    minutos: int = 0
    eh_admin: bool = False


def _estado(db: Session) -> EstadoManutencao:
    cfg = servico.configuracao(db)
    autor = db.get(Usuario, cfg.manutencao_por_id) if cfg.manutencao_por_id else None
    return EstadoManutencao(
        ativa=bool(cfg.manutencao_ativa),
        mensagem=cfg.manutencao_mensagem,
        desde=cfg.manutencao_desde,
        por_nome=autor.nome if autor else None,
    )


@router.get("/status", response_model=EstadoManutencao)
def status(
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> EstadoManutencao:
    return _estado(db)


@router.post("/ativar", response_model=EstadoManutencao)
def ativar(
    entrada: AtivarEntrada | None = None,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> EstadoManutencao:
    """Liga o modo manutenção.

    Quem já está logado **não** é desconectado agora: cai na próxima
    requisição, quando o `get_current_user` devolve 503. É o que permite
    avisar a pessoa antes de derrubar.
    """
    servico.ligar(db, user.id, entrada.mensagem if entrada else None)
    from app.services.audit_service import audit

    audit(db, user, "manutencao_ativar", "configuracao", None)
    db.commit()
    return _estado(db)


@router.post("/desativar", response_model=EstadoManutencao)
def desativar(
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> EstadoManutencao:
    servico.desligar(db)
    from app.services.audit_service import audit

    audit(db, user, "manutencao_desativar", "configuracao", None)
    db.commit()
    return _estado(db)


@router.get("/usuarios", response_model=list[UsuarioPresente])
def usuarios(
    minutos: int = Query(default=JANELA_PRESENCA_MIN, ge=1, le=1440),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> list[UsuarioPresente]:
    """Quem acessou o sistema nos últimos N minutos.

    Inclui o próprio administrador — ele também usa o sistema, e escondê-lo
    faria a lista parecer incompleta.
    """
    agora = datetime.now(timezone.utc)
    corte = agora - timedelta(minutes=minutos)

    linhas = (
        db.query(Usuario)
        .filter(
            Usuario.deleted_at.is_(None),
            Usuario.ultimo_acesso_em.isnot(None),
            Usuario.ultimo_acesso_em >= corte,
        )
        .order_by(Usuario.ultimo_acesso_em.desc())
        .all()
    )

    saida: list[UsuarioPresente] = []
    for u in linhas:
        quando = u.ultimo_acesso_em
        # SQLite devolve datetime sem fuso; PostgreSQL com. Normalizar evita
        # TypeError na subtração.
        if quando is not None and quando.tzinfo is None:
            quando = quando.replace(tzinfo=timezone.utc)
        papel = getattr(u.papel, "value", u.papel)
        saida.append(
            UsuarioPresente(
                id=u.id,
                nome=u.nome,
                email=u.email,
                papel=papel,
                planta_sigla=getattr(getattr(u, "planta", None), "sigla", None),
                ultimo_acesso_em=quando,
                minutos=int((agora - quando).total_seconds() // 60) if quando else 0,
                eh_admin=papel == "admin",
            )
        )
    return saida


@router.post("/derrubar/{usuario_id}")
def derrubar(
    usuario_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> dict:
    """Encerra as sessões de um usuário.

    O carimbo em `forcar_logout_em` invalida todo token emitido antes dele.
    O usuário **pode entrar de novo** logo em seguida — o que é desejável: se
    ele estava no meio de uma tarefa, não fica trancado fora para sempre.

    Não é permitido derrubar a si mesmo: quem clicou perderia a própria
    sessão no meio da operação.
    """
    if usuario_id == user.id:
        raise HTTPException(400, "Use 'Sair' para encerrar a sua própria sessão.")

    alvo = db.get(Usuario, usuario_id)
    if alvo is None or alvo.deleted_at is not None:
        raise HTTPException(404, "Usuário não encontrado.")

    if getattr(alvo.papel, "value", alvo.papel) == "admin":
        raise HTTPException(
            403,
            "Não é possível derrubar outro administrador. Desative o acesso dele "
            "no cadastro de usuários.",
        )

    alvo.forcar_logout_em = datetime.now(timezone.utc)
    db.commit()

    from app.services.audit_service import audit

    audit(db, user, "manutencao_derrubar", "usuario", alvo.id)
    db.commit()

    return {"ok": True, "mensagem": f"Sessões de {alvo.nome} encerradas."}
