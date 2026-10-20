"""Ativos patrimoniais + extensões (TI / Impressora), dashboard e termos."""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.core.deps import (
    get_current_user,
    require_admin,
    require_delete,
    require_module,
    require_write,
)
from app.core.pagination import paginate
from app.core.permissoes import permissoes_efetivas, pode_inventario
from app.core.planta import aplicar_filtro, exigir_planta, planta_ativa
from app.database import get_db
from app.models.core import Ativo, Movimentacao, Termo, Usuario
from app.models.enums import Dominio, FormaAquisicao, StatusAtivo, TipoMov
from app.models.impressora import AtivoImpressora, LeituraContador, SuprimentoImpressora
from app.models.ti import AtivoTI
from app.routers.dashboard import dashboard_stats
from app.schemas.ativos import (
    AtivoCreate,
    AtivoImpressoraBase,
    AtivoOut,
    AtivoTIBase,
    AtivoUpdate,
    AtribuirRequest,
    LeituraContadorCreate,
    LeituraContadorOut,
    StatusChange,
    SuprimentoCreate,
    SuprimentoOut,
)
from app.schemas.common import Page
from app.services import unicidade, zerado_service
from app.services.audit_service import audit
from app.services.counter_service import register_leitura
from app.services.pdf_service import build_termo_pdf
from app.services.qr_service import eh_payload_zerado

router = APIRouter(
    prefix="/ativos", tags=["ativos"], dependencies=[Depends(require_module("ativos"))]
)

_SORT_FIELDS = {"patrimonio", "modelo", "marca", "status", "created_at", "data_garantia"}


def _ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _get_ativo(db: Session, ativo_id: int, planta_id: int | None = None) -> Ativo:
    """Busca o ativo respeitando a planta ativa (isolamento entre localidades).

    `planta_id=None` significa visão consolidada (administrador): encontra
    qualquer ativo.
    """
    obj = db.get(Ativo, ativo_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Ativo não encontrado")
    if planta_id is not None and obj.planta_id != planta_id:
        raise HTTPException(
            404,
            "Este ativo pertence a outra planta. "
            "Troque a planta ativa no topo da tela para acessá-lo.",
        )
    return obj


def _apply_extension(
    ativo: Ativo, dominio: Dominio, ti: AtivoTIBase | None, impressora: AtivoImpressoraBase | None
) -> None:
    """Cria/atualiza a extensão 1:1 conforme o domínio."""
    if dominio == Dominio.TI and ti is not None:
        data = ti.model_dump()
        if ativo.ti is None:
            ativo.ti = AtivoTI(**data)
        else:
            for k, v in data.items():
                setattr(ativo.ti, k, v)
    if dominio == Dominio.IMPRESSORA and impressora is not None:
        data = impressora.model_dump()
        if ativo.impressora is None:
            ativo.impressora = AtivoImpressora(**data)
        else:
            for k, v in data.items():
                setattr(ativo.impressora, k, v)


# ---------------------------------------------------------------------------
# Listagem + Dashboard
# ---------------------------------------------------------------------------
@router.get("", response_model=Page[AtivoOut])
def list_ativos(
    dominio: Dominio | None = Query(default=None),
    status: StatusAtivo | None = Query(default=None),
    categoria_id: int | None = Query(default=None),
    departamento_id: int | None = Query(default=None),
    localizacao_id: int | None = Query(default=None),
    # Filtrar por comprado/locado. Com a maioria do parque em locação, "ver
    # só os locados" é a pergunta que a lista provoca — o chip mostra a
    # natureza, mas sem filtro não dá para isolar.
    forma_aquisicao: FormaAquisicao | None = Query(default=None),
    contrato_id: int | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
    sort: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    # Respeita os inventários que o usuário pode acessar.
    if dominio is not None and not pode_inventario(user, dominio.value):
        raise HTTPException(403, "Sem acesso a este inventário")
    if dominio is None:
        permitidos = permissoes_efetivas(user).get("inventarios") or []
        q_base = db.query(Ativo).filter(Ativo.deleted_at.is_(None), Ativo.dominio.in_(permitidos))
    else:
        q_base = db.query(Ativo).filter(Ativo.deleted_at.is_(None), Ativo.dominio == dominio)
    # Isolamento por planta: usuário comum só vê a planta dele.
    q_base = aplicar_filtro(q_base, Ativo, planta_id)
    q = q_base
    if status is not None:
        q = q.filter(Ativo.status == status)
    if categoria_id is not None:
        q = q.filter(Ativo.categoria_id == categoria_id)
    if departamento_id is not None:
        q = q.filter(Ativo.departamento_id == departamento_id)
    if localizacao_id is not None:
        q = q.filter(Ativo.localizacao_id == localizacao_id)
    if forma_aquisicao is not None:
        q = q.filter(Ativo.forma_aquisicao == forma_aquisicao)
    if contrato_id is not None:
        q = q.filter(Ativo.contrato_id == contrato_id)
    if search:
        like = f"%{search}%"
        # O hostname vive na FICHA TÉCNICA, não no ativo: em TI (`AtivoTI`) ou
        # em impressora (`AtivoImpressora`). Sem as duas junções, procurar por
        # "NTAT" (notebook) ou "RTAT0001" (impressora) não achava nada — e é
        # por esses nomes que as máquinas são conhecidas na rede.
        q = (
            q.outerjoin(AtivoTI, AtivoTI.ativo_id == Ativo.id)
            .outerjoin(AtivoImpressora, AtivoImpressora.ativo_id == Ativo.id)
            .filter(
                or_(
                    Ativo.patrimonio.ilike(like),
                    Ativo.numero_serie.ilike(like),
                    Ativo.modelo.ilike(like),
                    Ativo.marca.ilike(like),
                    AtivoTI.hostname.ilike(like),
                    AtivoTI.ip.ilike(like),
                    AtivoTI.mac_address.ilike(like),
                    AtivoImpressora.hostname.ilike(like),
                    AtivoImpressora.ip.ilike(like),
                )
            )
        )
    if sort and sort.lstrip("-") in _SORT_FIELDS:
        col = getattr(Ativo, sort.lstrip("-"))
        q = q.order_by(col.desc() if sort.startswith("-") else col.asc())
    else:
        q = q.order_by(Ativo.id.desc())

    # Eager load evita N+1 ao serializar extensões.
    q = q.options(selectinload(Ativo.ti), selectinload(Ativo.impressora))
    result = paginate(q, page, size)
    return Page[AtivoOut](**result)


@router.get("/stats", include_in_schema=False, deprecated=True)
def stats_compat(
    dominio: Dominio = Query(default=Dominio.TI),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """Alias antigo de `/dashboard/stats`.

    Mantido apenas para navegadores que ainda tenham o frontend anterior no
    cache do service worker — assim o dashboard não quebra enquanto o cache
    é atualizado. Não usar em código novo.
    """
    return dashboard_stats(dominio=dominio, db=db, user=user)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.get("/{ativo_id}", response_model=AtivoOut)
def get_ativo(
    ativo_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    q = db.query(Ativo).filter(Ativo.id == ativo_id, Ativo.deleted_at.is_(None))
    q = aplicar_filtro(q, Ativo, planta_id)
    q = q.options(selectinload(Ativo.ti), selectinload(Ativo.impressora))
    obj = q.first()
    if obj is None:
        raise HTTPException(404, "Ativo não encontrado")
    return obj


@router.post("", response_model=AtivoOut, status_code=201)
def create_ativo(
    body: AtivoCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa),
):
    # O identificador é o NÚMERO DE SÉRIE. O patrimônio continua aceito, mas
    # deixou de ser obrigatório e de definir unicidade: dois ativos sem
    # patrimônio são válidos, e o que não pode repetir é o serial.
    if db.query(Ativo).filter(
        Ativo.numero_serie == body.numero_serie, Ativo.deleted_at.is_(None)
    ).first():
        raise HTTPException(409, f"Número de série {body.numero_serie} já cadastrado")

    # Patrimônio repetido só é erro quando os dois têm valor: vazio não conta.
    if body.patrimonio and db.query(Ativo).filter(
        Ativo.patrimonio == body.patrimonio, Ativo.deleted_at.is_(None)
    ).first():
        raise HTTPException(409, f"Patrimônio {body.patrimonio} já cadastrado")

    # A checagem acima só olha os VIVOS — e está certa. Mas a constraint
    # UNIQUE do banco vale para todas as linhas, inclusive as excluídas: o
    # soft delete não libera o valor.
    #
    # Sem isto, excluir um ativo e recadastrar o mesmo serial falha com 409
    # vindo do banco, **contradizendo a tela** — que não mostra nada ali.
    unicidade.liberar(db, Ativo, "numero_serie", body.numero_serie, limite=160)
    if body.patrimonio:
        unicidade.liberar(db, Ativo, "patrimonio", body.patrimonio, limite=80)

    data = body.model_dump(exclude={"ti", "impressora"})

    # Um ativo NÃO nasce emprestado — ver a explicação em `update_ativo`.
    # Criar já com este status daria o mesmo problema: emprestado para
    # ninguém, sem prazo, sem termo e fora da agenda.
    if data.get("status") == StatusAtivo.EMPRESTADO:
        raise HTTPException(
            400,
            "Use a tela de Empréstimos para registrar um empréstimo. "
            "Cadastrar o ativo como emprestado deixaria o equipamento sem "
            "responsável, sem prazo e fora da agenda.",
        )
    # Por segurança só aceitamos payload de ETIQUETA EM BRANCO vindo do cliente.
    # Um payload TIATIVO arbitrário não é gravado (a leitura resolve pelo ID de
    # dentro do QR, mas gravar lixo atrapalharia a reimpressão da etiqueta).
    if data.get("qr_payload") and not eh_payload_zerado(data["qr_payload"]):
        data.pop("qr_payload", None)

    ativo = Ativo(**data)
    # A planta vem de quem está criando: usuário comum grava na planta dele;
    # o administrador precisa ter escolhido uma (a visão "todas" não grava).
    ativo.planta_id = exigir_planta(db, planta_id, "cadastrar o ativo")
    db.add(ativo)
    db.flush()
    _apply_extension(ativo, body.dominio, body.ti, body.impressora)

    # Cadastro a partir de uma ETIQUETA EM BRANCO: o ativo nasce com o payload
    # lido e a etiqueta fica vinculada a ele (leitura futura acha o ativo).
    if body.qr_payload and eh_payload_zerado(body.qr_payload):
        try:
            zerado_service.vincular(db, body.qr_payload, ativo)
        except ValueError as exc:
            db.rollback()
            raise HTTPException(409, str(exc))

    audit(db, user, "create", "ativo", ativo.id, ip=_ip(request), diff=data)
    db.commit()
    db.refresh(ativo)
    return ativo


@router.put("/{ativo_id}", response_model=AtivoOut)
def update_ativo(
    ativo_id: int, body: AtivoUpdate, request: Request, db: Session = Depends(get_db),
    user: Usuario = Depends(require_write), planta_id: int | None = Depends(planta_ativa),
):
    ativo = _get_ativo(db, ativo_id, planta_id)

    # O inventário define qual extensão 1:1 existe (ativos_ti / ativos_impressora),
    # então não pode ser trocado depois de criado. O formulário reenvia esses
    # campos, portanto aceitamos — mas recusamos com mensagem clara se diferirem.
    if body.dominio is not None and body.dominio != ativo.dominio:
        raise HTTPException(
            400,
            f"O inventário de um ativo não pode ser alterado (atual: {ativo.dominio.value}). "
            "Cadastre um novo ativo no outro inventário, se for o caso.",
        )

    data = body.model_dump(exclude_unset=True, exclude={"ti", "impressora", "dominio", "tipo_item"})

    # --- "Emprestado" não se define aqui --------------------------------
    #
    # Empréstimo não é um status que se digita: é um registro com
    # responsável, prazo, checklist de retirada e termo. Quem escolhia
    # "emprestado" nesta tela mudava só o campo `status` — **sem criar
    # empréstimo nenhum**.
    #
    # O resultado era o ativo "emprestado" para ninguém: fora da agenda (que
    # lê `devolucao_prevista`), sem prazo, sem termo, e sem aparecer na tela
    # de Empréstimos. A devolução também não existia, porque não havia o que
    # devolver.
    #
    # A recusa é no servidor, e não só escondendo a opção na tela: esconder
    # não protege nada — quem chamar a API direto continuaria podendo.
    if data.get("status") == StatusAtivo.EMPRESTADO:
        raise HTTPException(
            400,
            "Use a tela de Empréstimos para registrar um empréstimo. "
            "Marcar o status aqui deixaria o ativo emprestado sem "
            "responsável, sem prazo e fora da agenda.",
        )

    for k, v in data.items():
        setattr(ativo, k, v)
    _apply_extension(ativo, ativo.dominio, body.ti, body.impressora)
    audit(db, user, "update", "ativo", ativo.id, ip=_ip(request), diff=data)
    db.commit()
    db.refresh(ativo)
    return ativo


@router.delete("/{ativo_id}", status_code=204)
def delete_ativo(
    ativo_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_delete)
):
    ativo = _get_ativo(db, ativo_id)
    ativo.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "ativo", ativo.id, ip=_ip(request))
    db.commit()


# ---------------------------------------------------------------------------
# Status + Atribuição + Termo de Responsabilidade
# ---------------------------------------------------------------------------
@router.patch("/{ativo_id}/status", response_model=AtivoOut)
def change_status(
    ativo_id: int, body: StatusChange, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
):
    ativo = _get_ativo(db, ativo_id)
    old = ativo.status.value
    ativo.status = body.status
    # Emprestar tem fluxo próprio (exige chamado e data de devolução), então
    # este atalho NÃO pode deixar o ativo "emprestado" sem esses dados.
    if body.status == StatusAtivo.EMPRESTADO:
        raise HTTPException(
            400,
            "Para emprestar, use a opção Emprestar — ela pede o número do chamado "
            "e a data de devolução prevista.",
        )
    if old == StatusAtivo.EMPRESTADO.value:
        # Voltando de empréstimo por aqui: encerra o registro do empréstimo.
        _limpar_emprestimo(ativo)
    audit(db, user, "status", "ativo", ativo.id, ip=_ip(request), diff={"de": old, "para": body.status.value})
    db.commit()
    db.refresh(ativo)
    return ativo


def _limpar_emprestimo(ativo: Ativo) -> None:
    """Encerra o empréstimo em aberto (devolução ou troca de status)."""
    ativo.numero_chamado = None
    ativo.emprestado_em = None
    ativo.devolucao_prevista = None
    ativo.emprestado_para_id = None


class EmprestimoRequest(BaseModel):
    """Dados do empréstimo: o chamado é obrigatório (é o registro da saída)."""

    model_config = {"extra": "forbid"}

    numero_chamado: str = Field(min_length=1, max_length=60)
    devolucao_prevista: date
    usuario_id: int | None = None
    localizacao_id: int | None = None
    observacoes: str | None = None


@router.post("/{ativo_id}/emprestimo", response_model=AtivoOut)
def registrar_emprestimo(
    ativo_id: int,
    body: EmprestimoRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
):
    """Registra a saída do ativo por empréstimo, com chamado e devolução."""
    ativo = _get_ativo(db, ativo_id)
    if ativo.status == StatusAtivo.DESCARTADO:
        raise HTTPException(400, "Ativo descartado não pode ser emprestado")
    if ativo.status == StatusAtivo.EMPRESTADO:
        raise HTTPException(
            400,
            f"Este ativo já está emprestado (chamado {ativo.numero_chamado or '—'}). "
            "Registre a devolução antes de emprestar de novo.",
        )

    hoje = date.today()
    if body.devolucao_prevista < hoje:
        raise HTTPException(400, "A devolução prevista não pode ser anterior a hoje.")

    chamado = body.numero_chamado.strip()
    if not chamado:
        raise HTTPException(400, "Informe o número do chamado.")

    ativo.status = StatusAtivo.EMPRESTADO
    ativo.numero_chamado = chamado
    ativo.emprestado_em = hoje
    ativo.devolucao_prevista = body.devolucao_prevista
    ativo.emprestado_para_id = body.usuario_id
    if body.localizacao_id:
        ativo.localizacao_id = body.localizacao_id

    db.add(
        Movimentacao(
            tipo=TipoMov.ATRIBUICAO,
            ativo_id=ativo.id,
            destino_usuario_id=body.usuario_id,
            usuario_id=user.id,
            observacoes=body.observacoes or f"Empréstimo — chamado {chamado}",
        )
    )
    audit(
        db, user, "emprestimo", "ativo", ativo.id, ip=_ip(request),
        diff={
            "numero_chamado": chamado,
            "devolucao_prevista": body.devolucao_prevista.isoformat(),
            "usuario_id": body.usuario_id,
        },
    )
    db.commit()
    db.refresh(ativo)
    return ativo


@router.post("/{ativo_id}/devolucao", response_model=AtivoOut)
def registrar_devolucao(
    ativo_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
):
    """Devolve o ativo: encerra o empréstimo e libera para uso."""
    ativo = _get_ativo(db, ativo_id)
    if ativo.status != StatusAtivo.EMPRESTADO:
        raise HTTPException(400, "Este ativo não está emprestado.")

    chamado = ativo.numero_chamado
    atraso = (date.today() - ativo.devolucao_prevista).days if ativo.devolucao_prevista else 0

    _limpar_emprestimo(ativo)
    ativo.status = StatusAtivo.ESTOQUE

    db.add(
        Movimentacao(
            tipo=TipoMov.DEVOLUCAO,
            ativo_id=ativo.id,
            usuario_id=user.id,
            observacoes=f"Devolução — chamado {chamado}" + (f" ({atraso} dia(s) de atraso)" if atraso > 0 else ""),
        )
    )
    audit(
        db, user, "devolucao", "ativo", ativo.id, ip=_ip(request),
        diff={"numero_chamado": chamado, "dias_atraso": max(0, atraso)},
    )
    db.commit()
    db.refresh(ativo)
    return ativo


@router.post("/{ativo_id}/atribuir", response_model=AtivoOut)
def atribuir(
    ativo_id: int, body: AtribuirRequest, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
):
    ativo = _get_ativo(db, ativo_id)
    if ativo.status == StatusAtivo.DESCARTADO:
        raise HTTPException(400, "Ativo descartado não pode ser atribuído")
    colaborador = db.get(Usuario, body.usuario_id)
    if colaborador is None or colaborador.deleted_at is not None:
        raise HTTPException(404, "Colaborador não encontrado")

    ativo.status = StatusAtivo.EM_USO
    if colaborador.departamento_id:
        ativo.departamento_id = colaborador.departamento_id
    if body.localizacao_id:
        ativo.localizacao_id = body.localizacao_id

    mov = Movimentacao(
        tipo=TipoMov.ATRIBUICAO,
        ativo_id=ativo.id,
        destino_usuario_id=colaborador.id,
        usuario_id=user.id,
        observacoes=body.observacoes,
    )
    db.add(mov)

    # Termo de Responsabilidade em PDF com hash de integridade.
    pdf_bytes, hash_sha = build_termo_pdf(
        patrimonio=ativo.patrimonio,
        modelo=ativo.modelo or "",
        dominio=ativo.dominio.value,
        colaborador_nome=colaborador.nome,
        colaborador_email=colaborador.email,
        departamento=colaborador.departamento.nome if colaborador.departamento else "",
    )
    termo = Termo(ativo_id=ativo.id, usuario_id=colaborador.id, hash_sha256=hash_sha)
    db.add(termo)
    db.flush()
    os.makedirs(os.path.join(settings.media_dir, "termos"), exist_ok=True)
    pdf_path = os.path.join(settings.media_dir, "termos", f"{termo.id}.pdf")
    with open(pdf_path, "wb") as fh:
        fh.write(pdf_bytes)
    termo.pdf_path = pdf_path

    audit(
        db, user, "atribuir", "ativo", ativo.id, ip=_ip(request),
        diff={"usuario_id": colaborador.id, "termo": termo.id, "hash": hash_sha},
    )
    db.commit()
    db.refresh(ativo)
    return ativo


@router.get("/{ativo_id}/termos")
def list_termos(ativo_id: int, db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    return db.query(Termo).filter(Termo.ativo_id == ativo_id, Termo.deleted_at.is_(None)).order_by(Termo.data_assinatura.desc()).all()


@router.get("/{ativo_id}/termos/{termo_id}/pdf")
def download_termo(ativo_id: int, termo_id: int, db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    termo = db.query(Termo).filter(Termo.id == termo_id, Termo.ativo_id == ativo_id, Termo.deleted_at.is_(None)).first()
    if termo is None or not termo.pdf_path or not os.path.exists(termo.pdf_path):
        raise HTTPException(404, "Termo não encontrado")
    return FileResponse(termo.pdf_path, media_type="application/pdf", filename=f"termo_{ativo_id}.pdf")


# ---------------------------------------------------------------------------
# Contador (Impressora) e Suprimentos
# ---------------------------------------------------------------------------
@router.post("/{ativo_id}/leituras", response_model=LeituraContadorOut, status_code=201)
def create_leitura(
    ativo_id: int, body: LeituraContadorCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
):
    ativo = _get_ativo(db, ativo_id)
    if ativo.dominio != Dominio.IMPRESSORA:
        raise HTTPException(400, "Leitura de contador disponível apenas para impressoras")
    leitura = register_leitura(db, ativo, body.contador, body.observacoes)
    audit(db, user, "leitura_contador", "ativo", ativo.id, ip=_ip(request), diff={"contador": body.contador})
    db.commit()
    db.refresh(leitura)
    return leitura


@router.get("/{ativo_id}/leituras", response_model=list[LeituraContadorOut])
def list_leituras(ativo_id: int, db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    return (
        db.query(LeituraContador)
        .filter(LeituraContador.ativo_id == ativo_id, LeituraContador.deleted_at.is_(None))
        .order_by(LeituraContador.data_leitura.desc())
        .all()
    )


@router.get("/{ativo_id}/suprimentos", response_model=list[SuprimentoOut])
def list_suprimentos(ativo_id: int, db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    return (
        db.query(SuprimentoImpressora)
        .filter(SuprimentoImpressora.ativo_id == ativo_id, SuprimentoImpressora.deleted_at.is_(None))
        .order_by(SuprimentoImpressora.id)
        .all()
    )


@router.post("/{ativo_id}/suprimentos", response_model=SuprimentoOut, status_code=201)
def create_suprimento(
    ativo_id: int, body: SuprimentoCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
):
    ativo = _get_ativo(db, ativo_id)
    if ativo.dominio != Dominio.IMPRESSORA:
        raise HTTPException(400, "Suprimentos disponíveis apenas para impressoras")
    obj = SuprimentoImpressora(ativo_id=ativo.id, **body.model_dump())
    db.add(obj)
    db.flush()
    audit(db, user, "create", "suprimento", obj.id, ip=_ip(request), diff=body.model_dump())
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/suprimentos/{suprimento_id}", status_code=204)
def delete_suprimento(
    suprimento_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_delete)
):
    obj = db.get(SuprimentoImpressora, suprimento_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Suprimento não encontrado")
    obj.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "suprimento", obj.id, ip=_ip(request))
    db.commit()


# ---------------------------------------------------------------------------
# Exclusão em lote (somente administrador)
# ---------------------------------------------------------------------------
# Acima desta quantidade, o sistema gera um BACKUP AUTOMÁTICO antes de apagar.
LIMITE_BACKUP_AUTOMATICO = 20


class ExclusaoLoteIn(BaseModel):
    """Seleção para exclusão.

    Ou uma lista explícita de `ids` (o que está marcado na tela), ou
    `todos_do_filtro=True` com os mesmos filtros da listagem — assim dá para
    apagar tudo que a busca retornou sem precisar marcar item por item.
    """

    model_config = {"extra": "forbid"}

    ids: list[int] = Field(default_factory=list)
    todos_do_filtro: bool = False
    dominio: Dominio | None = None
    status: StatusAtivo | None = None
    categoria_id: int | None = None
    departamento_id: int | None = None
    localizacao_id: int | None = None
    search: str | None = None


@router.post("/excluir-lote")
def excluir_lote(
    body: ExclusaoLoteIn,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
    planta_id: int | None = Depends(planta_ativa),
) -> dict:
    """Exclui vários ativos de uma vez.

    **Somente administrador.** A exclusão é lógica (sai das listas e relatórios,
    mas o histórico permanece). Com mais de `LIMITE_BACKUP_AUTOMATICO` itens, um
    backup do banco é gerado ANTES de apagar — se algo der errado, dá para
    restaurar.
    """
    consulta = db.query(Ativo).filter(Ativo.deleted_at.is_(None))
    consulta = aplicar_filtro(consulta, Ativo, planta_id)

    if body.todos_do_filtro:
        # Mesmos filtros da tela de Ativos.
        if body.dominio is not None:
            if not pode_inventario(user, body.dominio.value):
                raise HTTPException(403, "Sem acesso a este inventário")
            consulta = consulta.filter(Ativo.dominio == body.dominio)
        if body.status is not None:
            consulta = consulta.filter(Ativo.status == body.status)
        if body.categoria_id is not None:
            consulta = consulta.filter(Ativo.categoria_id == body.categoria_id)
        if body.departamento_id is not None:
            consulta = consulta.filter(Ativo.departamento_id == body.departamento_id)
        if body.localizacao_id is not None:
            consulta = consulta.filter(Ativo.localizacao_id == body.localizacao_id)
        if body.search:
            like = f"%{body.search}%"
            consulta = consulta.filter(
                or_(
                    Ativo.patrimonio.ilike(like),
                    Ativo.numero_serie.ilike(like),
                    Ativo.modelo.ilike(like),
                    Ativo.marca.ilike(like),
                )
            )
    else:
        if not body.ids:
            raise HTTPException(400, "Nenhum ativo selecionado.")
        consulta = consulta.filter(Ativo.id.in_(body.ids))

    alvos = consulta.with_entities(Ativo.id, Ativo.patrimonio).all()
    if not alvos:
        raise HTTPException(404, "Nenhum ativo encontrado para excluir.")

    quantidade = len(alvos)
    ids = [a[0] for a in alvos]

    # --- Backup automático antes de uma exclusão grande -------------------
    backup = None
    if quantidade > LIMITE_BACKUP_AUTOMATICO:
        try:
            from app.services.backup_service import criar_backup

            backup = criar_backup(motivo="pre-exclusao-lote")
        except Exception as exc:  # noqa: BLE001
            # Sem backup, NÃO apagamos: a segurança vem antes da conveniência.
            raise HTTPException(
                500,
                f"Não foi possível gerar o backup de segurança antes da exclusão: {exc}. "
                "Nada foi apagado.",
            ) from exc

    agora = datetime.now(timezone.utc)
    db.query(Ativo).filter(Ativo.id.in_(ids)).update({"deleted_at": agora}, synchronize_session=False)

    # Um único registro de auditoria: 5.000 linhas de log seriam piores que
    # inúteis. Guarda o total, o critério e uma amostra do que saiu.
    audit(
        db,
        user,
        "delete_lote",
        "ativo",
        None,
        ip=_ip(request),
        diff={
            "quantidade": quantidade,
            "criterio": "filtro" if body.todos_do_filtro else "selecao_manual",
            "filtros": {
                k: (v.value if hasattr(v, "value") else v)
                for k, v in body.model_dump(exclude={"ids"}).items()
            },
            "amostra_patrimonios": [a[1] for a in alvos[:50]],
            "backup": backup.get("arquivo") if isinstance(backup, dict) else None,
        },
    )
    db.commit()

    return {
        "excluidos": quantidade,
        "backup": backup.get("arquivo") if isinstance(backup, dict) else None,
        "backup_gerado": backup is not None,
    }
