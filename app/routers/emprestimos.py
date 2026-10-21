"""Empréstimo de equipamento — endpoints do ciclo.

Cada passo valida a transição pelo serviço (`emprestimo_service`), e não por
regras soltas aqui: a lógica do ciclo fica num lugar só, testada sem banco.

A devolução compara o checklist com o da entrega e, se houver avaria, já
devolve o que precisa ser feito — a tela não precisa saber a regra.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user, require_write
from app.core.pagination import paginate
from app.core.planta import aplicar_filtro, planta_ativa
from app.database import get_db
from app.models.core import Ativo, Usuario
from app.models.emprestimo import (
    ChecklistItem,
    Emprestimo,
    EmprestimoItem,
    MomentoChecklist,
    SituacaoEmprestimo,
)
from app.models.enums import StatusAtivo
from app.schemas.common import Page
from app.services import emprestimo_service as svc
from app.services.audit_service import audit

router = APIRouter(prefix="/emprestimos", tags=["emprestimos"])


# ---------------------------------------------------------------------------
# Schemas (locais: são exclusivos deste ciclo)
# ---------------------------------------------------------------------------
class ReservaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ativo_id: int
    usuario_id: int | None = None
    retirado_por_nome: str | None = Field(default=None, max_length=160)
    departamento_id: int | None = None
    finalidade: str | None = Field(default=None, max_length=200)
    observacoes: str | None = None
    devolucao_prevista: datetime | None = None


class ItemConferido(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rotulo: str = Field(min_length=1, max_length=160)
    ok: bool
    observacoes: str | None = None


class ChecklistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    itens: list[ItemConferido] = Field(default_factory=list)
    observacoes: str | None = None
    # Confirmacao de que o termo foi assinado. Ao marcar, o sistema cria o
    # registro Termo (com hash e data) e vincula - e o que tira a retirada do papel.
    confirmar_termo: bool = False


class VistoriaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observacoes: str | None = None
    abrir_manutencao: bool = False


# ---------------------------------------------------------------------------
def _buscar(db: Session, emp_id: int, planta_id: int | None) -> Emprestimo:
    q = (
        db.query(Emprestimo)
        .options(
            selectinload(Emprestimo.itens),
            selectinload(Emprestimo.ativo),
            selectinload(Emprestimo.usuario),
        )
        .filter(Emprestimo.id == emp_id, Emprestimo.deleted_at.is_(None))
    )
    q = aplicar_filtro(q, Emprestimo, planta_id)
    obj = q.first()
    if obj is None:
        raise HTTPException(404, "Empréstimo não encontrado")
    return obj


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _itens_de(db: Session, emp_id: int, momento: MomentoChecklist) -> dict[str, bool]:
    """Le do banco, e nao da colecao emp.itens.

    A colecao e carregada quando o emprestimo e buscado; itens adicionados
    depois (na propria requisicao) podem nao estar nela. Consultar direto
    evita depender do estado da sessao - foi o que fez a devolucao nao acusar
    avaria.
    """
    q = db.query(EmprestimoItem).filter(
        EmprestimoItem.emprestimo_id == emp_id,
        EmprestimoItem.momento == momento,
        EmprestimoItem.deleted_at.is_(None),
    )
    return {i.rotulo: i.ok for i in q.all()}


def _bloqueio_por_atraso(db: Session, usuario_id: int | None) -> tuple[Emprestimo, dict] | None:
    """Emprestimo em aberto que bloqueia novos - se houver.

    A escada do serviço decide: 15 dias de atraso bloqueiam. Quem esta nesse
    degrau nao leva equipamento novo ate regularizar.
    """
    if usuario_id is None:
        return None
    abertos = (
        db.query(Emprestimo)
        .filter(
            Emprestimo.usuario_id == usuario_id,
            Emprestimo.situacao == SituacaoEmprestimo.RETIRADO,
            Emprestimo.deleted_at.is_(None),
        )
        .all()
    )
    for e in abertos:
        alerta = svc.escalonamento(e.devolucao_prevista)
        if alerta.get("bloqueia_novo_emprestimo"):
            return e, alerta
    return None


def _saida(db: Session, emp: Emprestimo) -> dict:
    """Resumo com o que a tela precisa: situação, alerta e próximos passos."""
    resumo = svc.resumo_do_ciclo(
        emp.situacao,
        emp.devolucao_prevista,
        tem_termo=emp.termo_id is not None,
        tem_checklist_entrega=bool(_itens_de(db, emp.id, MomentoChecklist.ENTREGA)),
    )
    return {
        "id": emp.id,
        "ativo_id": emp.ativo_id,
        "ativo_patrimonio": emp.ativo_patrimonio,
        "situacao": emp.situacao.value,
        "retirado_por": emp.retirado_por_nome_final,
        "finalidade": emp.finalidade,
        "reservado_em": emp.reservado_em,
        "retirado_em": emp.retirado_em,
        "devolucao_prevista": emp.devolucao_prevista,
        "devolvido_em": emp.devolvido_em,
        "vistoriado_em": emp.vistoriado_em,
        "tem_avaria": emp.tem_avaria,
        "bloqueado": emp.bloqueado,
        "observacoes": emp.observacoes,
        **resumo,
    }


# ---------------------------------------------------------------------------
@router.get("", response_model=Page[dict])
def listar(
    situacao: SituacaoEmprestimo | None = Query(default=None),
    ativo_id: int | None = Query(default=None),
    usuario_id: int | None = Query(default=None),
    search: str | None = Query(default=None, description="Busca por equipamento, pessoa ou chamado"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    """O histórico de empréstimos, com filtros.

    ## Os filtros existem para responder duas perguntas

    *"O que a Ana já levou?"* e *"por quais mãos este notebook passou?"* —
    são as duas perguntas de quem audita empréstimo, e nenhuma delas era
    possível: a lista só filtrava por situação e por um `ativo_id` que a tela
    nunca enviava.

    ## Por que subconsulta, e não `join`

    `paginate` conta as linhas do resultado. Um `join` com `Ativo` ou
    `Usuario` multiplicaria a linha do empréstimo quando houvesse mais de uma
    correspondência — e a contagem de páginas sairia errada. A subconsulta
    filtra por `in_`, mantém uma linha por empréstimo, e a paginação continua
    correta.

    ## O que a busca cobre

    Patrimônio e número de série do equipamento, nome e e-mail do usuário,
    o nome digitado livremente na reserva, e o número do chamado. É o que
    alguém tem à mão quando procura.
    """
    q = db.query(Emprestimo).filter(Emprestimo.deleted_at.is_(None))
    q = aplicar_filtro(q, Emprestimo, planta_id)

    if situacao is not None:
        q = q.filter(Emprestimo.situacao == situacao)
    if ativo_id is not None:
        q = q.filter(Emprestimo.ativo_id == ativo_id)
    if usuario_id is not None:
        q = q.filter(Emprestimo.usuario_id == usuario_id)

    if search and search.strip():
        like = f"%{search.strip()}%"
        # O número do chamado mora no ATIVO, não no empréstimo — é o chamado
        # de manutenção do equipamento. Procurá-lo em `Emprestimo` levantava
        # `AttributeError` e derrubava a busca inteira com 500.
        ativos = (
            db.query(Ativo.id)
            .filter(or_(
                Ativo.patrimonio.ilike(like),
                Ativo.numero_serie.ilike(like),
                Ativo.numero_chamado.ilike(like),
            ))
            .subquery()
        )
        usuarios = (
            db.query(Usuario.id)
            .filter(or_(Usuario.nome.ilike(like), Usuario.email.ilike(like)))
            .subquery()
        )
        q = q.filter(or_(
            Emprestimo.ativo_id.in_(select(ativos.c.id)),
            Emprestimo.usuario_id.in_(select(usuarios.c.id)),
            # Nome digitado livremente na reserva — quem não tem conta no
            # sistema também precisa ser encontrável no histórico.
            Emprestimo.retirado_por_nome.ilike(like),
        ))

    q = q.options(
        selectinload(Emprestimo.itens),
        selectinload(Emprestimo.ativo),
        selectinload(Emprestimo.usuario),
    )
    resultado = paginate(q.order_by(Emprestimo.reservado_em.desc()), page, size)
    resultado["items"] = [_saida(db, e) for e in resultado["items"]]
    return Page[dict](**resultado)


# ---------------------------------------------------------------------------
# Checklist configurável (a tela de Administração usa estes)
#
# Declarado ANTES de `/{emp_id}` de propósito: caminhos fixos precisam vir
# primeiro, senão o FastAPI tentaria ler "checklist" como um id.
# ---------------------------------------------------------------------------
@router.get("/checklist/modelo", response_model=list[dict])
def checklist_modelo(
    categoria_id: int | None = Query(default=None),
    dominio: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    """Itens do checklist aplicáveis — gerais + os da categoria."""
    q = db.query(ChecklistItem).filter(
        ChecklistItem.deleted_at.is_(None), ChecklistItem.ativo.is_(True)
    )
    if dominio:
        q = q.filter((ChecklistItem.dominio.is_(None)) | (ChecklistItem.dominio == dominio))
    else:
        q = q.filter(ChecklistItem.dominio.is_(None))
    if categoria_id is not None:
        q = q.filter((ChecklistItem.categoria_id.is_(None))
                     | (ChecklistItem.categoria_id == categoria_id))
    else:
        q = q.filter(ChecklistItem.categoria_id.is_(None))

    return [
        {
            "id": i.id, "rotulo": i.rotulo, "ajuda": i.ajuda, "ordem": i.ordem,
            "na_entrega": i.na_entrega, "na_devolucao": i.na_devolucao,
            "categoria_id": i.categoria_id, "dominio": i.dominio,
            "abre_manutencao": i.abre_manutencao,
        }
        for i in q.order_by(ChecklistItem.ordem, ChecklistItem.id).all()
    ]


@router.get("/{emp_id}", response_model=dict)
def detalhe(
    emp_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    return _saida(db, _buscar(db, emp_id, planta_id))


@router.post("", response_model=dict, status_code=201)
def reservar(
    body: ReservaIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa),
):
    """Reserva o equipamento. Ainda não saiu — só está separado."""
    ativo = db.get(Ativo, body.ativo_id)
    if ativo is None or ativo.deleted_at is not None:
        raise HTTPException(404, "Ativo não encontrado")

    # Já emprestado? Uma segunda reserva só criaria conflito de retirada.
    em_uso = (
        db.query(Emprestimo)
        .filter(
            Emprestimo.ativo_id == ativo.id,
            Emprestimo.deleted_at.is_(None),
            Emprestimo.situacao.in_([SituacaoEmprestimo.RESERVADO,
                                     SituacaoEmprestimo.RETIRADO]),
        )
        .first()
    )
    if em_uso is not None:
        raise HTTPException(
            400,
            f"Este ativo já está com empréstimo em aberto (#{em_uso.id}, "
            f"situação '{em_uso.situacao.value}').",
        )

    if body.usuario_id is None and not (body.retirado_por_nome or "").strip():
        raise HTTPException(400, "Informe para quem é o empréstimo.")

    # Escalonamento do atraso: no degrau mais alto, não se leva equipamento novo.
    bloqueio = _bloqueio_por_atraso(db, body.usuario_id)
    if bloqueio is not None:
        emp_antigo, alerta = bloqueio
        raise HTTPException(
            400,
            f"Novo empréstimo bloqueado: há {alerta['dias_atraso']} dias de atraso "
            f"no empréstimo #{emp_antigo.id}. Regularize a devolução primeiro.",
        )

    emp = Emprestimo(
        ativo_id=ativo.id,
        planta_id=planta_id or ativo.planta_id,
        usuario_id=body.usuario_id,
        retirado_por_nome=body.retirado_por_nome,
        departamento_id=body.departamento_id,
        finalidade=body.finalidade,
        observacoes=body.observacoes,
        devolucao_prevista=body.devolucao_prevista,
        reservado_por_id=user.id,
        situacao=SituacaoEmprestimo.RESERVADO,
    )
    db.add(emp)
    db.flush()

    # --- A reserva também marca o ativo ---------------------------------
    #
    # ## Por que isto faltava, e o que custava
    #
    # A **agenda** (Calendário) não lê a tabela `emprestimos`: ela lê os
    # campos do próprio `Ativo` (`status`, `emprestado_em`,
    # `devolucao_prevista`). Era uma escolha acertada — uma consulta só, sem
    # junção, e o ativo carrega o seu estado.
    #
    # Mas esta rota criava o `Emprestimo` e **não tocava no ativo**. O
    # empréstimo existia, aparecia na tela de Empréstimos, e ficava
    # **invisível na agenda** até alguém registrar a retirada (que é quem
    # preenchia os campos). Quem reservava não via a reserva agendada.
    #
    # Pior: a única forma de o ativo aparecer na agenda antes disso era mudar
    # o status **à mão na tela de Ativo** — que não cria empréstimo nenhum, e
    # deixava o ativo "emprestado" sem ninguém responsável.
    #
    # ## `emprestado_em = hoje`
    #
    # A reserva **tira o equipamento de circulação**: ninguém mais pode
    # levá-lo. A agenda precisa de uma data de início para desenhar a faixa
    # de dias, e `None` quebraria a interseção da consulta. Na retirada, este
    # campo é reescrito com a data real (`retirado_em`) — então ele nunca
    # mente sobre quando o aparelho saiu de fato.
    ativo.status = StatusAtivo.RESERVADO
    ativo.emprestado_em = date.today()
    ativo.devolucao_prevista = (
        body.devolucao_prevista.date() if body.devolucao_prevista else None
    )
    ativo.emprestado_para_id = body.usuario_id

    audit(db, user, "reservar", "emprestimo", emp.id,
          ip=request.client.host if request.client else None,
          diff={"ativo": ativo.patrimonio})
    db.commit()
    db.refresh(emp)
    return _saida(db, emp)


@router.post("/{emp_id}/retirar", response_model=dict)
def retirar(
    emp_id: int,
    body: ChecklistIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa),
):
    """Registra a retirada — exige conferência de entrega.

    O termo assinado é conferido em `termo_id`; sem ele, a transição é
    recusada com o motivo.
    """
    emp = _buscar(db, emp_id, planta_id)

    # Assinar o termo nesta etapa cria o registro e libera a transicao.
    if body.confirmar_termo and emp.termo_id is None:
        import hashlib

        from app.models.core import Termo

        conteudo = (
            f"Emprestimo #{emp.id} - ativo {emp.ativo_patrimonio or emp.ativo_id} - "
            f"para {emp.retirado_por_nome_final or 'nao informado'} - "
            f"termo de responsabilidade confirmado na retirada"
        )
        termo = Termo(
            ativo_id=emp.ativo_id,
            # Termo.usuario_id e obrigatorio no modelo (que nao foi alterado).
            # Emprestimo para quem NAO tem login - visitante, terceiro - cai no
            # operador que registra; o nome do retirante vai no conteudo do termo.
            usuario_id=emp.usuario_id or user.id,
            hash_sha256=hashlib.sha256(conteudo.encode("utf-8")).hexdigest(),
            data_assinatura=_agora(),
            observacoes=conteudo,
        )
        db.add(termo)
        db.flush()
        emp.termo_id = termo.id

    checklist = [i for i in body.itens]
    validacao = svc.validar_transicao(
        emp.situacao, SituacaoEmprestimo.RETIRADO,
        tem_termo=emp.termo_id is not None,
        tem_checklist=bool(checklist),
    )
    if not validacao["ok"]:
        raise HTTPException(400, validacao["motivo"])

    for i in checklist:
        db.add(EmprestimoItem(
            emprestimo_id=emp.id, momento=MomentoChecklist.ENTREGA,
            rotulo=i.rotulo, ok=i.ok, observacoes=i.observacoes,
            conferido_por_id=user.id,
        ))

    emp.situacao = SituacaoEmprestimo.RETIRADO
    emp.retirado_em = _agora()
    emp.retirada_registrada_por_id = user.id
    if body.observacoes:
        emp.observacoes = f"{emp.observacoes or ''}\n[Retirada] {body.observacoes}".strip()

    # O ativo passa a constar como emprestado para o resto do sistema.
    ativo = db.get(Ativo, emp.ativo_id)
    if ativo is not None:
        ativo.emprestado_em = emp.retirado_em
        ativo.emprestado_para_id = emp.usuario_id
        ativo.devolucao_prevista = emp.devolucao_prevista
        ativo.status = StatusAtivo.EMPRESTADO

    audit(db, user, "retirar", "emprestimo", emp.id,
          ip=request.client.host if request.client else None,
          diff={"itens_conferidos": len(checklist)})
    db.commit()
    db.refresh(emp)
    return _saida(db, emp)


@router.post("/{emp_id}/devolver", response_model=dict)
def devolver(
    emp_id: int,
    body: ChecklistIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa),
):
    """Registra a devolução e **compara com a entrega**.

    É a comparação que revela avaria: sem saber como saiu, não há como afirmar
    que voltou pior.
    """
    emp = _buscar(db, emp_id, planta_id)

    checklist = list(body.itens)
    validacao = svc.validar_transicao(
        emp.situacao, SituacaoEmprestimo.DEVOLVIDO, tem_checklist=bool(checklist)
    )
    if not validacao["ok"]:
        raise HTTPException(400, validacao["motivo"])

    for i in checklist:
        db.add(EmprestimoItem(
            emprestimo_id=emp.id, momento=MomentoChecklist.DEVOLUCAO,
            rotulo=i.rotulo, ok=i.ok, observacoes=i.observacoes,
            conferido_por_id=user.id,
        ))
    db.flush()

    entrega = _itens_de(db, emp.id, MomentoChecklist.ENTREGA)
    # A devolucao sai do que acabou de ser ENVIADO, nao da colecao emp.itens:
    # ela foi carregada do banco antes destes itens existirem, e comparar contra
    # uma lista vazia nunca acusaria avaria.
    devolucao = {i.rotulo: i.ok for i in checklist}
    # Os itens comparados sao os DESTE emprestimo, nao os de fabrica: o
    # checklist e configuravel e pode ter mudado desde a retirada. Sem isto, a
    # comparacao percorria os 7 rotulos padrao, nao encontrava nenhum e nunca
    # acusava avaria.
    laudo = svc.avaliar_devolucao(
        entrega, devolucao, itens=list(entrega.keys()) or list(devolucao.keys())
    )

    emp.situacao = SituacaoEmprestimo.DEVOLVIDO
    emp.devolvido_em = _agora()
    emp.devolucao_registrada_por_id = user.id
    emp.tem_avaria = bool(laudo["avarias"])
    if body.observacoes:
        emp.observacoes = f"{emp.observacoes or ''}\n[Devolução] {body.observacoes}".strip()

    ativo = db.get(Ativo, emp.ativo_id)
    if ativo is not None:
        ativo.emprestado_em = None
        ativo.emprestado_para_id = None
        ativo.devolucao_prevista = None
        ativo.status = StatusAtivo.MANUTENCAO if laudo["abrir_manutencao"] else StatusAtivo.ESTOQUE

    audit(db, user, "devolver", "emprestimo", emp.id,
          ip=request.client.host if request.client else None,
          diff={"avarias": laudo["avarias"]})
    db.commit()
    db.refresh(emp)

    saida = _saida(db, emp)
    saida["laudo"] = laudo          # a tela mostra o que a comparação achou
    return saida


@router.post("/{emp_id}/vistoriar", response_model=dict)
def vistoriar(
    emp_id: int,
    body: VistoriaIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa),
):
    """Encerra o ciclo.

    `abrir_manutencao` só tem efeito se a devolução apontou avaria — abrir
    ordem de serviço num equipamento que voltou íntegro seria ruído.
    """
    emp = _buscar(db, emp_id, planta_id)

    validacao = svc.validar_transicao(emp.situacao, SituacaoEmprestimo.VISTORIADO)
    if not validacao["ok"]:
        raise HTTPException(400, validacao["motivo"])

    if body.abrir_manutencao and not emp.tem_avaria:
        raise HTTPException(
            400, "Não há avaria registrada na devolução — não há o que abrir."
        )

    manutencao_id = None
    if body.abrir_manutencao and emp.tem_avaria:
        from app.models.core import Manutencao

        m = Manutencao(
            ativo_id=emp.ativo_id,
            descricao=f"Avaria identificada na devolução do empréstimo #{emp.id}",
            observacoes=body.observacoes,
        )
        db.add(m)
        db.flush()
        manutencao_id = m.id

    emp.situacao = SituacaoEmprestimo.VISTORIADO
    emp.vistoriado_em = _agora()
    emp.vistoriado_por_id = user.id
    emp.manutencao_id = manutencao_id

    audit(db, user, "vistoriar", "emprestimo", emp.id,
          ip=request.client.host if request.client else None,
          diff={"manutencao_id": manutencao_id})
    db.commit()
    db.refresh(emp)

    saida = _saida(db, emp)
    saida["manutencao_id"] = manutencao_id
    return saida


@router.post("/{emp_id}/cancelar", response_model=dict)
def cancelar(
    emp_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa),
):
    """Cancela uma reserva que não chegou a sair."""
    emp = _buscar(db, emp_id, planta_id)

    validacao = svc.validar_transicao(emp.situacao, SituacaoEmprestimo.CANCELADO)
    if not validacao["ok"]:
        raise HTTPException(400, validacao["motivo"])

    emp.situacao = SituacaoEmprestimo.CANCELADO
    emp.cancelado_em = _agora()
    db.commit()
    db.refresh(emp)
    return _saida(db, emp)
