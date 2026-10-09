"""Inventário cíclico (contagem) — conferência física.

O fluxo que este módulo atende:

1. Abre a contagem com um escopo (planta, domínio, categoria, localização)
2. O técnico percorre o setor escaneando, e cada leitura é registrada na hora
3. Ao finalizar, o sistema compara lido × esperado
4. O relatório mostra conforme / não encontrado / não cadastrado
5. A aprovação encerra — e, se pedido, dá baixa no que não foi encontrado

**Aditivo:** só lê as tabelas existentes. Não altera nenhuma delas.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user, require_admin, require_module, require_write
from app.core.pagination import paginate
from app.core.planta import aplicar_filtro, planta_ativa
from app.database import get_db
from app.models.contagem import (
    Contagem,
    ContagemItem,
    ResultadoItem,
    StatusContagem,
)
from app.models.core import Ativo, Usuario
from app.models.enums import Dominio
from app.models.ti import AtivoTI
from app.schemas.common import Page
from app.schemas.contagens import (
    AprovarIn,
    ContagemCreate,
    ContagemItemOut,
    ContagemOut,
    DivergenciaOut,
    LeituraIn,
    LeituraOut,
)
from app.services.audit_service import audit

router = APIRouter(
    prefix="/contagens",
    tags=["contagens"],
    dependencies=[Depends(require_module("contagens"))],
)

# Status em que ainda se pode ler ou mexer.
ABERTAS = (StatusContagem.ABERTA, StatusContagem.EM_CONTAGEM)


def _buscar(db: Session, contagem_id: int, planta_id: int | None) -> Contagem:
    """Carrega a contagem respeitando a planta de quem está pedindo."""
    q = db.query(Contagem).filter(
        Contagem.id == contagem_id, Contagem.deleted_at.is_(None)
    )
    q = aplicar_filtro(q, Contagem, planta_id)
    obj = q.first()
    if obj is None:
        raise HTTPException(404, "Contagem não encontrada")
    return obj


def _exigir_aberta(contagem: Contagem, acao: str) -> None:
    if contagem.status not in ABERTAS:
        raise HTTPException(
            400,
            f"Não é possível {acao}: a contagem está '{contagem.status.value}'.",
        )


def _resolver_por_codigo(db: Session, codigo: str) -> Ativo | None:
    """Acha o ativo a partir do que foi lido.

    Aceita patrimônio, número de série e **hostname** — as três formas que
    aparecem na prática: etiqueta colada, etiqueta de fábrica e nome de rede.
    """
    termo = (codigo or "").strip()
    if not termo:
        return None
    return (
        db.query(Ativo)
        .outerjoin(AtivoTI, AtivoTI.ativo_id == Ativo.id)
        .filter(
            Ativo.deleted_at.is_(None),
            or_(
                Ativo.patrimonio.ilike(termo),
                Ativo.numero_serie.ilike(termo),
                AtivoTI.hostname.ilike(termo),
            ),
        )
        .first()
    )


def _esperados(db: Session, contagem: Contagem, planta_id: int | None) -> list[Ativo]:
    """Ativos que DEVERIAM estar no escopo desta contagem."""
    q = db.query(Ativo).filter(Ativo.deleted_at.is_(None))
    # A contagem manda na planta; sem planta definida, usa a de quem consulta.
    q = aplicar_filtro(q, Ativo, contagem.planta_id or planta_id)
    if contagem.dominio:
        q = q.filter(Ativo.dominio == Dominio(contagem.dominio))
    if contagem.categoria_id:
        q = q.filter(Ativo.categoria_id == contagem.categoria_id)
    if contagem.localizacao_id:
        q = q.filter(Ativo.localizacao_id == contagem.localizacao_id)
    return q.all()


def _resumo(db: Session, contagem: Contagem, planta_id: int | None) -> dict:
    """Contadores usados tanto na listagem quanto no detalhe."""
    itens = contagem.itens
    return {
        "lidos": len(itens),
        "nao_cadastrados": len(
            [i for i in itens if i.resultado == ResultadoItem.NAO_CADASTRADO]
        ),
    }


# ---------------------------------------------------------------------------
@router.get("", response_model=Page[ContagemOut])
def listar(
    status: StatusContagem | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    q = db.query(Contagem).filter(Contagem.deleted_at.is_(None))
    q = aplicar_filtro(q, Contagem, planta_id)
    if status is not None:
        q = q.filter(Contagem.status == status)
    q = q.options(selectinload(Contagem.itens))
    result = paginate(q.order_by(Contagem.aberta_em.desc()), page, size)
    return Page[ContagemOut](**result)


@router.post("", response_model=ContagemOut, status_code=201)
def criar(
    body: ContagemCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa),
):
    """Abre uma contagem.

    O escopo é opcional: sem nada preenchido, confere o inventário inteiro da
    planta — que é o caso mais comum na primeira vez.
    """
    if body.dominio and body.dominio not in ("ti", "impressora"):
        raise HTTPException(400, "O domínio deve ser 'ti' ou 'impressora'.")

    contagem = Contagem(
        nome=body.nome.strip(),
        planta_id=planta_id,
        dominio=body.dominio,
        categoria_id=body.categoria_id,
        localizacao_id=body.localizacao_id,
        observacoes=body.observacoes,
        aberta_por_id=user.id,
        status=StatusContagem.ABERTA,
    )
    db.add(contagem)
    db.flush()
    audit(db, user, "criar", "contagem", contagem.id,
          ip=request.client.host if request.client else None,
          diff={"nome": contagem.nome, "dominio": contagem.dominio})
    db.commit()
    db.refresh(contagem)

    # Já informa quantos itens o escopo abrange: o técnico sabe o tamanho do
    # trabalho antes de começar.
    esperados = len(_esperados(db, contagem, planta_id))
    saida = ContagemOut.model_validate(contagem)
    saida.lidos = 0
    saida.nao_cadastrados = 0
    saida.esperados = esperados
    return saida


@router.get("/{contagem_id}", response_model=ContagemOut)
def detalhe(
    contagem_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    contagem = _buscar(db, contagem_id, planta_id)
    saida = ContagemOut.model_validate(contagem)
    resumo = _resumo(db, contagem, planta_id)
    saida.lidos, saida.nao_cadastrados = resumo["lidos"], resumo["nao_cadastrados"]
    saida.esperados = len(_esperados(db, contagem, planta_id))
    return saida


@router.get("/{contagem_id}/itens", response_model=list[ContagemItemOut])
def itens(
    contagem_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    """Leituras registradas, da mais recente para a mais antiga."""
    contagem = _buscar(db, contagem_id, planta_id)
    return (
        db.query(ContagemItem)
        .filter(ContagemItem.contagem_id == contagem.id,
                ContagemItem.deleted_at.is_(None))
        .options(selectinload(ContagemItem.lido_por), selectinload(ContagemItem.ativo))
        .order_by(ContagemItem.lido_em.desc())
        .all()
    )


@router.post("/{contagem_id}/ler", response_model=LeituraOut, status_code=201)
def ler(
    contagem_id: int,
    body: LeituraIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa),
):
    """Registra uma leitura — é o coração do modo sequencial.

    Devolve o resultado na hora, para o técnico saber se aquilo entrou: sem
    retorno imediato ele escaneia no escuro.
    """
    contagem = _buscar(db, contagem_id, planta_id)
    _exigir_aberta(contagem, "registrar leitura")

    codigo = body.codigo.strip()
    ativo = _resolver_por_codigo(db, codigo)

    # Código lido que não corresponde a ativo nenhum: registra como "não
    # cadastrado". É justamente o achado que a auditoria quer enxergar — antes
    # isso se perderia.
    resultado = ResultadoItem.CONFORME if ativo else ResultadoItem.NAO_CADASTRADO

    # Já lido nesta contagem? Não conta de novo, mas avisa.
    repetido = False
    if ativo is not None:
        repetido = (
            db.query(ContagemItem)
            .filter(
                ContagemItem.contagem_id == contagem.id,
                ContagemItem.ativo_id == ativo.id,
                ContagemItem.deleted_at.is_(None),
            )
            .first()
            is not None
        )

    item = ContagemItem(
        contagem_id=contagem.id,
        ativo_id=ativo.id if ativo else None,
        codigo_lido=codigo[:500],
        resultado=resultado,
        lido_por_id=user.id,
        observacoes=body.observacoes,
    )
    db.add(item)

    if contagem.status == StatusContagem.ABERTA:
        contagem.status = StatusContagem.EM_CONTAGEM

    db.flush()
    total = (
        db.query(ContagemItem)
        .filter(ContagemItem.contagem_id == contagem.id,
                ContagemItem.deleted_at.is_(None))
        .count()
    )
    db.commit()
    db.refresh(item)

    if repetido:
        mensagem = f"Já lido antes: {item.ativo_patrimonio}"
    elif ativo is not None:
        mensagem = f"Conforme: {item.ativo_patrimonio}"
    else:
        mensagem = "Não cadastrado — registrado para análise"

    return LeituraOut(item=item, mensagem=mensagem, repetido=repetido, total_lidos=total)


@router.get("/{contagem_id}/divergencias", response_model=DivergenciaOut)
def divergencias(
    contagem_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    """O relatório que justifica a contagem existir.

    Compara o que deveria estar no escopo com o que foi efetivamente lido.
    """
    contagem = _buscar(db, contagem_id, planta_id)
    esperados = _esperados(db, contagem, planta_id)
    itens = contagem.itens

    lidos_ids = {i.ativo_id for i in itens if i.ativo_id is not None}

    nao_encontrados = [
        {
            "id": a.id,
            "patrimonio": a.patrimonio,
            "modelo": a.modelo,
            "marca": a.marca,
            "numero_serie": a.numero_serie,
            "localizacao_id": a.localizacao_id,
        }
        for a in esperados
        if a.id not in lidos_ids
    ]

    # Fora do escopo: ou não é ativo nenhum, ou é ativo que não pertencia a
    # este recorte (outra planta, outra categoria, outro setor).
    nao_cadastrados = [
        {
            "id": i.id,
            "codigo_lido": i.codigo_lido,
            "ativo_id": i.ativo_id,
            "patrimonio": i.ativo_patrimonio,
            "lido_em": i.lido_em.isoformat() if i.lido_em else None,
            "lido_por": i.lido_por_nome,
        }
        for i in itens
        if i.resultado == ResultadoItem.NAO_CADASTRADO
        or (i.ativo_id is not None and i.ativo_id not in {a.id for a in esperados})
    ]

    contagem_por_ativo: dict[int, int] = {}
    for i in itens:
        if i.ativo_id is not None:
            contagem_por_ativo[i.ativo_id] = contagem_por_ativo.get(i.ativo_id, 0) + 1
    repetidos = [
        {"ativo_id": aid, "vezes": n}
        for aid, n in contagem_por_ativo.items()
        if n > 1
    ]

    conformes = len([a for a in esperados if a.id in lidos_ids])
    total_esperado = len(esperados)
    percentual = round((conformes / total_esperado) * 100, 1) if total_esperado else 0.0

    return DivergenciaOut(
        nao_encontrados=nao_encontrados,
        nao_cadastrados=nao_cadastrados,
        repetidos=repetidos,
        esperados=total_esperado,
        lidos=len(itens),
        conformes=conformes,
        percentual=percentual,
    )


@router.post("/{contagem_id}/finalizar", response_model=ContagemOut)
def finalizar(
    contagem_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa),
):
    """Encerra a leitura. A partir daqui o escopo não muda mais."""
    contagem = _buscar(db, contagem_id, planta_id)
    _exigir_aberta(contagem, "finalizar")

    contagem.status = StatusContagem.FINALIZADA
    contagem.finalizada_em = datetime.now(timezone.utc)
    db.commit()
    db.refresh(contagem)

    saida = ContagemOut.model_validate(contagem)
    resumo = _resumo(db, contagem, planta_id)
    saida.lidos, saida.nao_cadastrados = resumo["lidos"], resumo["nao_cadastrados"]
    return saida


@router.post("/{contagem_id}/aprovar", response_model=ContagemOut)
def aprovar(
    contagem_id: int,
    body: AprovarIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
    planta_id: int | None = Depends(planta_ativa),
):
    """Aprova o resultado e encerra a contagem.

    **Somente administrador** — é a etapa que decide sobre patrimônio.

    A baixa dos não encontrados é **opt-in** (`baixar_nao_encontrados`): por
    padrão o relatório é só aceito, e nada é apagado. Ausência na contagem é
    indício, não prova.
    """
    contagem = _buscar(db, contagem_id, planta_id)
    if contagem.status != StatusContagem.FINALIZADA:
        raise HTTPException(
            400,
            "Finalize a contagem antes de aprovar "
            f"(situação atual: '{contagem.status.value}').",
        )

    baixados = 0
    if body.baixar_nao_encontrados:
        lidos_ids = {i.ativo_id for i in contagem.itens if i.ativo_id is not None}
        for ativo in _esperados(db, contagem, planta_id):
            if ativo.id not in lidos_ids:
                # Soft delete: sai das listas e relatórios, o histórico fica.
                ativo.deleted_at = datetime.now(timezone.utc)
                baixados += 1

    contagem.baixados = baixados
    contagem.status = StatusContagem.APROVADA
    contagem.aprovada_por_id = user.id
    contagem.aprovada_em = datetime.now(timezone.utc)
    if body.observacoes:
        contagem.observacoes = (
            f"{contagem.observacoes or ''}\n[Aprovação] {body.observacoes}".strip()
        )

    audit(db, user, "aprovar", "contagem", contagem.id,
          ip=request.client.host if request.client else None,
          diff={"baixados": baixados, "baixar": body.baixar_nao_encontrados})
    db.commit()
    db.refresh(contagem)

    saida = ContagemOut.model_validate(contagem)
    resumo = _resumo(db, contagem, planta_id)
    saida.lidos, saida.nao_cadastrados = resumo["lidos"], resumo["nao_cadastrados"]
    return saida


@router.post("/{contagem_id}/cancelar", response_model=ContagemOut)
def cancelar(
    contagem_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa),
):
    """Cancela sem aplicar nada. As leituras ficam registradas para consulta."""
    contagem = _buscar(db, contagem_id, planta_id)
    if contagem.status in (StatusContagem.APROVADA, StatusContagem.CANCELADA):
        raise HTTPException(400, f"A contagem já está '{contagem.status.value}'.")

    contagem.status = StatusContagem.CANCELADA
    db.commit()
    db.refresh(contagem)

    saida = ContagemOut.model_validate(contagem)
    resumo = _resumo(db, contagem, planta_id)
    saida.lidos, saida.nao_cadastrados = resumo["lidos"], resumo["nao_cadastrados"]
    return saida
