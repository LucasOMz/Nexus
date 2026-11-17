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
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import require_module, require_write
from app.core.planta import exigir_planta, planta_ativa
from app.database import get_db
from app.models.core import Ativo, Planta, Usuario
from app.models.enums import Dominio
from app.models.mapa import MapaProjeto

router = APIRouter(prefix="/mapas", tags=["mapa 3d"])

# Mesma pasta das fotos do sistema.
PASTA = "mapas"
EXTENSOES = {".png", ".jpg", ".jpeg", ".webp"}
MAX_BYTES = 12 * 1024 * 1024


def _pasta_abs() -> Path:
    base = Path(cfg_media())
    p = base / PASTA
    p.mkdir(parents=True, exist_ok=True)
    return p


def cfg_media() -> str:
    return settings.media_dir


def _projeto(db: Session, planta_id: int) -> MapaProjeto:
    """O projeto da planta, criando um vazio na primeira visita."""
    p = db.query(MapaProjeto).filter(MapaProjeto.planta_id == planta_id).first()
    if p is None:
        p = MapaProjeto(planta_id=planta_id, escala_metros_por_pixel=0.02)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


def _serializar(p: MapaProjeto) -> dict:
    paredes = []
    if p.paredes:
        try:
            paredes = json.loads(p.paredes)
        except Exception:
            paredes = []
    return {
        "planta_id": p.planta_id,
        "imagem": p.imagem,
        "largura_px": p.largura_px,
        "altura_px": p.altura_px,
        "escala_metros_por_pixel": p.escala_metros_por_pixel,
        "paredes": paredes,
        "observacoes": p.observacoes,
    }


class ProjetoEntrada(BaseModel):
    escala_metros_por_pixel: float | None = Field(default=None, gt=0, le=5)
    largura_px: int | None = Field(default=None, ge=1, le=20000)
    altura_px: int | None = Field(default=None, ge=1, le=20000)
    paredes: list[dict] | None = None
    observacoes: str | None = Field(default=None, max_length=2000)


class PosicaoEntrada(BaseModel):
    x: float = Field(ge=-500, le=500)
    z: float = Field(ge=-500, le=500)
    rotacao: float = Field(default=0, ge=-360, le=360)


@router.get("/{planta_id}")
def ler_projeto(
    planta_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_module("ativos")),
    planta: int | None = Depends(planta_ativa),
) -> dict:
    """O projeto da planta. `planta` é a planta ativa do usuário."""
    exigir_planta(planta, planta_id)
    if db.get(Planta, planta_id) is None:
        raise HTTPException(404, "Planta não encontrada.")
    return _serializar(_projeto(db, planta_id))


@router.put("/{planta_id}", dependencies=[Depends(require_write)])
def salvar_projeto(
    planta_id: int,
    dados: ProjetoEntrada,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_module("ativos")),
    planta: int | None = Depends(planta_ativa),
) -> dict:
    """Grava escala, dimensões e paredes. A imagem tem rota própria."""
    exigir_planta(planta, planta_id)
    p = _projeto(db, planta_id)

    if dados.escala_metros_por_pixel is not None:
        p.escala_metros_por_pixel = dados.escala_metros_por_pixel
    if dados.largura_px is not None:
        p.largura_px = dados.largura_px
    if dados.altura_px is not None:
        p.altura_px = dados.altura_px
    if dados.paredes is not None:
        p.paredes = json.dumps(dados.paredes[:400])
    if dados.observacoes is not None:
        p.observacoes = dados.observacoes

    db.commit()
    db.refresh(p)
    return _serializar(p)


@router.post("/{planta_id}/imagem", dependencies=[Depends(require_write)])
def enviar_imagem(
    planta_id: int,
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_module("ativos")),
    planta: int | None = Depends(planta_ativa),
) -> dict:
    """Sobe a planta baixa (PDF convertido, PNG ou JPG).

    **Só imagem.** PDF precisa ser convertido antes — o navegador não desenha
    PDF numa textura, e converter aqui exigiria uma dependência de sistema
    (Poppler) só para isso.
    """
    exigir_planta(planta, planta_id)

    ext = os.path.splitext(arquivo.filename or "")[1].lower()
    if ext not in EXTENSOES:
        raise HTTPException(
            422,
            "Envie a planta como PNG ou JPG. "
            "Para PDF, converta a página em imagem antes.",
        )

    conteudo = arquivo.file.read()
    if len(conteudo) > MAX_BYTES:
        raise HTTPException(413, "Imagem acima de 12 MB.")

    pasta = _pasta_abs()
    nome = f"{uuid.uuid4().hex}{ext}"
    (pasta / nome).write_bytes(conteudo)

    p = _projeto(db, planta_id)

    # Apaga a anterior — senão a pasta cresce a cada troca de planta.
    if p.imagem:
        antigo = pasta / Path(p.imagem).name
        if antigo.exists():
            antigo.unlink(missing_ok=True)

    p.imagem = f"{PASTA}/{nome}"
    db.commit()
    db.refresh(p)
    return _serializar(p)


@router.get("/{planta_id}/imagem")
def ler_imagem(
    planta_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_module("ativos")),
    planta: int | None = Depends(planta_ativa),
):
    """Serve o desenho. Fica atrás de login: a planta baixa é informação."""
    exigir_planta(planta, planta_id)
    p = db.query(MapaProjeto).filter(MapaProjeto.planta_id == planta_id).first()
    if p is None or not p.imagem:
        raise HTTPException(404, "Esta planta ainda não tem planta baixa.")

    caminho = Path(cfg_media()) / p.imagem
    if not caminho.exists():
        raise HTTPException(404, "Arquivo da planta baixa não encontrado.")
    return FileResponse(caminho)


@router.get("/{planta_id}/ativos")
def ativos_do_mapa(
    planta_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_module("ativos")),
    planta: int | None = Depends(planta_ativa),
) -> dict:
    """Ativos da planta, com e sem posição.

    Devolve **as duas listas**: os posicionados (para desenhar) e os
    pendentes (para arrastar). Sem a segunda, um ativo novo nunca chegaria ao
    mapa — e ninguém notaria.
    """
    exigir_planta(planta, planta_id)

    consulta = (
        db.query(Ativo)
        .filter(
            Ativo.planta_id == planta_id,
            Ativo.deleted_at.is_(None),
            Ativo.dominio.in_([Dominio.TI, Dominio.IMPRESSORA]),
        )
        .order_by(Ativo.dominio, Ativo.patrimonio)
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
            "hostname": a.ti.hostname if a.ti else None,
            "ip": a.ti.ip if a.ti else None,
            "impressora_ip": a.impressora.ip if a.impressora else None,
            "modelo_impressora": a.impressora.modelo if a.impressora else None,
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
    _: Usuario = Depends(require_module("ativos")),
) -> dict:
    """Move um ativo no mapa."""
    a = db.get(Ativo, ativo_id)
    if a is None or a.deleted_at is not None:
        raise HTTPException(404, "Ativo não encontrado.")

    a.mapa_x = dados.x
    a.mapa_z = dados.z
    a.mapa_rotacao = dados.rotacao
    db.commit()
    return {"ok": True, "ativo_id": ativo_id, "x": a.mapa_x, "z": a.mapa_z}


@router.delete("/ativos/{ativo_id}/posicao", dependencies=[Depends(require_write)])
def remover_do_mapa(
    ativo_id: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_module("ativos")),
) -> dict:
    a = db.get(Ativo, ativo_id)
    if a is None or a.deleted_at is not None:
        raise HTTPException(404, "Ativo não encontrado.")

    a.mapa_x = None
    a.mapa_z = None
    a.mapa_rotacao = None
    db.commit()
    return {"ok": True}
