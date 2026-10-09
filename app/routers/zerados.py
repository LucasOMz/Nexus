"""Etiquetas QR em branco (sem ativo) — Administração da Leitura.

Permite gerar lotes de etiquetas "zeradas", imprimir, baixar em PDF e
acompanhar quais já foram vinculadas a um ativo.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_module, require_write
from app.database import get_db
from app.models.core import Ativo, QRZerado, TemplateEtiqueta, Usuario
from app.models.enums import Dominio
from app.services import zerado_service
from app.services.audit_service import audit
from app.services.config_service import obter_template_padrao
from app.services.label_layout import montar_layout, normalizar_config
from app.services.print_service import pdf_de_layouts, send_print_job
from app.services.qr_service import qr_png_data_url

router = APIRouter(prefix="/zerados", tags=["qr-zerado"], dependencies=[Depends(require_module("scanner"))])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class GerarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantidade: int = Field(default=10, ge=1, le=zerado_service.LIMITE_POR_LEVA)
    dominio: Dominio | None = None


class ZeradoOut(BaseModel):
    id: int
    codigo: str
    payload: str
    lote: str
    status: str
    dominio: str | None = None
    ativo_id: int | None = None
    ativo_patrimonio: str | None = None
    criado_em: datetime
    usado_em: datetime | None = None


class LoteZeradoOut(BaseModel):
    lote: str
    total: int
    livres: int
    usados: int
    criado_em: str | None = None
    dominio: str | None = None


class ImprimirRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lote: str | None = None
    ids: list[int] | None = None
    # Quantas etiquetas LIVRES do lote imprimir (None = todas as livres).
    quantidade: int | None = Field(default=None, ge=1, le=zerado_service.LIMITE_POR_LEVA)
    dispositivo_id: int | None = None


def _serializar(db: Session, etiqueta: QRZerado) -> ZeradoOut:
    patrimonio = None
    if etiqueta.ativo_id:
        ativo = db.get(Ativo, etiqueta.ativo_id)
        patrimonio = ativo.patrimonio if ativo is not None else None
    return ZeradoOut(
        id=etiqueta.id,
        codigo=etiqueta.codigo,
        payload=etiqueta.payload,
        lote=etiqueta.lote,
        status=etiqueta.status,
        dominio=etiqueta.dominio,
        ativo_id=etiqueta.ativo_id,
        ativo_patrimonio=patrimonio,
        criado_em=etiqueta.created_at,
        usado_em=etiqueta.usado_em,
    )


def _selecionar(db: Session, body: ImprimirRequest) -> list[QRZerado]:
    """Resolve QUAIS etiquetas imprimir, na ordem de geração."""
    if body.ids:
        itens = (
            db.query(QRZerado)
            .filter(QRZerado.id.in_(body.ids))
            .order_by(QRZerado.id)
            .all()
        )
    elif body.lote:
        consulta = db.query(QRZerado).filter(QRZerado.lote == body.lote)
        if body.quantidade:
            consulta = consulta.filter(QRZerado.status == zerado_service.STATUS_LIVRE)
        itens = consulta.order_by(QRZerado.id).limit(body.quantidade or zerado_service.LIMITE_POR_LEVA).all()
    else:
        raise HTTPException(400, "Informe o lote ou a lista de etiquetas.")

    if not itens:
        raise HTTPException(404, "Nenhuma etiqueta encontrada para imprimir.")
    return itens


def _layout(db: Session, etiqueta: QRZerado, template: TemplateEtiqueta | None) -> dict:
    """Geometria da etiqueta em branco (mesmo motor das etiquetas de ativo)."""
    cfg = dict(getattr(template, "config", None) or {})
    cfg["largura_mm"] = float(getattr(template, "largura_mm", 100) or 100)
    cfg["altura_mm"] = float(getattr(template, "altura_mm", 50) or 50)
    cfg["dpi"] = int(getattr(template, "dpi", 203) or 203)
    return montar_layout(normalizar_config(cfg), zerado_service.dados_para_etiqueta(etiqueta))


def _template(db: Session, template_id: int | None) -> TemplateEtiqueta | None:
    if template_id:
        tpl = db.get(TemplateEtiqueta, template_id)
        if tpl is not None and tpl.deleted_at is None:
            return tpl
    return obter_template_padrao(db)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("", status_code=201)
def gerar(
    body: GerarRequest, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
) -> dict:
    """Gera um lote de etiquetas em branco (sem ativo vinculado)."""
    try:
        lote, itens = zerado_service.gerar(db, body.quantidade, body.dominio.value if body.dominio else None)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    audit(db, user, "gerar_zerados", "qr_zerado", None,
          ip=request.client.host if request.client else None,
          diff={"lote": lote, "quantidade": len(itens), "dominio": body.dominio.value if body.dominio else None})
    db.commit()
    return {
        "lote": lote,
        "quantidade": len(itens),
        "itens": [{"id": i.id, "codigo": i.codigo, "payload": i.payload} for i in itens],
    }


@router.get("")
def listar(
    status: str | None = Query(default=None, pattern="^(livre|usado)$"),
    lote: str | None = None,
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
) -> dict:
    """Lista as etiquetas em branco, com filtro por status/lote."""
    consulta = db.query(QRZerado)
    if status:
        consulta = consulta.filter(QRZerado.status == status)
    if lote:
        consulta = consulta.filter(QRZerado.lote == lote)

    total = consulta.count()
    itens = (
        consulta.order_by(QRZerado.id.desc())
        .offset((pagina - 1) * por_pagina)
        .limit(por_pagina)
        .all()
    )
    livres = db.query(QRZerado).filter(QRZerado.status == zerado_service.STATUS_LIVRE).count()
    return {
        "total": total,
        "livres": livres,
        "itens": [_serializar(db, i) for i in itens],
    }


@router.get("/lotes", response_model=list[LoteZeradoOut])
def listar_lotes(db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)) -> list[dict]:
    """Resumo por leva (quantas livres e quantas já usadas)."""
    return zerado_service.resumo_por_lote(db)


@router.get("/{zerado_id}/qrcode")
def qrcode_da_etiqueta(
    zerado_id: int, db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)
) -> dict:
    """Imagem do QR de uma etiqueta (para exibir na tela)."""
    etiqueta = db.get(QRZerado, zerado_id)
    if etiqueta is None:
        raise HTTPException(404, "Etiqueta em branco não encontrada")
    return {"codigo": etiqueta.codigo, "qr_data_url": qr_png_data_url(etiqueta.payload, box_size=4)}


@router.get("/etiquetas.pdf")
def etiquetas_pdf(
    lote: str | None = None,
    ids: str | None = None,
    quantidade: int | None = Query(default=None, ge=1, le=zerado_service.LIMITE_POR_LEVA),
    template_id: int | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_write),
) -> Response:
    """PDF das etiquetas em branco, no tamanho exato — para imprimir em qualquer impressora."""
    lista_ids = [int(v) for v in ids.split(",") if v.strip().isdigit()] if ids else None
    itens = _selecionar(db, ImprimirRequest(lote=lote, ids=lista_ids, quantidade=quantidade))
    template = _template(db, template_id)

    layouts = [_layout(db, etiqueta, template) for etiqueta in itens]
    pdf = pdf_de_layouts(layouts, titulo="Etiquetas em branco")

    nome = f"etiquetas_branco_{lote or 'selecao'}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome}"'},
    )


@router.post("/imprimir")
def imprimir(
    body: ImprimirRequest, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
) -> dict:
    """Imprime as etiquetas em branco na impressora cadastrada.

    As etiquetas vão em **um único trabalho** (ZPL/TSPL concatenados), então uma
    leva de 100 etiquetas não vira 100 requisições ao agente.
    """
    from app.routers.print import _resolver_dispositivo, _template_do_dispositivo

    dispositivo = _resolver_dispositivo(db, body.dispositivo_id, Dominio.TI)
    if dispositivo is None:
        raise HTTPException(400, "Cadastre um dispositivo de impressão antes de imprimir.")

    itens = _selecionar(db, body)
    template = _template_do_dispositivo(db, dispositivo)
    layouts = [_layout(db, etiqueta, template) for etiqueta in itens]

    resposta = send_print_job(
        layouts=layouts,
        formato=dispositivo.formato,
        copies=1,
        dispositivo=dispositivo,
    )

    # Marca como impressas (para saber o que já saiu da impressora).
    if resposta.get("status") != "error":
        agora = datetime.now(timezone.utc)
        for etiqueta in itens:
            etiqueta.impresso_em = agora
        db.flush()

    audit(db, user, "imprimir_zerados", "qr_zerado", None,
          ip=request.client.host if request.client else None,
          diff={"lote": body.lote, "quantidade": len(itens), "status": resposta.get("status")})
    db.commit()

    return {
        "quantidade": len(itens),
        "status": resposta.get("status"),
        "detail": resposta.get("detail") or resposta.get("message"),
        "job_id": resposta.get("job_id"),
    }


@router.delete("/{zerado_id}", status_code=204)
def excluir(
    zerado_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_write)
):
    """Remove uma etiqueta em branco que ainda não foi usada."""
    etiqueta = db.get(QRZerado, zerado_id)
    if etiqueta is None:
        raise HTTPException(404, "Etiqueta em branco não encontrada")
    if etiqueta.status == zerado_service.STATUS_USADO:
        raise HTTPException(409, "Esta etiqueta já está vinculada a um ativo e não pode ser excluída.")
    audit(db, user, "delete", "qr_zerado", etiqueta.id, ip=request.client.host if request.client else None)
    db.delete(etiqueta)
    db.commit()
