"""Mapa 3D do parque: rotas.

## O que a tela precisa, e nesta ordem

1. **o projeto da planta** — imagem de fundo, escala e paredes
2. **os ativos com posicao** — computadores e impressoras
3. **os ativos sem posicao** — a lista de quem falta arrastar

O passo 3 é fácil de esquecer e é o que faz o mapa ficar incompleto sem
ninguém perceber: a impressora nova existe no inventário, mas não está na
planta, e ninguém vai notar olhando o desenho.

## Escopo por planta

O mapa é de **uma** unidade. Um gestor que enxerga todas as plantas não pode
ver o mapa de outra sem trocar a planta ativa — o desenho é do prédio.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.core.deps import require_module, require_write
from app.core.permissoes import permissoes_efetivas
from app.core.planta import planta_ativa_obrigatoria
from app.core.uploads import MAX_PLANTA, ler_arquivo, validar_imagem
from app.database import get_db
from app.models.core import Ativo, Planta, Usuario
from app.models.mapa import MapaProjeto

router = APIRouter(prefix="/mapas", tags=["mapa 3d"])

# Mesma pasta das fotos do sistema.
PASTA = "mapas"
FORMATOS = ("PNG", "JPEG", "WEBP")


def _pasta_abs() -> Path:
    base = Path(cfg_media())
    p = base / PASTA
    p.mkdir(parents=True, exist_ok=True)
    return p


def cfg_media() -> str:
    return settings.media_dir


def _verificar_planta(db: Session, planta_id: int, planta: int | None, *, bloquear: bool = False) -> None:
    if planta is not None and planta != planta_id:
        raise HTTPException(404, "Planta não encontrada no seu escopo.")
    unidade = db.get(Planta, planta_id, with_for_update=bloquear)
    if unidade is None or unidade.deleted_at is not None:
        raise HTTPException(404, "Planta não encontrada.")


def _projeto(db: Session, planta_id: int) -> MapaProjeto:
    p = db.query(MapaProjeto).filter(MapaProjeto.planta_id == planta_id).first()
    return p or MapaProjeto(planta_id=planta_id, escala_metros_por_pixel=0.02)


def _serializar(p: MapaProjeto) -> dict:
    paredes = []
    if p.paredes:
        try:
            paredes = json.loads(p.paredes)
        except json.JSONDecodeError:
            paredes = []
    return {
        "planta_id": p.planta_id,
        "imagem": p.imagem,
        "largura_px": p.largura_px,
        "altura_px": p.altura_px,
        "escala_metros_por_pixel": p.escala_metros_por_pixel,
        "paredes": paredes if isinstance(paredes, list) else [],
        "observacoes": p.observacoes,
    }


Coordenada = Annotated[float, Field(ge=-500, le=500)]


class ParedeEntrada(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex, max_length=80)
    points: list[tuple[Coordenada, Coordenada]] = Field(min_length=2, max_length=120)
    height: float = Field(default=3, ge=0.1, le=30)
    thickness: float = Field(default=0.16, ge=0.05, le=5)

    @model_validator(mode="before")
    @classmethod
    def aceitar_segmento_legado(cls, dados):
        if isinstance(dados, dict) and all(chave in dados for chave in ("x1", "z1", "x2", "z2")):
            return {
                "points": [(dados["x1"], dados["z1"]), (dados["x2"], dados["z2"])],
                "height": dados.get("altura", 3),
                "thickness": dados.get("espessura", 0.16),
            }
        return dados


class ProjetoEntrada(BaseModel):
    escala_metros_por_pixel: float | None = Field(default=None, gt=0, le=5)
    largura_px: int | None = Field(default=None, ge=1, le=20000)
    altura_px: int | None = Field(default=None, ge=1, le=20000)
    paredes: list[ParedeEntrada] | None = Field(default=None, max_length=400)
    observacoes: str | None = Field(default=None, max_length=2000)


class PosicaoEntrada(BaseModel):
    x: Coordenada
    z: Coordenada
    rotacao: float = Field(default=0, ge=-360, le=360)


class EstadoEntrada(BaseModel):
    projeto: ProjetoEntrada | None = None
    posicoes: dict[int, PosicaoEntrada | None] = Field(default_factory=dict, max_length=5000)


def _atualizar_projeto(p: MapaProjeto, dados: ProjetoEntrada) -> None:
    campos = dados.model_dump(exclude_none=True)
    if "paredes" in campos:
        campos["paredes"] = json.dumps(campos["paredes"])
    for campo, valor in campos.items():
        setattr(p, campo, valor)


def _ativos_autorizados(db: Session, user: Usuario, planta_id: int | None):
    q = db.query(Ativo).filter(
        Ativo.deleted_at.is_(None),
        Ativo.dominio.in_(permissoes_efetivas(user)["inventarios"]),
    )
    if planta_id is not None:
        q = q.filter(Ativo.planta_id == planta_id)
    return q


def _aplicar_posicao(ativo: Ativo, dados: PosicaoEntrada | None) -> None:
    ativo.mapa_x = dados.x if dados else None
    ativo.mapa_z = dados.z if dados else None
    ativo.mapa_rotacao = dados.rotacao if dados else None


@router.get("/{planta_id}")
def ler_projeto(
    planta_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_module("mapa")),
    planta: int | None = Depends(planta_ativa_obrigatoria),
) -> dict:
    """O projeto da planta. `planta` é a planta ativa do usuário."""
    _verificar_planta(db, planta_id, planta)
    return _serializar(_projeto(db, planta_id))


@router.put("/{planta_id}", dependencies=[Depends(require_write)])
def salvar_projeto(
    planta_id: int,
    dados: ProjetoEntrada,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_module("mapa")),
    planta: int | None = Depends(planta_ativa_obrigatoria),
) -> dict:
    """Grava escala, dimensões e paredes. A imagem tem rota própria."""
    _verificar_planta(db, planta_id, planta, bloquear=True)
    p = _projeto(db, planta_id)
    _atualizar_projeto(p, dados)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _serializar(p)


@router.put("/{planta_id}/estado", dependencies=[Depends(require_write)])
def salvar_estado(
    planta_id: int,
    dados: EstadoEntrada,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_module("mapa")),
    planta: int | None = Depends(planta_ativa_obrigatoria),
) -> dict:
    """Grava geometria e posições em uma transação."""
    _verificar_planta(db, planta_id, planta, bloquear=dados.projeto is not None)
    if dados.posicoes:
        ativos = (
            _ativos_autorizados(db, user, planta_id)
            .filter(Ativo.id.in_(dados.posicoes))
            .order_by(Ativo.id)
            .with_for_update(of=Ativo)
            .all()
        )
        if len(ativos) != len(dados.posicoes):
            raise HTTPException(404, "Um dos ativos não está disponível nesta planta.")
        for ativo in ativos:
            _aplicar_posicao(ativo, dados.posicoes[ativo.id])
    if dados.projeto is not None:
        p = _projeto(db, planta_id)
        _atualizar_projeto(p, dados.projeto)
        db.add(p)
    db.commit()
    return {"ok": True}


@router.post("/{planta_id}/imagem", dependencies=[Depends(require_write)])
def enviar_imagem(
    planta_id: int,
    arquivo: UploadFile = File(...),
    largura_metros: float | None = Form(default=None, gt=0, le=1000),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_module("mapa")),
    planta: int | None = Depends(planta_ativa_obrigatoria),
) -> dict:
    _verificar_planta(db, planta_id, planta, bloquear=True)
    conteudo = ler_arquivo(arquivo, MAX_PLANTA)
    formato = validar_imagem(conteudo, formatos=FORMATOS, status_invalido=422)
    largura, altura = formato.largura, formato.altura
    escala = largura_metros / largura if largura_metros is not None else None
    if escala is not None and escala > 5:
        raise HTTPException(422, "A largura real é muito grande para a resolução desta imagem.")

    p = _projeto(db, planta_id)
    imagem_anterior = p.imagem
    destino = _pasta_abs() / f"{uuid.uuid4().hex}{formato.extensao}"
    try:
        destino.write_bytes(conteudo)
        p.imagem = f"{PASTA}/{destino.name}"
        p.largura_px, p.altura_px = largura, altura
        if escala is not None:
            p.escala_metros_por_pixel = escala
        db.add(p)
        db.commit()
    except Exception:
        db.rollback()
        destino.unlink(missing_ok=True)
        raise
    if imagem_anterior:
        _remover_arquivo(imagem_anterior)
    db.refresh(p)
    return _serializar(p)


@router.get("/{planta_id}/imagem")
def ler_imagem(
    planta_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_module("mapa")),
    planta: int | None = Depends(planta_ativa_obrigatoria),
):
    """Serve o desenho. Fica atrás de login: a planta baixa é informação."""
    _verificar_planta(db, planta_id, planta)
    p = db.query(MapaProjeto).filter(MapaProjeto.planta_id == planta_id).first()
    if p is None or not p.imagem:
        raise HTTPException(404, "Esta planta ainda não tem planta baixa.")

    caminho = Path(cfg_media()) / PASTA / Path(p.imagem).name
    if not caminho.is_file():
        raise HTTPException(404, "Arquivo da planta baixa não encontrado.")
    return FileResponse(caminho, headers={"Cache-Control": "private, no-store"})


def _remover_arquivo(imagem: str) -> None:
    try:
        (Path(cfg_media()) / PASTA / Path(imagem).name).unlink(missing_ok=True)
    except OSError:
        # A referência já foi atualizada. Um arquivo órfão pode ser limpo depois.
        pass


@router.delete("/{planta_id}/imagem", dependencies=[Depends(require_write)])
def remover_imagem(
    planta_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_module("mapa")),
    planta: int | None = Depends(planta_ativa_obrigatoria),
) -> dict:
    _verificar_planta(db, planta_id, planta, bloquear=True)
    p = _projeto(db, planta_id)
    if p.imagem:
        nome = p.imagem
        p.imagem = None
        p.largura_px = p.altura_px = None
        db.commit()
        _remover_arquivo(nome)
    return _serializar(p)


@router.get("/{planta_id}/ativos")
def ativos_do_mapa(
    planta_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_module("mapa")),
    planta: int | None = Depends(planta_ativa_obrigatoria),
) -> dict:
    """Ativos da planta, com e sem posição.

    Devolve **as duas listas**: os posicionados (para desenhar) e os
    pendentes (para arrastar). Sem a segunda, um ativo novo nunca chegaria ao
    mapa — e ninguém notaria.
    """
    _verificar_planta(db, planta_id, planta)

    consulta = (
        _ativos_autorizados(db, user, planta_id)
        .options(selectinload(Ativo.departamento), selectinload(Ativo.localizacao),
                 selectinload(Ativo.ti), selectinload(Ativo.impressora))
        .order_by(Ativo.dominio, Ativo.patrimonio, Ativo.id)
    )

    posicionados = []
    pendentes = []

    for a in consulta.all():
        item = {
            "id": a.id,
            "dominio": a.dominio.value if hasattr(a.dominio, "value") else a.dominio,
            "patrimonio": a.patrimonio,
            "numero_serie": a.numero_serie,
            "modelo": a.modelo,
            "marca": a.marca,
            "status": a.status.value if hasattr(a.status, "value") else a.status,
            "departamento": a.departamento.nome if a.departamento else None,
            "localizacao": a.localizacao.nome if a.localizacao else None,
            "hostname": a.ti.hostname if a.ti else (a.impressora.hostname if a.impressora else None),
            "ip": a.ti.ip if a.ti else None,
            "impressora_ip": a.impressora.ip if a.impressora else None,
            # Impressora não tem `modelo` na extensão: o modelo é o campo
            # base do ativo. `driver` e `colorida` existem e podem interessar
            # ao mapa — vão como extras.
            "driver": a.impressora.driver if a.impressora else None,
            "colorida": a.impressora.colorida if a.impressora else None,
        }

        if a.mapa_x is not None and a.mapa_z is not None:
            item["x"] = a.mapa_x
            item["z"] = a.mapa_z
            item["rotacao"] = a.mapa_rotacao or 0
            posicionados.append(item)
        else:
            pendentes.append(item)

    return {"posicionados": posicionados, "pendentes": pendentes}


@router.patch("/ativos/{ativo_id}/posicao", dependencies=[Depends(require_write)])
def posicionar(
    ativo_id: int,
    dados: PosicaoEntrada,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_module("mapa")),
    planta: int | None = Depends(planta_ativa_obrigatoria),
) -> dict:
    """Move um ativo no mapa."""
    a = _ativos_autorizados(db, user, planta).filter(Ativo.id == ativo_id).with_for_update(of=Ativo).first()
    if a is None:
        raise HTTPException(404, "Ativo não encontrado.")

    _aplicar_posicao(a, dados)
    db.commit()
    return {"ok": True, "ativo_id": ativo_id, "x": a.mapa_x, "z": a.mapa_z}


@router.delete("/ativos/{ativo_id}/posicao", dependencies=[Depends(require_write)])
def remover_do_mapa(
    ativo_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_module("mapa")),
    planta: int | None = Depends(planta_ativa_obrigatoria),
) -> dict:
    a = _ativos_autorizados(db, user, planta).filter(Ativo.id == ativo_id).with_for_update(of=Ativo).first()
    if a is None:
        raise HTTPException(404, "Ativo não encontrado.")

    _aplicar_posicao(a, None)
    db.commit()
    return {"ok": True}
