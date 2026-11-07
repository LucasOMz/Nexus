"""Kanban — buckets, atividades, checklist e responsáveis.

## Permissão

Tudo passa por `require_module("kanban")`, que é o mesmo mecanismo das
outras telas: o administrador libera o módulo no cadastro do usuário. Sem
ele, a rota responde 403 e o menu não mostra o ícone.

**Atribuir responsável é só do administrador** — é o que separa "eu organizo
minhas tarefas" de "eu distribuo tarefas para os outros".

## Escopo por planta

Bucket tem `planta_id`; atividade herda. `aplicar_filtro` garante que um
técnico da planta A não veja o quadro da B — a mesma regra de ativos.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user, require_admin, require_module
from app.core.planta import aplicar_filtro, exigir_planta, planta_ativa
from app.database import get_db
from app.models.core import Usuario
from app.models.kanban import Atividade, AtividadeItem, AtividadeResponsavel, Bucket

router = APIRouter(
    prefix="/kanban",
    tags=["kanban"],
    dependencies=[Depends(require_module("kanban"))],
)


# ---------------------------------------------------------------------------
# Saída
# ---------------------------------------------------------------------------


class ItemOut(BaseModel):
    id: int
    texto: str
    feito: bool
    ordem: int

    model_config = {"from_attributes": True}


class ResponsavelOut(BaseModel):
    usuario_id: int
    nome: str
    email: str


class AtividadeOut(BaseModel):
    id: int
    bucket_id: int
    titulo: str
    descricao: str | None = None
    ordem: int
    prazo: datetime | None = None
    data_inicio: datetime | None = None
    prioridade: str = "normal"
    progresso: int = 0
    concluida_em: datetime | None = None
    concluida: bool = False
    atrasada: bool = False
    total_itens: int = 0
    itens_feitos: int = 0
    itens: list[ItemOut] = []
    responsaveis: list[ResponsavelOut] = []


class BucketOut(BaseModel):
    id: int
    nome: str
    ordem: int
    cor: str | None = None
    atividades: list[AtividadeOut] = []


def _serializar(atividade: Atividade, nomes: dict[int, tuple[str, str]]) -> AtividadeOut:
    return AtividadeOut(
        id=atividade.id,
        bucket_id=atividade.bucket_id,
        titulo=atividade.titulo,
        descricao=atividade.descricao,
        ordem=atividade.ordem,
        prazo=atividade.prazo,
        data_inicio=atividade.data_inicio,
        prioridade=atividade.prioridade or "normal",
        progresso=atividade.progresso or 0,
        concluida_em=atividade.concluida_em,
        concluida=atividade.concluida,
        atrasada=atividade.atrasada,
        total_itens=atividade.total_itens,
        itens_feitos=atividade.itens_feitos,
        itens=[
            ItemOut(id=i.id, texto=i.texto, feito=i.feito, ordem=i.ordem)
            for i in sorted(atividade.itens, key=lambda x: (x.ordem, x.id))
        ],
        responsaveis=[
            ResponsavelOut(
                usuario_id=r.usuario_id,
                nome=nomes.get(r.usuario_id, ("", ""))[0],
                email=nomes.get(r.usuario_id, ("", ""))[1],
            )
            for r in atividade.responsaveis
        ],
    )


# ---------------------------------------------------------------------------
# Quadro
# ---------------------------------------------------------------------------


@router.get("", response_model=list[BucketOut])
def quadro(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
) -> list[BucketOut]:
    """O quadro inteiro: buckets com as atividades dentro."""
    consulta = aplicar_filtro(db.query(Bucket), Bucket, planta_id)
    buckets = (
        consulta.options(
            selectinload(Bucket.atividades).selectinload(Atividade.itens),
            selectinload(Bucket.atividades).selectinload(Atividade.responsaveis),
        )
        .order_by(Bucket.ordem, Bucket.id)
        .all()
    )

    # Nomes dos responsáveis numa consulta só — evita N+1.
    ids = {r.usuario_id for b in buckets for a in b.atividades for r in a.responsaveis}
    nomes: dict[int, tuple[str, str]] = {}
    if ids:
        for u in db.query(Usuario).filter(Usuario.id.in_(ids)).all():
            nomes[u.id] = (u.nome, u.email)

    return [
        BucketOut(
            id=b.id,
            nome=b.nome,
            ordem=b.ordem,
            cor=b.cor,
            atividades=[
                _serializar(a, nomes)
                for a in sorted(b.atividades, key=lambda x: (x.ordem, x.id))
            ],
        )
        for b in buckets
    ]


# ---------------------------------------------------------------------------
# Buckets
# ---------------------------------------------------------------------------


class BucketEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    cor: str | None = Field(default=None, max_length=20)


@router.post("/buckets", response_model=BucketOut)
def criar_bucket(
    entrada: BucketEntrada,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
) -> BucketOut:
    destino = exigir_planta(db, planta_id, "criar bucket")
    ultimo = (
        db.query(Bucket.ordem).filter(Bucket.planta_id == destino)
        .order_by(Bucket.ordem.desc()).first()
    )
    bucket = Bucket(
        planta_id=destino,
        nome=entrada.nome.strip(),
        cor=entrada.cor,
        ordem=(ultimo[0] + 1) if ultimo else 0,
    )
    db.add(bucket)
    db.commit()
    db.refresh(bucket)
    return BucketOut(id=bucket.id, nome=bucket.nome, ordem=bucket.ordem,
                     cor=bucket.cor, atividades=[])


class BucketPatch(BaseModel):
    """Edicao parcial: nome e cor sao independentes.

    `cor = ""` LIMPA a cor. Antes, `None` significava "nao mexer" e nao havia
    como remover uma cor escolhida por engano.
    """

    nome: str | None = Field(default=None, min_length=1, max_length=80)
    cor: str | None = Field(default=None, max_length=20)


@router.patch("/buckets/{bucket_id}", response_model=BucketOut)
def editar_bucket(
    bucket_id: int,
    entrada: BucketPatch,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> BucketOut:
    bucket = db.get(Bucket, bucket_id)
    if bucket is None:
        raise HTTPException(404, "Bucket não encontrado.")
    if entrada.nome is not None:
        bucket.nome = entrada.nome.strip()
    if entrada.cor is not None:
        bucket.cor = entrada.cor.strip() or None
    db.commit()
    db.refresh(bucket)
    return BucketOut(id=bucket.id, nome=bucket.nome, ordem=bucket.ordem,
                     cor=bucket.cor, atividades=[])


@router.delete("/buckets/{bucket_id}")
def excluir_bucket(
    bucket_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    bucket = db.get(Bucket, bucket_id)
    if bucket is None:
        raise HTTPException(404, "Bucket não encontrado.")
    # Apagar um bucket leva as atividades junto (cascade). A tela precisa
    # avisar: é a diferença entre "arquivar a coluna" e "perder os cartões".
    db.delete(bucket)
    db.commit()
    return {"ok": True}


class OrdemEntrada(BaseModel):
    ids: list[int] = Field(min_length=1)


@router.post("/buckets/ordem")
def reordenar_buckets(
    entrada: OrdemEntrada,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """Reescreve a ordem dos buckets conforme a lista recebida."""
    for posicao, bucket_id in enumerate(entrada.ids):
        bucket = db.get(Bucket, bucket_id)
        if bucket is not None:
            bucket.ordem = posicao
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Atividades
# ---------------------------------------------------------------------------


class AtividadeEntrada(BaseModel):
    bucket_id: int
    titulo: str = Field(min_length=1, max_length=200)
    descricao: str | None = None
    prazo: datetime | None = None
    data_inicio: datetime | None = None
    # `Literal` barra valor inventado: sem isso, "urgentissimo" entraria e
    # o filtro simplesmente nao o encontraria, sem erro nenhum.
    prioridade: Literal["baixa", "normal", "alta", "urgente"] = "normal"
    progresso: int = Field(default=0, ge=0, le=100)


@router.post("/atividades", response_model=AtividadeOut)
def criar_atividade(
    entrada: AtividadeEntrada,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> AtividadeOut:
    bucket = db.get(Bucket, entrada.bucket_id)
    if bucket is None:
        raise HTTPException(404, "Bucket não encontrado.")

    ultimo = (
        db.query(Atividade.ordem).filter(Atividade.bucket_id == bucket.id)
        .order_by(Atividade.ordem.desc()).first()
    )
    atividade = Atividade(
        bucket_id=bucket.id,
        titulo=entrada.titulo.strip(),
        descricao=entrada.descricao,
        prazo=entrada.prazo,
        data_inicio=entrada.data_inicio,
        prioridade=entrada.prioridade,
        progresso=entrada.progresso,
        ordem=(ultimo[0] + 1) if ultimo else 0,
        criado_por_id=user.id,
    )
    db.add(atividade)
    db.commit()
    db.refresh(atividade)
    return _serializar(atividade, {})


@router.patch("/atividades/{atividade_id}", response_model=AtividadeOut)
def editar_atividade(
    atividade_id: int,
    entrada: AtividadeEntrada,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> AtividadeOut:
    atividade = db.get(Atividade, atividade_id)
    if atividade is None:
        raise HTTPException(404, "Atividade não encontrada.")
    atividade.titulo = entrada.titulo.strip()
    atividade.descricao = entrada.descricao
    atividade.prazo = entrada.prazo
    atividade.data_inicio = entrada.data_inicio
    atividade.prioridade = entrada.prioridade
    atividade.progresso = entrada.progresso
    db.commit()
    db.refresh(atividade)
    return _serializar(atividade, {})


class MoverEntrada(BaseModel):
    bucket_id: int
    ordem: int = 0


@router.post("/atividades/{atividade_id}/mover", response_model=AtividadeOut)
def mover_atividade(
    atividade_id: int,
    entrada: MoverEntrada,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> AtividadeOut:
    """Move o cartão para outro bucket, ou reposiciona no mesmo."""
    atividade = db.get(Atividade, atividade_id)
    if atividade is None:
        raise HTTPException(404, "Atividade não encontrada.")
    destino = db.get(Bucket, entrada.bucket_id)
    if destino is None:
        raise HTTPException(404, "Bucket de destino não encontrado.")

    atividade.bucket_id = destino.id
    atividade.ordem = entrada.ordem
    db.commit()
    db.refresh(atividade)
    return _serializar(atividade, {})


@router.post("/atividades/{atividade_id}/concluir", response_model=AtividadeOut)
def concluir_atividade(
    atividade_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> AtividadeOut:
    """Marca ou desmarca como concluída.

    É alternado: clicar de novo reabre. Uma conclusão acidental não pode
    exigir editar o cartão.
    """
    atividade = db.get(Atividade, atividade_id)
    if atividade is None:
        raise HTTPException(404, "Atividade não encontrada.")

    atividade.concluida_em = (
        None if atividade.concluida_em is not None else datetime.now(timezone.utc)
    )
    db.commit()
    db.refresh(atividade)
    return _serializar(atividade, {})


@router.delete("/atividades/{atividade_id}")
def excluir_atividade(
    atividade_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    atividade = db.get(Atividade, atividade_id)
    if atividade is None:
        raise HTTPException(404, "Atividade não encontrada.")
    db.delete(atividade)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Checklist
# ---------------------------------------------------------------------------


class ItemEntrada(BaseModel):
    texto: str = Field(min_length=1, max_length=300)


@router.post("/atividades/{atividade_id}/itens", response_model=AtividadeOut)
def criar_item(
    atividade_id: int,
    entrada: ItemEntrada,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> AtividadeOut:
    atividade = db.get(Atividade, atividade_id)
    if atividade is None:
        raise HTTPException(404, "Atividade não encontrada.")
    ultimo = (
        db.query(AtividadeItem.ordem)
        .filter(AtividadeItem.atividade_id == atividade.id)
        .order_by(AtividadeItem.ordem.desc()).first()
    )
    db.add(AtividadeItem(
        atividade_id=atividade.id,
        texto=entrada.texto.strip(),
        ordem=(ultimo[0] + 1) if ultimo else 0,
    ))
    db.commit()
    db.refresh(atividade)
    return _serializar(atividade, {})


@router.post("/itens/{item_id}/alternar", response_model=AtividadeOut)
def alternar_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> AtividadeOut:
    item = db.get(AtividadeItem, item_id)
    if item is None:
        raise HTTPException(404, "Item não encontrado.")
    item.feito = not item.feito
    db.commit()
    atividade = db.get(Atividade, item.atividade_id)
    db.refresh(atividade)
    return _serializar(atividade, {})


@router.delete("/itens/{item_id}")
def excluir_item(
    item_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    item = db.get(AtividadeItem, item_id)
    if item is None:
        raise HTTPException(404, "Item não encontrado.")
    db.delete(item)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Responsáveis — só administrador
# ---------------------------------------------------------------------------


class ResponsaveisEntrada(BaseModel):
    usuario_ids: list[int] = Field(default_factory=list)


@router.post("/atividades/{atividade_id}/responsaveis", response_model=AtividadeOut)
def definir_responsaveis(
    atividade_id: int,
    entrada: ResponsaveisEntrada,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> AtividadeOut:
    """Substitui a lista de responsáveis da atividade.

    **Só administrador.** É o que separa "eu organizo minhas tarefas" de
    "eu distribuo tarefas para os outros".

    Recebe a lista completa em vez de adicionar um por vez: a tela marca e
    desmarca várias pessoas, e mandar o conjunto evita requisição por clique.
    """
    atividade = db.get(Atividade, atividade_id)
    if atividade is None:
        raise HTTPException(404, "Atividade não encontrada.")

    validos = {
        u.id for u in db.query(Usuario.id)
        .filter(Usuario.id.in_(entrada.usuario_ids), Usuario.deleted_at.is_(None))
        .all()
    } if entrada.usuario_ids else set()

    db.query(AtividadeResponsavel).filter(
        AtividadeResponsavel.atividade_id == atividade.id
    ).delete(synchronize_session=False)

    for usuario_id in validos:
        db.add(AtividadeResponsavel(atividade_id=atividade.id, usuario_id=usuario_id))

    db.commit()
    db.refresh(atividade)
    return _serializar(atividade, {})
