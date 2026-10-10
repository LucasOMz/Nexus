"""Certificado de descarte — emissão e conferência.

## O que este router faz

Emite o **certificado** que acompanha a baixa de um ativo, e permite conferir
depois se o documento apresentado corresponde ao que o sistema registrou.

## Por que existe

Dar baixa num ativo sem registro do destino é o buraco por onde o patrimônio
some. O certificado fecha isso: diz **o quê**, **por quê**, **para onde foi** e
**quem autorizou** — e carrega um selo que denuncia alteração posterior.

## O que o selo protege, e o que não

`conferir` recalcula o hash e compara. Isso pega **edição do conteúdo** depois
de emitido. Não pega quem reemite o documento inteiro com outro conteúdo — para
isso seria preciso guardar o selo fora do banco, como na auditoria imutável.
Vale dizer isso com clareza em vez de prometer mais do que entrega.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_write
from app.database import get_db
from app.models.core import Ativo, Usuario
from app.services import descarte_service as servico
from app.services.audit_service import audit

log = logging.getLogger(__name__)

router = APIRouter(prefix="/descarte", tags=["descarte"])


class DescarteIn(BaseModel):
    """Dados do certificado.

    `extra="forbid"` para erro de digitação não virar campo ignorado em
    silêncio — e os campos do destinador são os que `descarte_service.MOTIVOS`
    exige, com os mesmos nomes. Inventar nomes próprios aqui faria a validação
    acusar pendência de um campo que a tela nem sabe que existe.
    """

    model_config = ConfigDict(extra="forbid")

    ativo_id: int
    motivo: str

    # --- Destinatário ------------------------------------------------------
    # Quem recebe o material. Obrigatório conforme o motivo.
    destinador_nome: str | None = None
    # Documento genérico (CPF/CNPJ) da doação e da venda.
    destinador_documento: str | None = None
    # Sucata exige os dois separados: CNPJ e a licença ambiental do receptor.
    destinador_cnpj: str | None = None
    destinador_licenca: str | None = None

    # --- Papel ------------------------------------------------------------
    # Nota fiscal de saída (venda) ou documento de devolução.
    documento_fiscal: str | None = None
    # Perda é sinistro: o que fica registrado é o número da ocorrência.
    numero_ocorrencia: str | None = None

    # --- Do bem -----------------------------------------------------------
    # `quantidade` e `responsavel` são exigidos pelo serviço; o formulário
    # normalmente usa 1 e o usuário logado.
    quantidade: int = Field(default=1, ge=1)
    responsavel: str | None = None

    valor: float | None = Field(default=None, ge=0)
    observacoes: str | None = None
    logistica_reversa: bool | None = None


@router.get("/motivos", response_model=dict)
def motivos(_: Usuario = Depends(get_current_user)) -> dict:
    """Os motivos aceitos, com o que cada um exige e o fundamento legal.

    A tela monta o formulário a partir daqui: pedir "valor" só na venda, e
    "logística reversa" só quando a categoria exige.
    """
    return {
        "motivos": [
            {"valor": chave, **dados}
            for chave, dados in servico.MOTIVOS.items()
        ]
    }


@router.post("", response_model=dict)
def emitir(
    body: DescarteIn,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    _: Usuario = Depends(require_write),
) -> dict:
    """Monta e valida o certificado de descarte de um ativo."""
    ativo = (
        db.query(Ativo)
        .filter(Ativo.id == body.ativo_id, Ativo.deleted_at.is_(None))
        .first()
    )
    if ativo is None:
        raise HTTPException(404, "Ativo não encontrado.")

    dados = body.model_dump()

    # Completa o que o serviço precisa e o formulário não tem como saber.
    categoria = getattr(getattr(ativo, "categoria", None), "nome", None)
    dados["patrimonio"] = ativo.patrimonio
    dados["categoria"] = categoria
    dados["dominio"] = getattr(ativo.dominio, "value", ativo.dominio)
    # Quem assina é quem está operando, salvo se a tela mandar outro nome.
    if not dados.get("responsavel"):
        dados["responsavel"] = getattr(user, "nome", None) or getattr(user, "email", None)
    if dados.get("logistica_reversa") is None:
        # Detectado pela categoria — o operador não precisa saber de cor
        # quais resíduos exigem logística reversa (PNRS).
        dados["logistica_reversa"] = servico.precisa_logistica_reversa(categoria)

    # `validar` devolve os problemas encontrados; não lança. Assim a tela
    # recebe TODOS de uma vez, em vez de um por tentativa.
    checagem = servico.validar(dados)
    if not checagem.get("ok", True):
        raise HTTPException(
            400,
            {
                "detail": "Faltam dados para este motivo de descarte.",
                "pendencias": checagem.get("pendencias"),
                "mensagens": checagem.get("mensagens"),
                "fundamento": checagem.get("fundamento"),
            },
        )

    conteudo = servico.montar(dados, agora=datetime.now(timezone.utc))

    audit(db, user, "certificado_descarte", "ativo", ativo.id,
          diff={"motivo": body.motivo, "destinador": body.destinador_nome,
                "numero": conteudo.get("numero")})
    db.commit()

    return {
        "certificado": conteudo,
        "conferido": servico.conferir(conteudo),
        "texto": servico.texto(conteudo),
        "resumo": servico.resumo(conteudo),
    }


@router.post("/conferir", response_model=dict)
def conferir(
    body: dict,
    _: Usuario = Depends(get_current_user),
) -> dict:
    """Confere um certificado apresentado.

    Recalcula o selo e compara com o que está no documento. Se alguém editou
    o conteúdo depois de emitido, o selo não bate.
    """
    if not body:
        raise HTTPException(400, "Envie o certificado a conferir.")

    integro = servico.conferir(body)
    return {
        "integro": integro,
        "mensagem": (
            "O certificado confere com o selo — não foi alterado desde a emissão."
            if integro else
            "O SELO NÃO CONFERE. O conteúdo foi alterado depois de emitido, "
            "ou o documento não foi gerado por este sistema."
        ),
        "resumo": servico.resumo(body),
        "numero": body.get("numero"),
    }
