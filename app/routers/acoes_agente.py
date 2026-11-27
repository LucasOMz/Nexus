"""Ações fixas do Agente Nexus e seu histórico por equipamento."""
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, exists, false, func, insert, or_, select, update
from sqlalchemy.orm import Session

from app.core.deps import require_module
from app.core.permissoes import eh_admin, permissoes_efetivas, pode_inventario, pode_modulo
from app.core.planta import planta_ativa_obrigatoria
from app.database import get_db
from app.models.agente import AcaoAgente, ColetaAgenteLote, TokenAgente
from app.models.core import Ativo, Usuario
from app.models.enums import Dominio
from app.services.agente_service import buscar_token
from app.services.audit_service import audit

router = APIRouter(tags=["ações do agente"])
TipoAcao = Literal["coletar", "testar_comunicacao", "status_servico"]
ResultadoAcao = Literal["coleta_enviada", "falha_coleta", "comunicacao_ok", "servico_em_execucao", "falha_status"]
RESULTADOS = {
    "coletar": {"coleta_enviada", "falha_coleta"},
    "testar_comunicacao": {"comunicacao_ok"},
    "status_servico": {"servico_em_execucao", "falha_status"},
}
PRAZO_FILA = timedelta(hours=24)
PRAZO_RESULTADO = timedelta(minutes=5)
ITENS_HISTORICO = 30
COLETAS_POR_MINUTO = 50
INTERVALO_LOTE = timedelta(minutes=1) / COLETAS_POR_MINUTO
_TRAVA_AGENDA_COLETA = 1730186101
_TRAVA_ENTREGA_LOTE = 1730186102


class Solicitacao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tipo: TipoAcao


class Resultado(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int = Field(gt=0)
    resultado: ResultadoAcao


def _utc(valor: datetime | None) -> datetime | None:
    return valor.replace(tzinfo=timezone.utc) if valor and valor.tzinfo is None else valor


def _pode_usar(user: Usuario) -> bool:
    return (pode_modulo(user, "ativos") and pode_inventario(user, "ti")
            and permissoes_efetivas(user)["pode_acoes_agente"])


def _travar_lote(db: Session, chave: int) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(chave)))
    else:
        # SQLite adquire a trava de escrita mesmo sem uma linha correspondente.
        db.execute(update(ColetaAgenteLote).where(false()).values(total=ColetaAgenteLote.total))


def _horario_disponivel(db: Session) -> datetime | None:
    ultima_entrega = select(AcaoAgente.lote_entregue_em).where(
        AcaoAgente.lote_entregue_em.is_not(None),
    ).order_by(AcaoAgente.lote_entregue_em.desc()).limit(1)
    if db.get_bind().dialect.name == "postgresql":
        agora, ultima = db.execute(select(func.clock_timestamp(), ultima_entrega.scalar_subquery())).one()
    else:
        agora, ultima = datetime.now(timezone.utc), db.scalar(ultima_entrega)
    if ultima is not None and agora - _utc(ultima) < INTERVALO_LOTE:
        return None
    return agora


def _horario_entrega_lote(db: Session) -> datetime | None:
    if _horario_disponivel(db) is None:
        return None
    _travar_lote(db, _TRAVA_ENTREGA_LOTE)
    return _horario_disponivel(db)


def _ativo_autorizado(db: Session, user: Usuario, ativo_id: int, planta_id: int | None) -> Ativo:
    if not _pode_usar(user):
        raise HTTPException(403, "Seu usuário não tem permissão para ações remotas.")
    ativo = db.get(Ativo, ativo_id)
    if (ativo is None or ativo.deleted_at is not None or ativo.dominio != Dominio.TI
            or (planta_id is not None and ativo.planta_id != planta_id)):
        raise HTTPException(404, "Computador não encontrado.")
    return ativo


def _token_da_maquina(db: Session, request: Request) -> TokenAgente:
    esquema, _, segredo = request.headers.get("Authorization", "").partition(" ")
    if esquema.lower() != "bearer" or not segredo.strip():
        raise HTTPException(401, "token_ausente")
    token = buscar_token(db, segredo.strip())
    if token is None:
        raise HTTPException(401, "token_invalido")
    ativo = db.get(Ativo, token.ativo_id)
    if ativo is None or ativo.deleted_at is not None or ativo.dominio != Dominio.TI:
        raise HTTPException(404, "Computador não encontrado.")
    return token


def _token_vinculado(ativo_id: int):
    return (select(TokenAgente).where(TokenAgente.ativo_id == ativo_id, TokenAgente.deleted_at.is_(None),
            TokenAgente.revogado_em.is_(None)).order_by(TokenAgente.id.desc()).limit(1))


def _historico(item: AcaoAgente, agora: datetime, revogado_em: datetime | None = None) -> dict:
    estado = item.estado
    encerrada = _utc(item.encerrada_em)
    resultado = item.resultado
    if estado in ("aguardando", "entregue"):
        vencimento = _utc(item.expira_em)
        revogado = _utc(revogado_em)
        if revogado is not None and revogado < vencimento:
            estado, encerrada, resultado = "cancelada", revogado, "acesso_ou_vinculo_alterado"
        elif vencimento <= agora:
            estado, encerrada = "expirada", vencimento
    return {
        "id": item.id, "tipo": item.tipo, "estado": estado, "solicitante": item.solicitante_nome,
        "solicitada_em": _utc(item.solicitada_em), "encerrada_em": encerrada, "resultado": resultado,
    }


@router.get("/ativos/{ativo_id}/acoes-agente")
def painel(ativo_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_module("ativos")),
           planta_id: int | None = Depends(planta_ativa_obrigatoria),
           antes_de: int | None = Query(default=None, gt=0)) -> dict:
    ativo = _ativo_autorizado(db, user, ativo_id, planta_id)
    token = db.scalar(_token_vinculado(ativo.id))
    agora = datetime.now(timezone.utc)
    consulta = select(AcaoAgente, TokenAgente.revogado_em).join(TokenAgente, TokenAgente.id == AcaoAgente.token_id).where(
        AcaoAgente.ativo_id == ativo.id, AcaoAgente.planta_id == ativo.planta_id,
    )
    if antes_de is not None:
        consulta = consulta.where(AcaoAgente.id < antes_de)
    itens = db.execute(consulta.order_by(AcaoAgente.id.desc()).limit(ITENS_HISTORICO + 1)).all()
    proximo = itens[ITENS_HISTORICO - 1][0].id if len(itens) > ITENS_HISTORICO else None
    contatos = [_utc(data) for data in (token.ultimo_uso_em, token.ultimo_contato_acoes_em) if data] if token else []
    return {
        "vinculado": token is not None,
        "ultimo_contato": max(contatos, default=None),
        "recebe_acoes": bool(token and token.ultimo_contato_acoes_em),
        "historico": [_historico(item, agora, revogado_em) for item, revogado_em in itens[:ITENS_HISTORICO]],
        "proximo": proximo,
    }


@router.post("/ativos/{ativo_id}/acoes-agente", status_code=201)
def solicitar(ativo_id: int, body: Solicitacao, request: Request, db: Session = Depends(get_db),
              user: Usuario = Depends(require_module("ativos")),
              planta_id: int | None = Depends(planta_ativa_obrigatoria)) -> dict:
    ativo = _ativo_autorizado(db, user, ativo_id, planta_id)
    if body.tipo == "coletar":
        _travar_lote(db, _TRAVA_AGENDA_COLETA)
    token = db.scalar(_token_vinculado(ativo.id).with_for_update(of=TokenAgente))
    if token is None:
        raise HTTPException(409, "Este computador não tem um agente vinculado.")
    agora = datetime.now(timezone.utc)
    existente = db.scalar(select(AcaoAgente.id).where(
        AcaoAgente.token_id == token.id, AcaoAgente.tipo == body.tipo, AcaoAgente.planta_id == ativo.planta_id,
        AcaoAgente.estado.in_(("aguardando", "entregue")), AcaoAgente.expira_em > agora,
    ).limit(1))
    if existente is not None:
        raise HTTPException(409, "Já há uma solicitação deste tipo em andamento.")
    item = AcaoAgente(token_id=token.id, ativo_id=ativo.id, planta_id=ativo.planta_id,
                      solicitante_id=user.id, solicitante_nome=user.nome, tipo=body.tipo,
                      estado="aguardando", solicitada_em=agora, expira_em=agora + PRAZO_FILA)
    db.add(item)
    db.flush()
    audit(db, user, "solicitar_acao_agente", "ativo", ativo.id, ip=request.client.host if request.client else None,
          diff={"solicitacao_id": item.id, "tipo": body.tipo})
    resposta = _historico(item, agora)
    db.commit()
    return resposta


def _escopo_lotes(consulta, planta_id):
    if planta_id is not None:
        return consulta.where(ColetaAgenteLote.planta_id == planta_id)
    return consulta


def _exigir_acesso_lotes(user: Usuario) -> None:
    if not _pode_usar(user):
        raise HTTPException(403, "Seu usuário não tem permissão para ações remotas.")


def _dados_lote(lote: ColetaAgenteLote) -> dict:
    return {
        "id": lote.id, "solicitante": lote.solicitante_nome, "solicitada_em": _utc(lote.solicitada_em),
        "total": lote.total, "sem_agente": lote.sem_agente, "ja_solicitados": lote.ja_solicitados,
    }


def _vinculo_lote_alterado():
    return or_(
        TokenAgente.revogado_em.is_not(None) & (TokenAgente.revogado_em < AcaoAgente.expira_em),
        TokenAgente.deleted_at.is_not(None), Ativo.deleted_at.is_not(None), Ativo.dominio != Dominio.TI,
        Ativo.planta_id.is_distinct_from(AcaoAgente.planta_id), TokenAgente.ativo_id != AcaoAgente.ativo_id,
    )


@router.get("/acoes-agente/lotes")
def listar_lotes(db: Session = Depends(get_db), user: Usuario = Depends(require_module("ativos")),
                 planta_id: int | None = Depends(planta_ativa_obrigatoria)) -> dict:
    _exigir_acesso_lotes(user)
    consulta = _escopo_lotes(select(ColetaAgenteLote), planta_id)
    lotes = db.scalars(consulta.order_by(ColetaAgenteLote.id.desc()).limit(20))
    return {"lotes": [_dados_lote(lote) for lote in lotes], "coletas_por_minuto": COLETAS_POR_MINUTO,
            "planta_id": planta_id}


@router.post("/acoes-agente/lotes", status_code=201)
def solicitar_lote(request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_module("ativos")),
                    planta_id: int | None = Depends(planta_ativa_obrigatoria)) -> dict:
    _exigir_acesso_lotes(user)
    _travar_lote(db, _TRAVA_AGENDA_COLETA)
    agora = datetime.now(timezone.utc)
    lote_pendente = (select(AcaoAgente.id)
                     .join(ColetaAgenteLote, ColetaAgenteLote.id == AcaoAgente.lote_id)
                     .join(TokenAgente, TokenAgente.id == AcaoAgente.token_id)
                     .join(Ativo, Ativo.id == AcaoAgente.ativo_id)
                     .where(ColetaAgenteLote.planta_id.is_not_distinct_from(planta_id),
                            AcaoAgente.estado.in_(("aguardando", "entregue")), AcaoAgente.expira_em > agora,
                            ~_vinculo_lote_alterado()).limit(1))
    if db.scalar(lote_pendente) is not None:
        raise HTTPException(409, "Já há uma coleta em lote em andamento neste escopo.")
    filtros = [Ativo.dominio == Dominio.TI, Ativo.deleted_at.is_(None)]
    if planta_id is not None:
        filtros.append(Ativo.planta_id == planta_id)

    tokens_atuais = (select(TokenAgente.ativo_id, func.max(TokenAgente.id).label("token_id")).where(
        TokenAgente.deleted_at.is_(None), TokenAgente.revogado_em.is_(None),
    ).group_by(TokenAgente.ativo_id).subquery())
    ja_solicitada = exists().where(
        AcaoAgente.token_id == tokens_atuais.c.token_id, AcaoAgente.tipo == "coletar",
        AcaoAgente.planta_id.is_not_distinct_from(Ativo.planta_id),
        AcaoAgente.estado.in_(("aguardando", "entregue")), AcaoAgente.expira_em > agora,
    )
    inventario = db.execute(select(
        Ativo.id, Ativo.planta_id, Ativo.patrimonio, Ativo.numero_serie, tokens_atuais.c.token_id,
        ja_solicitada.label("ja_solicitada"),
    ).outerjoin(tokens_atuais, tokens_atuais.c.ativo_id == Ativo.id).where(*filtros)).all()
    vinculados = [item for item in inventario if item.token_id is not None]
    alvos = [item for item in vinculados if not item.ja_solicitada]
    if not alvos:
        detalhe = "Já há coletas solicitadas para todos os computadores vinculados neste escopo." if vinculados else (
            "Nenhum computador com agente vinculado neste escopo."
        )
        raise HTTPException(409, detalhe)

    lote = ColetaAgenteLote(planta_id=planta_id, solicitante_nome=user.nome, solicitada_em=agora,
                          total=len(alvos), sem_agente=len(inventario) - len(vinculados),
                          ja_solicitados=len(vinculados) - len(alvos))
    db.add(lote)
    db.flush()
    db.execute(insert(AcaoAgente), [
        {"lote_id": lote.id, "lote_alvo": alvo.patrimonio or alvo.numero_serie or f"Ativo #{alvo.id}",
         "ativo_id": alvo.id, "planta_id": alvo.planta_id, "token_id": alvo.token_id,
         "solicitante_id": user.id, "solicitante_nome": user.nome, "tipo": "coletar", "estado": "aguardando",
         "solicitada_em": agora, "expira_em": agora + PRAZO_FILA}
        for alvo in alvos
    ])
    audit(db, user, "solicitar_coleta_agente_lote", "coleta_agente_lote", lote.id,
          ip=request.client.host if request.client else None,
          diff={"planta_id": planta_id, "total": lote.total, "limite_por_minuto": COLETAS_POR_MINUTO})
    resposta = _dados_lote(lote)
    db.commit()
    return resposta


@router.get("/acoes-agente/lotes/{lote_id}")
def progresso_lote(lote_id: int, db: Session = Depends(get_db), user: Usuario = Depends(require_module("ativos")),
                   planta_id: int | None = Depends(planta_ativa_obrigatoria),
                   falhas_offset: int = Query(default=0, ge=0)) -> dict:
    _exigir_acesso_lotes(user)
    lote = db.scalar(_escopo_lotes(select(ColetaAgenteLote).where(ColetaAgenteLote.id == lote_id), planta_id))
    if lote is None:
        raise HTTPException(404, "Coleta em lote não encontrada.")
    agora = datetime.now(timezone.utc)
    pendente = AcaoAgente.estado.in_(("aguardando", "entregue"))
    estado = case(
        (pendente & _vinculo_lote_alterado(), "cancelada"),
        (pendente & (AcaoAgente.expira_em <= agora), "expirada"),
        else_=AcaoAgente.estado,
    ).label("estado")
    itens = (select(AcaoAgente.id, AcaoAgente.lote_alvo.label("ativo"), estado, AcaoAgente.resultado)
             .join(TokenAgente, TokenAgente.id == AcaoAgente.token_id)
             .join(Ativo, Ativo.id == AcaoAgente.ativo_id).where(AcaoAgente.lote_id == lote.id).subquery())
    contagens = dict(db.execute(select(itens.c.estado, func.count()).group_by(itens.c.estado)).all())
    erros = ("falhou", "cancelada", "expirada")
    total_falhas = sum(contagens.get(erro, 0) for erro in erros)
    falhas = db.execute(select(itens.c.ativo, itens.c.estado, itens.c.resultado).where(itens.c.estado.in_(erros))
                        .order_by(itens.c.id).offset(falhas_offset).limit(25)).mappings().all()
    return {
        **_dados_lote(lote),
        "aguardando": contagens.get("aguardando", 0), "em_execucao": contagens.get("entregue", 0),
        "concluidas": contagens.get("concluida", 0), "total_falhas": total_falhas,
        "falhas": [dict(falha) for falha in falhas],
        "proximo_offset": falhas_offset + 25 if falhas_offset + 25 < total_falhas else None,
    }


@router.post("/agente/acoes/consultar")
def consultar(request: Request, db: Session = Depends(get_db)) -> dict:
    token = _token_da_maquina(db, request)
    agora = datetime.now(timezone.utc)
    ativo = db.get(Ativo, token.ativo_id)
    token.ultimo_contato_acoes_em = agora
    candidatos = db.scalars(select(AcaoAgente).where(
        AcaoAgente.token_id == token.id, AcaoAgente.ativo_id == ativo.id,
        AcaoAgente.estado == "aguardando", AcaoAgente.expira_em > agora,
    ).order_by(AcaoAgente.id).limit(10)).all()
    entrega = None
    for item in candidatos:
        autor = db.get(Usuario, item.solicitante_id) if item.solicitante_id is not None else None
        valido = (item.planta_id == ativo.planta_id and autor is not None and autor.ativo
                  and autor.deleted_at is None and _pode_usar(autor)
                  and (eh_admin(autor) or (autor.planta_id is not None and autor.planta_id == ativo.planta_id)))
        horario = agora
        if valido and item.lote_id is not None:
            horario = _horario_entrega_lote(db)
            if horario is None:
                continue
        valores = {"estado": "entregue", "expira_em": horario + PRAZO_RESULTADO} if valido else {
            "estado": "cancelada", "encerrada_em": agora, "resultado": "acesso_ou_vinculo_alterado",
        }
        if valido and item.lote_id is not None:
            valores["lote_entregue_em"] = horario
        mudanca = db.execute(update(AcaoAgente).where(
            AcaoAgente.id == item.id, AcaoAgente.estado == "aguardando", AcaoAgente.expira_em > horario,
        ).values(**valores).execution_options(synchronize_session=False))
        if valido and mudanca.rowcount == 1:
            entrega = {"id": item.id, "tipo": item.tipo}
            break
    db.commit()
    return {"acao": entrega}


@router.post("/agente/acoes/resultado")
def concluir(body: Resultado, request: Request, db: Session = Depends(get_db)) -> dict:
    token = _token_da_maquina(db, request)
    ativo = db.get(Ativo, token.ativo_id)
    item = db.get(AcaoAgente, body.id)
    if item is None or item.token_id != token.id or item.ativo_id != ativo.id or item.planta_id != ativo.planta_id:
        raise HTTPException(404, "Solicitação não encontrada.")
    if body.resultado not in RESULTADOS[item.tipo]:
        raise HTTPException(422, "Resultado inválido para esta ação.")
    agora = datetime.now(timezone.utc)
    mudanca = db.execute(update(AcaoAgente).where(
        AcaoAgente.id == item.id, AcaoAgente.estado == "entregue", AcaoAgente.expira_em > agora,
    ).values(estado="falhou" if body.resultado.startswith("falha_") else "concluida",
             encerrada_em=agora, resultado=body.resultado).execution_options(synchronize_session=False))
    if mudanca.rowcount != 1:
        db.refresh(item)
        if item.estado not in ("concluida", "falhou") or item.resultado != body.resultado:
            raise HTTPException(409, "A solicitação expirou ou não está aguardando resultado.")
    db.commit()
    return {"ok": True}
