"""Configuração, envio e aceite do termo de entrega."""
from datetime import timedelta
from hashlib import sha256
from hmac import compare_digest, digest
from secrets import token_urlsafe
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.deps import require_admin, require_module, require_write
from app.core.permissoes import pode_inventario
from app.core.planta import planta_ativa_obrigatoria
from app.core.rate_limit import SlidingWindowLimiter, redis_contadores
from app.database import get_db
from app.models.agente import TokenAgente
from app.models.core import Ativo, ConfiguracaoSistema, Termo
from app.models.termo_entrega import EntregaTermo, ModeloTermoEntrega
from app.schemas.termo_entrega import (
    AceiteEntrega, ConfigEntrega, ConfirmacaoAgenteEntrega, ConfirmarEnvioEntrega, IdentidadeEntrega,
)
from app.services import atribuicao_ad, email_service, ldap_service, pdf_termo_entrega, termo_entrega as termos
from app.services.agente_service import buscar_token
from app.services.audit_service import audit

router = APIRouter(tags=["termo de entrega"])
_ADMIN = "/admin/termo-entrega"
_ATIVO = "/ativos/{ativo_id}/termo-entrega"
_PUBLICO = "/termo-entrega"
_LEITURA = require_module("ativos")
_TENTATIVAS = SlidingWindowLimiter(7, 300, redis=redis_contadores, grupo="termo_entrega_ad")
_AGENTE = SlidingWindowLimiter(20, 300, redis=redis_contadores, grupo="termo_entrega_agente")
_PRIVADO = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


def _bearer(request: Request) -> str:
    esquema, _, valor = request.headers.get("Authorization", "").partition(" ")
    return valor if esquema.casefold() == "bearer" else ""


def _ip(request: Request):
    return request.client.host if request.client else None


def _modelo_saida(modelo):
    if modelo is None:
        return None
    return {c: getattr(modelo, c) for c in ("id", "nome", "url_publica", "prazo_horas", "exigir_agente", "campos", "paginas")}


def _pagina(pdf: bytes, paginas: list, pagina: int):
    if not 1 <= pagina <= len(paginas):
        raise HTTPException(404, "Página não encontrada.")
    return Response(pdf_termo_entrega.imagem_pagina(pdf, pagina), media_type="image/png", headers=_PRIVADO)


@router.get(_ADMIN)
def configuracao(db: Session = Depends(get_db), _=Depends(require_admin)):
    return {"modelo": _modelo_saida(termos.modelo_atual(db))}


@router.post(_ADMIN + "/previa")
def previa(pagina: int = 1, arquivo: UploadFile = File(...), _=Depends(require_admin)):
    pdf = arquivo.file.read(pdf_termo_entrega.LIMITE_PDF + 1)
    medidas = pdf_termo_entrega.dimensoes_pdf(pdf)
    res = _pagina(pdf, medidas, pagina)
    res.headers["X-Total-Paginas"] = str(len(medidas))
    return res


@router.get(_ADMIN + "/pagina/{pagina}")
def pagina_modelo(pagina: int, db: Session = Depends(get_db), _=Depends(require_admin)):
    modelo = termos.modelo_atual(db)
    if not modelo:
        raise HTTPException(404, "Cadastre o PDF do termo.")
    return _pagina(modelo.pdf, modelo.paginas, pagina)


@router.put(_ADMIN)
def salvar_modelo(
    request: Request, configuracao: Annotated[str, Form()], arquivo: UploadFile | None = File(None),
    modelo_base: Annotated[int | None, Form()] = None,
    db: Session = Depends(get_db), user=Depends(require_admin),
):
    try:
        cfg = ConfigEntrega.model_validate_json(configuracao)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False, include_input=False)[0]["msg"]) from None
    anterior = termos.modelo_atual(db)
    if modelo_base is not None and modelo_base != (anterior.id if anterior else 0):
        raise HTTPException(409, "O modelo foi atualizado em outra sessão. Abra o editor novamente.")
    pdf = arquivo.file.read(pdf_termo_entrega.LIMITE_PDF + 1) if arquivo else anterior.pdf if anterior else b""
    medidas = pdf_termo_entrega.dimensoes_pdf(pdf)
    if any(c.pagina > len(medidas) for c in cfg.campos):
        raise HTTPException(422, "Há campos posicionados em páginas que não existem neste PDF.")
    modelo = ModeloTermoEntrega(**cfg.model_dump(mode="json"), pdf=pdf, paginas=medidas)
    db.add(modelo)
    db.flush()
    audit(db, user, "update", "modelo_termo_entrega", modelo.id, ip=_ip(request))
    db.commit()
    return _modelo_saida(modelo)


def _ativo(db: Session, ativo_id: int, planta_id, user):
    ativo = db.get(Ativo, ativo_id)
    if (ativo is None or ativo.deleted_at is not None or (planta_id is not None and ativo.planta_id != planta_id)
            or not pode_inventario(user, ativo.dominio.value)):
        raise HTTPException(404, "Ativo não encontrado.")
    return ativo


def _envio(db: Session, ativo_id: int):
    termo = termos.ultimo_termo(db, ativo_id)
    modelo = termos.modelo_atual(db)
    if not modelo or not termo or not termo.usuario or not termo.usuario.login_ad:
        raise HTTPException(409, "Configure o termo e atribua o ativo a um colaborador com login no AD.")
    pronto, motivo = email_service.pronto(db)
    if not pronto:
        raise HTTPException(409, motivo)
    # A busca usa a conta de serviço configurada. O operador confirma o
    # e-mail que veio do AD, sem digitar um destinatário diferente.
    pessoa = atribuicao_ad.buscar_colaborador(db, termo.usuario.login_ad)
    return termo, modelo, pessoa


def _entrega_saida(db: Session, entrega: EntregaTermo):
    respostas = None
    if entrega.assinado_em and entrega.respostas:
        valores = entrega.respostas["campos"]
        respostas = [{"rotulo": c["rotulo"], "pagina": c["pagina"], "valor": valores.get(c["id"])}
                     for c in entrega.modelo.campos if c["tipo"] != "assinatura"]
    return {"id": entrega.id, "termo_id": entrega.termo_id, "estado": termos.situacao(db, entrega),
            "destinatario": entrega.destinatario, "expira_em": termos.utc(entrega.expira_em),
            "assinado_em": termos.utc(entrega.assinado_em), "comprovante": entrega.comprovante,
            "respostas": respostas}


@router.get(_ATIVO)
def acompanhar(
    ativo_id: int, db: Session = Depends(get_db), user=Depends(_LEITURA), planta_id=Depends(planta_ativa_obrigatoria),
):
    _ativo(db, ativo_id, planta_id, user)
    termo = termos.ultimo_termo(db, ativo_id)
    entregas = db.scalars(select(EntregaTermo).join(Termo).where(Termo.ativo_id == ativo_id)
                          .order_by(EntregaTermo.id.desc()).limit(50)).all()
    return {"termo_atual": termo.id if termo else None, "entregas": [_entrega_saida(db, e) for e in entregas]}


@router.post(_ATIVO + "/{termo_id}/preparar")
def preparar(
    ativo_id: int, termo_id: int, db: Session = Depends(get_db), user=Depends(require_write), _=Depends(_LEITURA),
    planta_id=Depends(planta_ativa_obrigatoria),
):
    _ativo(db, ativo_id, planta_id, user)
    termo, modelo, pessoa = _envio(db, ativo_id)
    if termo.id != termo_id:
        raise HTTPException(409, "A atribuição mudou. Abra novamente a ficha.")
    return {"colaborador": pessoa.nome, "email": pessoa.email, "prazo_horas": modelo.prazo_horas}


@router.post(_ATIVO + "/{termo_id}/enviar", status_code=201)
def enviar(
    ativo_id: int, termo_id: int, body: ConfirmarEnvioEntrega, request: Request, db: Session = Depends(get_db),
    user=Depends(require_write), _=Depends(_LEITURA), planta_id=Depends(planta_ativa_obrigatoria),
):
    ativo = _ativo(db, ativo_id, planta_id, user)
    termo, modelo, pessoa = _envio(db, ativo_id)
    if termo.id != termo_id or pessoa.email.casefold() != body.email.casefold():
        raise HTTPException(409, "O e-mail ou a atribuição mudou. Confira os dados novamente.")
    if modelo.exigir_agente and not _agente_atual(db, ativo.id):
        raise HTTPException(409, "O modelo exige confirmação pelo agente. Vincule o agente ao equipamento antes de enviar.")
    entrega, codigo = termos.registrar_envio(db, termo, modelo, pessoa, user, _ip(request))
    link = f"{modelo.url_publica}/termo-entrega.html#{codigo}"
    try:
        email_service.enviar(db, pessoa.email, "Termo de entrega de equipamento",
                            f"Olá, {pessoa.nome}.\n\nAcesse o Nexus para ler e assinar seu termo de entrega. "
                            f"O link fica válido por {modelo.prazo_horas} hora(s).\n\n{link}\n")
    except (email_service.FalhaEnvio, email_service.SMTPNaoConfigurado):
        entrega.estado = "falha_envio"
        db.commit()
        raise HTTPException(502, "O SMTP não confirmou o envio do termo. Confira a configuração e tente novamente.") from None
    entrega.estado = "enviado"
    db.commit()
    return _entrega_saida(db, entrega)


@router.get(_ATIVO + "/{entrega_id}/pdf")
def pdf_assinado(
    ativo_id: int, entrega_id: int, db: Session = Depends(get_db), user=Depends(_LEITURA),
    planta_id=Depends(planta_ativa_obrigatoria),
):
    _ativo(db, ativo_id, planta_id, user)
    entrega = db.scalar(select(EntregaTermo).join(Termo).where(EntregaTermo.id == entrega_id,
                       Termo.ativo_id == ativo_id, EntregaTermo.estado == "assinado"))
    if not entrega or not entrega.pdf_assinado:
        raise HTTPException(404, "Termo assinado não encontrado.")
    if sha256(entrega.pdf_assinado).hexdigest() != entrega.comprovante["hash_pdf"]:
        raise HTTPException(409, "A integridade do arquivo não confere com o comprovante.")
    return Response(entrega.pdf_assinado, media_type="application/pdf",
                    headers={**_PRIVADO, "Content-Disposition": f'attachment; filename="termo-entrega-{entrega.id}.pdf"'})


def _agente_atual(db, ativo_id):
    return db.scalar(select(TokenAgente.id).where(TokenAgente.ativo_id == ativo_id, TokenAgente.revogado_em.is_(None),
                     TokenAgente.deleted_at.is_(None)).limit(1))


def _estado_publico(db, entrega):
    return {"estado": termos.situacao(db, entrega), "assinado_em": termos.utc(entrega.assinado_em)}


@router.get(_PUBLICO + "/estado")
def estado_publico(request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers.update(_PRIVADO)
    return _estado_publico(db, termos.carregar_convite(db, _bearer(request)))


def _exigir_aberto(db, entrega):
    if termos.situacao(db, entrega) not in {"enviado", "aguardando_agente", "codigo_expirado"}:
        raise HTTPException(409, "O convite não está disponível para preenchimento.")


@router.post(_PUBLICO + "/autenticar")
def autenticar(body: IdentidadeEntrega, request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers.update(_PRIVADO)
    entrega = termos.carregar_convite(db, _bearer(request))
    _exigir_aberto(db, entrega)
    if settings.env.casefold() == "production" and request.headers.get("Origin") != entrega.modelo.url_publica:
        raise HTTPException(403, "Abra o termo pelo endereço HTTPS informado no e-mail.")
    if not _TENTATIVAS.is_allowed(str(entrega.id)):
        raise HTTPException(429, "Aguarde alguns minutos antes de tentar novamente.")
    cfg = db.get(ConfiguracaoSistema, 1)
    login = entrega.login_ad
    if not atribuicao_ad.ad_disponivel(cfg):
        raise HTTPException(503, "O AD está indisponível. Procure a TI.")
    if body.login.strip().casefold() != login.casefold():
        raise HTTPException(401, "Não foi possível confirmar sua identidade.")
    db.expunge(cfg)
    db.rollback()
    verificado = ldap_service.autenticar(cfg, login, body.senha)
    if (not verificado.ok or not verificado.login or verificado.login.casefold() != login.casefold()
            or not verificado.email or verificado.email.casefold() != entrega.destinatario.casefold()):
        raise HTTPException(401, "Não foi possível confirmar sua identidade.")
    termos.bloquear_entrega(db, entrega)
    _exigir_aberto(db, entrega)
    sessao = token_urlsafe(32)
    entrega.sessao_hash = termos.hash_codigo(sessao)
    entrega.sessao_expira_em = min(termos.agora() + timedelta(minutes=45), termos.utc(entrega.expira_em))
    ativo = db.get(Ativo, db.get(Termo, entrega.termo_id).ativo_id)
    dados = {"sessao": sessao, "colaborador": entrega.colaborador, "equipamento": ativo.patrimonio or ativo.numero_serie,
             "campos": entrega.modelo.campos, "paginas": len(entrega.modelo.paginas),
             "exigir_agente": entrega.modelo.exigir_agente, "agente_vinculado": bool(_agente_atual(db, ativo.id))}
    db.commit()
    return dados


@router.get(_PUBLICO + "/pagina/{pagina}")
def pagina_publica(pagina: int, request: Request, db: Session = Depends(get_db)):
    entrega = termos.carregar_convite(db, _bearer(request))
    _exigir_aberto(db, entrega)
    termos.exigir_sessao(entrega, request.headers.get("X-Termo-Sessao", ""))
    return _pagina(entrega.modelo.pdf, entrega.modelo.paginas, pagina)


@router.post(_PUBLICO + "/assinar")
def assinar(body: AceiteEntrega, request: Request, response: Response, db: Session = Depends(get_db)):
    response.headers.update(_PRIVADO)
    entrega = termos.carregar_convite(db, _bearer(request))
    termos.bloquear_entrega(db, entrega)
    _exigir_aberto(db, entrega)
    termos.exigir_sessao(entrega, request.headers.get("X-Termo-Sessao", ""))
    ativo = db.get(Ativo, db.get(Termo, entrega.termo_id).ativo_id)
    entrega.respostas, entrega.imagem_assinatura = termos.conferir_respostas(entrega, body, ativo)
    entrega.aceite_em = termos.agora()
    if entrega.modelo.exigir_agente or body.confirmar_no_agente:
        if not _agente_atual(db, ativo.id):
            raise HTTPException(409, "O agente deste equipamento ainda não está vinculado ao Nexus.")
        codigo = termos.preparar_desafio(entrega)
        db.commit()
        return {"estado": "aguardando_agente", "codigo": codigo}
    termos.concluir(db, entrega, ativo, _ip(request))
    return _estado_publico(db, entrega)


@router.post("/agente/termo-entrega/confirmar")
def confirmar_agente(body: ConfirmacaoAgenteEntrega, request: Request, db: Session = Depends(get_db)):
    token = _bearer(request)
    credencial = buscar_token(db, token)
    if credencial is None or credencial.deleted_at is not None:
        raise HTTPException(401, "Agente não autenticado.")
    if not _AGENTE.is_allowed(str(credencial.id)):
        raise HTTPException(429, "Muitas tentativas. Tente novamente em alguns minutos.")
    mensagem = f"nexus.termo.v1\n{body.codigo}\n{body.usuario_windows}".encode()
    if not compare_digest(digest(token.encode(), mensagem, "sha256").hex(), body.assinatura):
        raise HTTPException(401, "A assinatura do agente não confere.")
    hash_desafio = termos.hash_codigo(body.codigo)
    entrega = db.scalar(select(EntregaTermo).join(Termo).where(
        EntregaTermo.desafio_hash == hash_desafio, Termo.ativo_id == credencial.ativo_id,
    ))
    if not entrega:
        raise HTTPException(404, "O código não pertence a este equipamento ou já foi usado.")
    termos.bloquear_entrega(db, entrega)
    dominio, separador, nome = body.usuario_windows.partition("\\")
    if (entrega.desafio_hash != hash_desafio or termos.situacao(db, entrega) != "aguardando_agente"
            or not separador or not dominio or nome.casefold() != entrega.login_ad.casefold()):
        raise HTTPException(409, "O código venceu ou o usuário do Windows não corresponde ao colaborador.")
    ativo = db.get(Ativo, credencial.ativo_id)
    prova = {"ativo_id": ativo.id, "token_agente_id": credencial.id, "usuario_windows": body.usuario_windows,
             "hora": termos.agora().isoformat(timespec="seconds"), "host": ativo.hostname,
             "assinatura_agente": body.assinatura, "desafio_hash": hash_desafio}
    termos.concluir(db, entrega, ativo, _ip(request), prova)
    return {"ok": True}
