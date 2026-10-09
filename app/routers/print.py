"""Impressão de etiquetas (individual, em massa, pré-visualização e teste).

O destino é um **Dispositivo de Impressão** cadastrado pelo administrador
(ex.: hostname `RTAT0001`, compartilhamento `\\\\RTAT0001\\sip`). Cada dispositivo
pode ter o seu **template de etiqueta**; sem template próprio, usa o padrão.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session, selectinload

from app.core.deps import require_write
from app.core.planta import aplicar_filtro, planta_ativa
from app.database import get_db
from app.models.core import Ativo, DispositivoImpressao, TemplateEtiqueta, Usuario
from app.models.enums import Dominio
from app.schemas.print import PrintBatchRequest, PrintJobItem, PrintRequest, PrintResponse
from app.services.audit_service import audit
from app.services.config_service import obter_template_padrao
from app.services.print_service import (
    dados_do_ativo,
    gerar_bytes,
    montar_label,
    montar_label_de_dados,
    pdf_de_layouts,
    preview_base64,
    send_print_job,
)
from app.services.qr_service import build_payload

router = APIRouter(prefix="/print", tags=["print"])


class PreviewRequest(BaseModel):
    """Pré-visualização: usa um ativo existente como amostra."""

    model_config = ConfigDict(extra="forbid")

    ativo_id: int | None = None
    template_id: int | None = None
    config: dict[str, Any] | None = None
    formato: str = "zpl"


def _nome_arquivo(ativo: Ativo) -> str:
    return f"etiqueta_{ativo.patrimonio}".replace("/", "-").replace("\\", "-")


def _resolver_dispositivo(
    db: Session, dispositivo_id: Optional[int], dominio: Dominio, planta_id: int | None = None
) -> Optional[DispositivoImpressao]:
    """Escolhe a impressora: id informado → padrão da planta → padrão do domínio.

    Com `planta_id` definido, só considera impressoras daquela planta — é o que
    garante que cada planta imprima na SUA impressora.
    """
    if dispositivo_id is not None:
        disp = db.get(DispositivoImpressao, dispositivo_id)
        if disp is None or disp.deleted_at is not None:
            raise HTTPException(404, "Dispositivo de impressão não encontrado")
        if planta_id is not None and disp.planta_id != planta_id:
            raise HTTPException(
                400, "Esta impressora pertence a outra planta. Selecione a impressora da sua planta."
            )
        return disp

    def _com_filtro(extra=None):
        q = db.query(DispositivoImpressao).filter(
            DispositivoImpressao.deleted_at.is_(None),
            DispositivoImpressao.ativo.is_(True),
            DispositivoImpressao.padrao.is_(True),
        )
        q = aplicar_filtro(q, DispositivoImpressao, planta_id)
        if extra is not None:
            q = q.filter(extra)
        return q.first()

    padrao = _com_filtro((DispositivoImpressao.dominio.is_(None)) | (DispositivoImpressao.dominio == dominio))
    if padrao is None:
        # Sem padrão marcado: usa a primeira ativa da planta.
        padrao = (
            aplicar_filtro(
                db.query(DispositivoImpressao).filter(
                    DispositivoImpressao.deleted_at.is_(None), DispositivoImpressao.ativo.is_(True)
                ),
                DispositivoImpressao,
                planta_id,
            )
            .order_by(DispositivoImpressao.id)
            .first()
        )
    return padrao


def _template_do_dispositivo(db: Session, dispositivo: Optional[DispositivoImpressao]) -> Optional[TemplateEtiqueta]:
    """Template do dispositivo; se não tiver, o padrão do sistema."""
    if dispositivo is not None and dispositivo.template_id:
        tpl = db.get(TemplateEtiqueta, dispositivo.template_id)
        if tpl is not None and tpl.deleted_at is None:
            return tpl
    return obter_template_padrao(db)


def _garantir_payload(db: Session, ativo: Ativo) -> None:
    if not ativo.qr_payload:
        ativo.qr_payload = build_payload(ativo.id)
        db.flush()


def _print_ativo(
    db: Session,
    ativo: Ativo,
    formato: str,
    printer: Optional[str],
    copies: int,
    dispositivo: Optional[DispositivoImpressao],
    template: Optional[TemplateEtiqueta],
) -> PrintJobItem:
    """Gera a etiqueta pelo template e envia ao destino."""
    _garantir_payload(db, ativo)
    layout = montar_label(template, ativo)
    resp = send_print_job(
        layout=layout,
        formato=formato,
        printer=printer or "",
        copies=copies,
        dispositivo=dispositivo,
    )
    status = "error" if resp.get("status") == "error" else "ok"
    return PrintJobItem(
        ativo_id=ativo.id,
        job_id=resp.get("job_id"),
        status=status,
        detail=resp.get("detail") or resp.get("message"),
        retryable=bool(resp.get("retryable", False)),
    )


@router.get("/dispositivos")
def dispositivos_disponiveis(
    dominio: Dominio | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa),
) -> list[dict]:
    """Impressoras ativas da planta do usuário, para o seletor de impressão."""
    q = db.query(DispositivoImpressao).filter(
        DispositivoImpressao.deleted_at.is_(None), DispositivoImpressao.ativo.is_(True)
    )
    q = aplicar_filtro(q, DispositivoImpressao, planta_id)
    if dominio is not None:
        q = q.filter((DispositivoImpressao.dominio.is_(None)) | (DispositivoImpressao.dominio == dominio))
    return [
        {"id": d.id, "nome": d.nome, "tipo": d.tipo, "padrao": d.padrao, "formato": d.formato,
         "planta_sigla": d.planta_sigla}
        for d in q.order_by(DispositivoImpressao.nome).all()
    ]


@router.post("/preview")
def preview(
    body: PreviewRequest,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_write),
) -> dict:
    """Pré-visualização: devolve a geometria (para desenhar) e o PDF/etiqueta.

    A geometria é a MESMA usada na impressão — por isso o que aparece na tela
    corresponde ao que sai na impressora, inclusive os avisos de texto que não cabe.
    """
    ativo: Ativo | None = None
    if body.ativo_id is not None:
        ativo = (
            db.query(Ativo)
            .options(selectinload(Ativo.ti), selectinload(Ativo.impressora))
            .filter(Ativo.id == body.ativo_id, Ativo.deleted_at.is_(None))
            .first()
        )
        if ativo is None:
            raise HTTPException(404, "Ativo não encontrado")
        _garantir_payload(db, ativo)

    if body.config is not None:
        dados = dados_do_ativo(ativo) if ativo is not None else _dados_exemplo()
        layout = montar_label_de_dados(body.config, dados)
    else:
        template = db.get(TemplateEtiqueta, body.template_id) if body.template_id else obter_template_padrao(db)
        if template is None and ativo is None:
            raise HTTPException(400, "Cadastre um template de etiqueta ou informe uma configuração.")
        layout = montar_label(template, ativo) if ativo is not None else montar_label(template, _AtivoExemplo())

    formato = (body.formato or "zpl").lower()
    # Enriquece os QR com a imagem, para a pré-visualização desenhar o código real.
    from app.services.qr_service import qr_png_data_url

    for el in layout["elementos"]:
        if el["tipo"] == "qr":
            el["qr_data_url"] = qr_png_data_url(el["payload"], box_size=4, ecc=el.get("ecc", "M"))

    resultado: dict[str, Any] = {"layout": layout, "formato": formato}
    try:
        resultado["conteudo_base64"] = preview_base64(formato, layout)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return resultado


@router.post("/preview/pdf")
def preview_pdf(
    body: PreviewRequest,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_write),
) -> Response:
    """Gera o PDF da etiqueta (para visualizar ou imprimir em outra impressora)."""
    dados = _dados_exemplo()
    if body.ativo_id is not None:
        ativo = (
            db.query(Ativo)
            .options(selectinload(Ativo.ti), selectinload(Ativo.impressora))
            .filter(Ativo.id == body.ativo_id, Ativo.deleted_at.is_(None))
            .first()
        )
        if ativo is None:
            raise HTTPException(404, "Ativo não encontrado")
        _garantir_payload(db, ativo)
        dados = dados_do_ativo(ativo)

    if body.config is not None:
        layout = montar_label_de_dados(body.config, dados)
        nome = "etiqueta_preview"
    else:
        template = db.get(TemplateEtiqueta, body.template_id) if body.template_id else obter_template_padrao(db)
        if template is None:
            raise HTTPException(400, "Nenhum template de etiqueta cadastrado.")
        layout = montar_label_de_dados(
            {
                **(template.config or {}),
                "largura_mm": float(template.largura_mm),
                "altura_mm": float(template.altura_mm),
                "dpi": int(template.dpi),
            },
            dados,
        )
        nome = template.nome

    pdf = gerar_bytes("pdf", layout)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome}.pdf"'},
    )


@router.get("/etiqueta/{ativo_id}.pdf")
def etiqueta_pdf(
    ativo_id: int,
    template_id: int | None = None,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_write),
) -> Response:
    """PDF da etiqueta de um ativo — para imprimir manualmente em outra impressora."""
    ativo = (
        db.query(Ativo)
        .options(selectinload(Ativo.ti), selectinload(Ativo.impressora))
        .filter(Ativo.id == ativo_id, Ativo.deleted_at.is_(None))
        .first()
    )
    if ativo is None:
        raise HTTPException(404, "Ativo não encontrado")
    _garantir_payload(db, ativo)
    template = db.get(TemplateEtiqueta, template_id) if template_id else obter_template_padrao(db)
    layout = montar_label(template, ativo)
    db.commit()
    pdf = gerar_bytes("pdf", layout)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{_nome_arquivo(ativo)}.pdf"'},
    )


@router.get("/etiquetas.pdf")
def etiquetas_pdf(
    ids: str | None = None,
    dominio: Dominio = Dominio.TI,
    template_id: int | None = None,
    limite: int = 100,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_write),
) -> Response:
    """PDF com várias etiquetas (uma por página) — impressão manual.

    Aceita `ids` (lista separada por vírgula, na ordem da tela) ou, sem eles,
    todos os ativos do inventário indicado em `dominio`.
    """
    consulta = db.query(Ativo).options(selectinload(Ativo.ti), selectinload(Ativo.impressora))

    if ids:
        lista_ids = [int(v) for v in ids.split(",") if v.strip().isdigit()]
        if not lista_ids:
            raise HTTPException(400, "Nenhum ativo válido informado.")
        ativos = consulta.filter(Ativo.id.in_(lista_ids), Ativo.deleted_at.is_(None)).all()
        # Mantém a ordem em que os ativos vieram da tela.
        por_id = {a.id: a for a in ativos}
        ativos = [por_id[i] for i in lista_ids if i in por_id]
    else:
        ativos = (
            consulta.filter(Ativo.deleted_at.is_(None), Ativo.dominio == dominio)
            .order_by(Ativo.patrimonio)
            .limit(max(1, min(limite, 500)))
            .all()
        )

    if not ativos:
        raise HTTPException(404, "Nenhum ativo encontrado para gerar as etiquetas.")

    template = db.get(TemplateEtiqueta, template_id) if template_id else obter_template_padrao(db)

    layouts = []
    for ativo in ativos:
        _garantir_payload(db, ativo)
        layouts.append(montar_label(template, ativo))
    db.commit()

    pdf = pdf_de_layouts(layouts, titulo="Etiquetas")
    nome = "etiquetas.pdf" if len(ativos) > 1 else f"etiqueta_{_nome_arquivo(ativos[0])}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome}"'},
    )


@router.post("/teste")
def imprimir_teste(
    request: Request,
    dispositivo_id: int | None = None,
    template_id: int | None = None,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa),
) -> PrintResponse:
    """Imprime uma etiqueta de TESTE (dados fictícios) no dispositivo escolhido."""
    dispositivo = _resolver_dispositivo(db, dispositivo_id, Dominio.TI, planta_id)
    if dispositivo is None:
        raise HTTPException(400, "Cadastre um dispositivo de impressão antes de testar.")
    template = db.get(TemplateEtiqueta, template_id) if template_id else _template_do_dispositivo(db, dispositivo)
    layout = montar_label(template, _AtivoExemplo())
    resp = send_print_job(
        layout=layout,
        formato=dispositivo.formato,
        copies=1,
        dispositivo=dispositivo,
    )
    audit(db, user, "print_teste", "dispositivo_impressao", dispositivo.id,
          ip=request.client.host if request.client else None, diff={"status": resp.get("status")})
    db.commit()
    status = "error" if resp.get("status") == "error" else "ok"
    return PrintResponse(total=1, jobs=[PrintJobItem(
        ativo_id=0, job_id=resp.get("job_id"), status=status,
        detail=resp.get("detail") or resp.get("message"), retryable=bool(resp.get("retryable", False)),
    )])


# ---------------------------------------------------------------------------
# Amostra para pré-visualização / teste (não toca no banco)
# ---------------------------------------------------------------------------
class _AtivoExemplo:
    """Ativo fictício usado na pré-visualização e no teste de impressão.

    O texto de exemplo tem **acentos de propósito** ("Recepção", "3º", "nº"):
    é assim que se confere, sem gastar etiqueta de verdade, se a impressora
    está entendendo UTF-8 — antes os acentos saíam como caracteres estranhos.
    """

    id = 0
    patrimonio = "TESTE-0001"
    numero_serie = "SN-EXEMPLO-0001"
    modelo = "Impressão térmica nº 1"
    marca = "Recepção — 3º andar"
    status = "estoque"
    dominio = "ti"
    valor = None
    data_garantia = None
    qr_payload = "TIATIVO:0:1700000000:EXEMPLO"
    categoria = None
    localizacao = None
    departamento = None
    ti = None
    impressora = None


def _dados_exemplo() -> dict[str, str]:
    return dados_do_ativo(_AtivoExemplo())


@router.post("", response_model=PrintResponse)
def print_one(
    body: PrintRequest, request: Request, db: Session = Depends(get_db),
    user: Usuario = Depends(require_write), planta_id: int | None = Depends(planta_ativa),
):
    ativo = db.get(Ativo, body.ativo_id)
    if ativo is None or ativo.deleted_at is not None:
        raise HTTPException(404, "Ativo não encontrado")
    dispositivo = _resolver_dispositivo(db, body.dispositivo_id, ativo.dominio, planta_id)
    template = _template_do_dispositivo(db, dispositivo)
    job = _print_ativo(db, ativo, body.formato, body.printer, body.copies, dispositivo, template)
    audit(db, user, "print", "ativo", ativo.id,
          ip=request.client.host if request.client else None, diff=body.model_dump())
    db.commit()
    return PrintResponse(total=1, jobs=[job])


@router.post("/batch", response_model=PrintResponse)
def print_batch(
    body: PrintBatchRequest, request: Request, db: Session = Depends(get_db),
    user: Usuario = Depends(require_write), planta_id: int | None = Depends(planta_ativa),
):
    """Impressão em massa: uma etiqueta por ativo da seleção."""
    ativos = db.query(Ativo).filter(Ativo.id.in_(body.ativo_ids), Ativo.deleted_at.is_(None)).all()
    if not ativos:
        raise HTTPException(404, "Nenhum ativo encontrado")
    dispositivo = _resolver_dispositivo(db, body.dispositivo_id, ativos[0].dominio, planta_id)
    template = _template_do_dispositivo(db, dispositivo)
    jobs = [_print_ativo(db, a, body.formato, body.printer, body.copies, dispositivo, template) for a in ativos]
    audit(
        db, user, "print_batch", "ativos", None,
        ip=request.client.host if request.client else None,
        diff={"ids": body.ativo_ids, "dispositivo": dispositivo.id if dispositivo else None},
    )
    db.commit()
    return PrintResponse(total=len(jobs), jobs=jobs)
