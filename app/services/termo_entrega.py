"""Aceite eletrônico, confirmação do equipamento e comprovante."""
import hashlib
import hmac
import json
from datetime import date, datetime, timedelta, timezone
from secrets import choice, token_urlsafe

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models.core import Ativo, Termo
from app.models.termo_entrega import EntregaTermo, ModeloTermoEntrega
from app.schemas.termo_entrega import AceiteEntrega
from app.services import pdf_termo_entrega
from app.services.audit_service import audit


def agora():
    return datetime.now(timezone.utc)


def utc(valor):
    return valor.replace(tzinfo=timezone.utc) if valor and valor.tzinfo is None else valor


def hash_codigo(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


def modelo_atual(db: Session):
    return db.scalar(select(ModeloTermoEntrega).order_by(ModeloTermoEntrega.id.desc()).limit(1))


def ultimo_termo(db: Session, ativo_id: int):
    return db.scalar(select(Termo).where(
        Termo.ativo_id == ativo_id, Termo.entrega_elegivel.is_(True), Termo.deleted_at.is_(None),
    ).order_by(Termo.id.desc()).limit(1))


def registrar_envio(db: Session, termo: Termo, modelo, pessoa, user, ip: str | None):
    # A escrita na linha do termo também serializa envios concorrentes em SQLite.
    db.execute(update(Termo).where(Termo.id == termo.id).values(entrega_elegivel=True))
    anterior = db.scalar(select(EntregaTermo).where(EntregaTermo.termo_id == termo.id)
                         .order_by(EntregaTermo.id.desc()).limit(1))
    if anterior and (anterior.estado == "assinado" or (
        anterior.estado in {"enviado", "aguardando_agente"} and utc(anterior.expira_em) > agora()
    ) or (anterior.estado == "enviando" and utc(anterior.created_at) + timedelta(minutes=2) > agora())):
        raise HTTPException(409, "A entrega já foi concluída ou tem um convite em andamento.")
    codigo = token_urlsafe(32)
    entrega = EntregaTermo(
        termo_id=termo.id, modelo_id=modelo.id, criado_por=user.id, destinatario=str(pessoa.email),
        login_ad=pessoa.login, colaborador=pessoa.nome, estado="enviando", convite_hash=hash_codigo(codigo),
        expira_em=agora() + timedelta(hours=modelo.prazo_horas),
    )
    db.add(entrega)
    db.flush()
    audit(db, user, "enviar_termo_entrega", "ativo", termo.ativo_id, ip=ip, diff={"entrega_id": entrega.id})
    db.commit()
    return entrega, codigo


def situacao(db: Session, entrega: EntregaTermo) -> str:
    if entrega.estado in {"assinado", "falha_envio"}:
        return entrega.estado
    termo = db.get(Termo, entrega.termo_id)
    ativo = db.get(Ativo, termo.ativo_id) if termo else None
    recente = ultimo_termo(db, ativo.id) if ativo and ativo.deleted_at is None else None
    if not recente or recente.id != entrega.termo_id:
        return "substituido"
    if utc(entrega.expira_em) <= agora():
        return "expirado"
    if entrega.estado == "aguardando_agente" and utc(entrega.desafio_expira_em) <= agora():
        return "codigo_expirado"
    return entrega.estado


def carregar_convite(db: Session, codigo: str) -> EntregaTermo:
    if not (30 <= len(codigo) <= 80):
        raise HTTPException(404, "Convite inválido.")
    entrega = db.scalar(select(EntregaTermo).where(EntregaTermo.convite_hash == hash_codigo(codigo)))
    if entrega is None:
        raise HTTPException(404, "Convite inválido.")
    return entrega


def bloquear_entrega(db: Session, entrega: EntregaTermo) -> None:
    db.execute(update(EntregaTermo).where(EntregaTermo.id == entrega.id).values(estado=EntregaTermo.estado)
               .execution_options(synchronize_session=False))
    db.refresh(entrega)


def exigir_sessao(entrega: EntregaTermo, sessao: str) -> None:
    if (not sessao or not entrega.sessao_hash or not hmac.compare_digest(entrega.sessao_hash, hash_codigo(sessao))
            or utc(entrega.sessao_expira_em) <= agora()):
        raise HTTPException(401, "Confirme sua identidade novamente pelo AD.")


def conferir_respostas(entrega: EntregaTermo, aceite: AceiteEntrega, ativo: Ativo):
    campos = {}
    imagem = pdf_termo_entrega.normalizar_png(aceite.assinatura_png)
    for campo in entrega.modelo.campos:
        tipo, chave = campo["tipo"], campo["id"]
        valor = aceite.campos.get(chave)
        if tipo in {"nome", "assinatura"}:
            valor = entrega.colaborador
        elif tipo == "patrimonio":
            valor = ativo.patrimonio or ativo.numero_serie
        elif tipo == "leitura":
            valor = valor is True
        elif isinstance(valor, str):
            valor = valor.strip()
            if len(valor) > 200 or any(ord(c) < 32 for c in valor):
                raise HTTPException(422, "Use até 200 caracteres por campo.")
            if tipo == "data" and valor:
                try:
                    valor = date.fromisoformat(valor).strftime("%d/%m/%Y")
                except ValueError:
                    raise HTTPException(422, "Informe uma data válida.") from None
        else:
            valor = ""
        if campo["obrigatorio"] and not valor:
            raise HTTPException(422, f'Preencha o campo “{campo["rotulo"]}”.')
        campos[chave] = valor
    return {"campos": campos, "fonte": aceite.fonte}, imagem


def preparar_desafio(entrega: EntregaTermo) -> str:
    codigo = "".join(choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
    entrega.estado = "aguardando_agente"
    entrega.desafio_hash = hash_codigo(codigo)
    entrega.desafio_expira_em = min(agora() + timedelta(minutes=15), utc(entrega.expira_em))
    return codigo


def _json(dados: dict) -> bytes:
    return json.dumps(dados, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def concluir(db: Session, entrega: EntregaTermo, ativo: Ativo, ip: str | None, prova: dict | None = None) -> None:
    aceite = {
        "termo_id": entrega.termo_id, "entrega_id": entrega.id, "versao_modelo": entrega.modelo_id,
        "identidade": entrega.login_ad, "destinatario": entrega.destinatario, "colaborador": entrega.colaborador,
        "equipamento": ativo.patrimonio or ativo.numero_serie, "ativo_id": ativo.id,
        "aceite_em": utc(entrega.aceite_em).isoformat(timespec="seconds"), "respostas": entrega.respostas,
        "pdf_original": hashlib.sha256(entrega.modelo.pdf).hexdigest(),
        "imagem_assinatura": hashlib.sha256(entrega.imagem_assinatura).hexdigest() if entrega.imagem_assinatura else None,
    }
    comprovante = {
        "termo_id": entrega.termo_id, "entrega_id": entrega.id, "versao_modelo": entrega.modelo_id,
        "colaborador": entrega.colaborador, "login_ad": entrega.login_ad, "destinatario": entrega.destinatario,
        "equipamento": aceite["equipamento"], "aceite_em": aceite["aceite_em"],
        "hash_aceite": hashlib.sha256(_json(aceite)).hexdigest(), "agente": prova,
        "confirmacao_agente": (f'{prova["usuario_windows"]} · {prova["hora"]}' if prova else
                               "Sem confirmação pelo agente. Aceite validado pelo AD."),
    }
    comprovante["selo"] = hmac.new(settings.jwt_secret.encode(), b"nexus.termo-entrega.v1:" + _json(comprovante),
                                   hashlib.sha256).hexdigest()
    entrega.pdf_assinado = pdf_termo_entrega.gerar_pdf(entrega.modelo, entrega.respostas, entrega.imagem_assinatura, comprovante)
    comprovante["hash_pdf"] = hashlib.sha256(entrega.pdf_assinado).hexdigest()
    entrega.comprovante = comprovante
    entrega.estado = "assinado"
    entrega.assinado_em = agora()
    entrega.sessao_hash = entrega.desafio_hash = None
    entrega.imagem_assinatura = None
    audit(db, None, "assinar_termo_entrega", "ativo", ativo.id, ip=ip,
          diff={"entrega_id": entrega.id, "hash_pdf": comprovante["hash_pdf"], "confirmado_pelo_agente": bool(prova)})
    db.commit()
