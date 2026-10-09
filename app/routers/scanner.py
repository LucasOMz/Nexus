"""Scanner / leitura de ativos.

Feito para LEITOR FÍSICO de QR Code (que digita o código como teclado) e para
digitação manual do identificador. NÃO usa câmera.

Fluxo:
  1. O leitor digita o payload assinado (`TIATIVO:...`) + Enter, OU o usuário
     digita o patrimônio / nº de série / id.
  2. `POST /scanner/buscar` resolve o ativo e devolve um resumo com as ações.

Existe ainda o caso das **etiquetas em branco** (`TIZERADO:...`): geradas sem
ativo, para colar no equipamento e cadastrar depois. Ao ler uma delas, a
resposta vem com `tipo="zerado"` e a tela abre o cadastro já vinculado.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user, require_module
from app.core.permissoes import pode_acao
from app.core.rate_limit import scan_limiter
from app.database import get_db
from app.models.core import Ativo, Usuario
from app.models.ti import AtivoTI
from app.services import zerado_service
from app.services.audit_service import audit
from app.services.qr_service import (
    extrair_codigo_zerado,
    resolver_codigo,
    validar_assinatura_zerado,
)

router = APIRouter(prefix="/scanner", tags=["scanner"], dependencies=[Depends(require_module("scanner"))])


class BuscarRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigo: str = Field(min_length=1, max_length=500)


class AtivoResumo(BaseModel):
    id: int
    patrimonio: str
    modelo: str | None = None
    marca: str | None = None
    dominio: str
    status: str
    numero_serie: str | None = None
    foto_id: int | None = None
    contador_paginas: int | None = None
    origem: str  # qr | qr_sem_assinatura | qr_zerado | id | patrimonio | serie
    # None = não veio de payload QR. True/False = assinatura conferida ou não.
    assinatura_valida: bool | None = None
    pode_escrever: bool = False


class ZeradoResumo(BaseModel):
    """Etiqueta em branco AINDA sem ativo — a tela abre o cadastro."""

    id: int
    codigo: str
    payload: str
    lote: str
    assinatura_valida: bool = True
    pode_escrever: bool = False


class LeituraOut(BaseModel):
    """`tipo="ativo"` → achou um ativo. `tipo="zerado"` → etiqueta em branco livre."""

    tipo: str
    ativo: AtivoResumo | None = None
    zerado: ZeradoResumo | None = None


def _resumo_ativo(ativo: Ativo, origem: str, assinatura: bool | None, user: Usuario) -> AtivoResumo:
    return AtivoResumo(
        id=ativo.id,
        patrimonio=ativo.patrimonio,
        modelo=ativo.modelo,
        marca=ativo.marca,
        dominio=ativo.dominio.value,
        status=ativo.status.value,
        numero_serie=ativo.numero_serie,
        foto_id=ativo.foto_id,
        contador_paginas=ativo.impressora.contador_paginas if ativo.impressora else None,
        origem=origem,
        assinatura_valida=assinatura,
        pode_escrever=pode_acao(user, "pode_escrever"),
    )


@router.post("/buscar", response_model=LeituraOut)
def buscar(
    body: BuscarRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> LeituraOut:
    """Resolve o que foi lido: ativo (QR, id, patrimônio, série) ou etiqueta em branco.

    O ID dentro do payload sempre resolve o ativo (etiquetas já impressas
    continuam válidas). A assinatura é conferida em separado e, quando
    `QR_EXIGIR_ASSINATURA=false`, não bloqueia a leitura — mas fica auditada.
    """
    if not scan_limiter.is_allowed(str(user.id)):
        raise HTTPException(429, "Muitas leituras. Aguarde um instante.")

    codigo = body.codigo.strip()
    ip = request.client.host if request.client else None

    # ------------------------------------------------------------------
    # 0) Etiqueta EM BRANCO (gerada sem ativo).
    #
    # Aceita as DUAS formas, porque a etiqueta imprime o QR e também o código
    # em letras grandes (para digitação quando o leitor falha):
    #   * payload completo → TIZERADO:8S7CW9F2XM:1700:assinatura
    #   * só o código      → 8S7CW9F2XM
    # ------------------------------------------------------------------
    codigo_zerado = extrair_codigo_zerado(codigo)
    etiqueta = None
    if codigo_zerado:
        etiqueta = zerado_service.localizar(db, codigo_zerado)
        if etiqueta is None:
            raise HTTPException(
                404,
                "Etiqueta em branco não reconhecida por este sistema. "
                "Confira se ela foi gerada aqui (e se o QR_HMAC_SECRET não mudou).",
            )
    elif ":" not in codigo:
        # Não parece um payload nosso: pode ser o código curto da etiqueta.
        etiqueta = zerado_service.localizar(db, codigo)

    if etiqueta is not None:
        # Sem payload não há assinatura a conferir — o código curto só existe
        # se a etiqueta foi gerada aqui (a tabela é a fonte da verdade).
        assinatura_ok = validar_assinatura_zerado(codigo) if codigo_zerado else True
        if codigo_zerado and not assinatura_ok:
            from app.config import settings

            if settings.qr_exigir_assinatura:
                raise HTTPException(400, "A assinatura desta etiqueta em branco não confere.")
            audit(db, user, "scan", "qr_zerado", etiqueta.id, ip=ip,
                  diff={"origem": "zerado_sem_assinatura", "codigo": etiqueta.codigo})

        # Já vinculada: comporta-se como qualquer etiqueta de ativo.
        if etiqueta.ativo_id:
            ativo = (
                db.query(Ativo)
                .options(selectinload(Ativo.impressora))
                .filter(Ativo.id == etiqueta.ativo_id, Ativo.deleted_at.is_(None))
                .first()
            )
            if ativo is None:
                raise HTTPException(
                    404,
                    f"A etiqueta {etiqueta.codigo} aponta para um ativo que foi excluído. "
                    "Gere uma nova etiqueta para este equipamento.",
                )
            audit(db, user, "scan", "ativo", ativo.id, ip=ip,
                  diff={"origem": "qr_zerado", "assinatura_valida": assinatura_ok})
            db.commit()
            return LeituraOut(tipo="ativo", ativo=_resumo_ativo(ativo, "qr_zerado", assinatura_ok, user))

        # Livre: devolve os dados para a tela abrir o cadastro.
        return LeituraOut(
            tipo="zerado",
            zerado=ZeradoResumo(
                id=etiqueta.id,
                codigo=etiqueta.codigo,
                payload=etiqueta.payload,
                lote=etiqueta.lote,
                assinatura_valida=assinatura_ok,
                pode_escrever=pode_acao(user, "pode_escrever"),
            ),
        )

    # ------------------------------------------------------------------
    # Fluxo normal (ativo já existente).
    # ------------------------------------------------------------------
    ativo = None
    origem = ""
    assinatura_valida: bool | None = None

    # 1) Payload QR (ID extraído do próprio código).
    ativo_id, assinatura_ok = resolver_codigo(codigo)
    if ativo_id is not None:
        ativo = db.get(Ativo, ativo_id)
        assinatura_valida = assinatura_ok
        origem = "qr" if assinatura_ok else "qr_sem_assinatura"
    # 2) Id numérico.
    elif codigo.isdigit():
        ativo = db.get(Ativo, int(codigo))
        origem = "id"
    # 3) Patrimônio / nº de série.
    else:
        ativo = (
            db.query(Ativo)
            .options(selectinload(Ativo.impressora))
            .outerjoin(AtivoTI, AtivoTI.ativo_id == Ativo.id)
            .filter(
                Ativo.deleted_at.is_(None),
                or_(
                    Ativo.patrimonio.ilike(codigo),
                    Ativo.numero_serie.ilike(codigo),
                    # O hostname é como a máquina é conhecida na rede: o técnico
                    # digita "DTAT0001" na tela de leitura em vez de procurar a
                    # etiqueta. Sem esta junção, o código não achava nada.
                    AtivoTI.hostname.ilike(codigo),
                ),
            )
            .first()
        )
        origem = "patrimonio"

    if ativo is None or ativo.deleted_at is not None:
        raise HTTPException(404, f"Nenhum ativo encontrado para o código lido: {codigo[:60]}")

    audit(db, user, "scan", "ativo", ativo.id, ip=ip,
          diff={"origem": origem, "assinatura_valida": assinatura_valida})
    db.commit()

    return LeituraOut(tipo="ativo", ativo=_resumo_ativo(ativo, origem, assinatura_valida, user))
