"""Área administrativa: dispositivos de impressão, banco de fotos e utilidades.

Permissões:
  - Leitura do banco de fotos: qualquer usuário autenticado (para escolher a
    foto de um ativo).
  - Criação/edição/exclusão: apenas `admin`.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import get_current_user, get_current_user_query, require_admin
from app.core.permissoes import INVENTARIOS, MODULOS
from app.core.planta import aplicar_filtro, exigir_planta, planta_ativa
from app.database import get_db
from app.models.core import DispositivoImpressao, Imagem, Planta, Usuario
from app.models.enums import Dominio
from app.schemas.admin import (
    DispositivoImpressaoCreate,
    DispositivoImpressaoOut,
    DispositivoImpressaoUpdate,
    ImagemOut,
    ImagemUpdate,
)
from app.services.audit_service import audit

router = APIRouter(prefix="/admin", tags=["admin"])

FOTOS_DIR = os.path.join(settings.media_dir, "fotos")
TIPOS_IMAGEM = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif", "image/svg+xml"}


def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _img_out(img: Imagem) -> ImagemOut:
    out = ImagemOut.model_validate(img)
    out.url = f"/api/v1/admin/fotos/{img.id}/arquivo"
    return out


# ---------------------------------------------------------------------------
# Metadados (alimenta a tela de permissões no frontend)
# ---------------------------------------------------------------------------
@router.get("/metadados")
def metadados(_: Usuario = Depends(require_admin)) -> dict:
    """Lista módulos e inventários disponíveis para montar a tela de permissões."""
    return {
        "modulos": [{"chave": k, "rotulo": v} for k, v in MODULOS.items()],
        "inventarios": [{"chave": k, "rotulo": v} for k, v in INVENTARIOS.items()],
    }


# ---------------------------------------------------------------------------
# Dispositivos de impressão — cada planta tem a SUA impressora
# ---------------------------------------------------------------------------
def require_gestor_impressao(user: Usuario = Depends(get_current_user)) -> Usuario:
    """Administrador **ou** perfil TI podem gerenciar impressoras.

    O técnico de TI cadastra a impressora da planta dele; o administrador
    (que não tem planta) enxerga e gerencia todas.
    """
    papel = getattr(user.papel, "value", user.papel)
    if papel not in ("admin", "ti"):
        raise HTTPException(
            403, "Apenas administradores e o perfil TI podem gerenciar impressoras."
        )
    return user


def _garantir_planta_do_dispositivo(obj: DispositivoImpressao, planta_id: int | None, user: Usuario) -> None:
    """Impede que uma planta altere a impressora de outra."""
    papel = getattr(user.papel, "value", user.papel)
    if papel == "admin":
        return  # administrador transita entre plantas
    if obj.planta_id != planta_id:
        raise HTTPException(
            403,
            "Esta impressora pertence a outra planta. "
            "Você só pode alterar a impressora da sua planta.",
        )


def _planta_alvo(
    db: Session, body_planta_id: int | None, planta_id: int | None, user: Usuario, acao: str
) -> int:
    """Define a planta da impressora.

    * **Administrador** — vale o que ele escolheu no formulário; se não escolheu,
      a planta do seletor do topo; se também não houver, a primeira cadastrada.
      É assim que o admin cadastra impressora para QUALQUER planta.
    * **Perfil TI** — sempre a planta dele; o campo do formulário é ignorado.
    """
    papel = getattr(user.papel, "value", user.papel)
    if papel == "admin" and body_planta_id is not None:
        if db.get(Planta, body_planta_id) is None:
            raise HTTPException(404, f"Planta {body_planta_id} não encontrada.")
        return body_planta_id
    return exigir_planta(db, planta_id, acao)


@router.get("/dispositivos", response_model=list[DispositivoImpressaoOut])
def list_dispositivos(
    dominio: Dominio | None = None,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
):
    """Impressoras visíveis para o usuário (as da planta dele)."""
    q = db.query(DispositivoImpressao).filter(DispositivoImpressao.deleted_at.is_(None))
    q = aplicar_filtro(q, DispositivoImpressao, planta_id)
    if dominio is not None:
        q = q.filter((DispositivoImpressao.dominio.is_(None)) | (DispositivoImpressao.dominio == dominio))
    return q.order_by(DispositivoImpressao.nome).all()


@router.post("/dispositivos", response_model=DispositivoImpressaoOut, status_code=201)
def create_dispositivo(
    body: DispositivoImpressaoCreate,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_gestor_impressao),
    planta_id: int | None = Depends(planta_ativa),
):
    destino = _planta_alvo(db, body.planta_id, planta_id, user, "cadastrar a impressora")
    dados = body.model_dump(exclude={"planta_id"})
    obj = DispositivoImpressao(**dados)
    obj.planta_id = destino
    if obj.padrao:
        # Só uma impressora padrão POR PLANTA.
        db.query(DispositivoImpressao).filter(
            DispositivoImpressao.padrao.is_(True), DispositivoImpressao.planta_id == destino
        ).update({"padrao": False})
    db.add(obj)
    db.flush()
    audit(db, user, "create", "dispositivo_impressao", obj.id, ip=_ip(request),
          diff={**dados, "planta_id": destino})
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/dispositivos/{disp_id}", response_model=DispositivoImpressaoOut)
def update_dispositivo(
    disp_id: int,
    body: DispositivoImpressaoUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_gestor_impressao),
    planta_id: int | None = Depends(planta_ativa),
):
    obj = db.get(DispositivoImpressao, disp_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Dispositivo não encontrado")
    _garantir_planta_do_dispositivo(obj, planta_id, user)

    data = body.model_dump()
    nova_planta = data.pop("planta_id", None)

    if nova_planta is not None and nova_planta != obj.planta_id:
        # Mover de planta é privilégio do administrador.
        papel = getattr(user.papel, "value", user.papel)
        if papel != "admin":
            raise HTTPException(403, "Apenas o administrador pode mover uma impressora de planta.")
        if db.get(Planta, nova_planta) is None:
            raise HTTPException(404, f"Planta {nova_planta} não encontrada.")
        obj.planta_id = nova_planta

    if data.get("padrao"):
        # Padrão é por planta: desmarca só as da mesma planta.
        db.query(DispositivoImpressao).filter(
            DispositivoImpressao.id != disp_id,
            DispositivoImpressao.padrao.is_(True),
            DispositivoImpressao.planta_id == obj.planta_id,
        ).update({"padrao": False})
    for k, v in data.items():
        setattr(obj, k, v)
    audit(db, user, "update", "dispositivo_impressao", obj.id, ip=_ip(request), diff=body.model_dump(mode="json"))
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/dispositivos/{disp_id}", status_code=204)
def delete_dispositivo(
    disp_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_gestor_impressao),
    planta_id: int | None = Depends(planta_ativa),
):
    obj = db.get(DispositivoImpressao, disp_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Dispositivo não encontrado")
    _garantir_planta_do_dispositivo(obj, planta_id, user)
    obj.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "dispositivo_impressao", obj.id, ip=_ip(request))
    db.commit()


# ---------------------------------------------------------------------------
# Banco de fotos
# ---------------------------------------------------------------------------
@router.get("/fotos", response_model=list[ImagemOut])
def list_fotos(
    dominio: Dominio | None = None,
    busca: str | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    q = db.query(Imagem).filter(Imagem.deleted_at.is_(None))
    if dominio is not None:
        q = q.filter((Imagem.dominio.is_(None)) | (Imagem.dominio == dominio))
    if busca:
        like = f"%{busca}%"
        q = q.filter((Imagem.nome.ilike(like)) | (Imagem.tags.ilike(like)))
    return [_img_out(i) for i in q.order_by(Imagem.nome).all()]


@router.post("/fotos", response_model=ImagemOut, status_code=201)
async def upload_foto(
    request: Request,
    file: UploadFile = File(...),
    nome: str = Form(...),
    descricao: str | None = Form(default=None),
    tags: str | None = Form(default=None),
    dominio: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    if file.content_type not in TIPOS_IMAGEM:
        raise HTTPException(400, "Envie um arquivo de imagem (PNG, JPG, WEBP, GIF ou SVG)")

    os.makedirs(FOTOS_DIR, exist_ok=True)
    conteudo = await file.read()
    # O caminho é definido ANTES do INSERT (coluna NOT NULL); o nome leva um
    # prefixo único para evitar colisão entre arquivos de mesmo nome.
    nome_arquivo = f"{uuid.uuid4().hex}_{os.path.basename(file.filename or 'foto')}"
    destino = os.path.join(FOTOS_DIR, nome_arquivo)
    with open(destino, "wb") as fh:
        fh.write(conteudo)

    img = Imagem(
        nome=nome,
        descricao=descricao,
        tags=tags,
        mime_type=file.content_type,
        uploaded_by=user.id,
        caminho=destino,
        tamanho=len(conteudo),
    )
    if dominio:
        img.dominio = Dominio(dominio)
    db.add(img)
    db.flush()

    audit(db, user, "upload", "imagem", img.id, ip=_ip(request), diff={"nome": nome, "arquivo": file.filename})
    db.commit()
    db.refresh(img)
    return _img_out(img)


@router.get("/fotos/{foto_id}/arquivo")
def arquivo_foto(foto_id: int, db: Session = Depends(get_db), _: Usuario = Depends(get_current_user_query)):
    """Serve a imagem. Aceita ?token=<jwt> para uso direto em <img src>."""
    img = db.get(Imagem, foto_id)
    if img is None or img.deleted_at is not None or not os.path.exists(img.caminho):
        raise HTTPException(404, "Imagem não encontrada")
    return FileResponse(img.caminho, media_type=img.mime_type or "image/png")


@router.put("/fotos/{foto_id}", response_model=ImagemOut)
def update_foto(
    foto_id: int,
    body: ImagemUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    img = db.get(Imagem, foto_id)
    if img is None or img.deleted_at is not None:
        raise HTTPException(404, "Imagem não encontrada")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(img, k, v)
    audit(db, user, "update", "imagem", img.id, ip=_ip(request), diff=body.model_dump(exclude_unset=True, mode="json"))
    db.commit()
    db.refresh(img)
    return _img_out(img)


@router.delete("/fotos/{foto_id}", status_code=204)
def delete_foto(
    foto_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
):
    img = db.get(Imagem, foto_id)
    if img is None or img.deleted_at is not None:
        raise HTTPException(404, "Imagem não encontrada")
    img.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "imagem", img.id, ip=_ip(request))
    db.commit()
