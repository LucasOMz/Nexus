"""Etiquetas QR EM BRANCO — gerar, listar e vincular a um ativo.

Fluxo de uso:

1. Na tela de **Leitura**, o operador informa a quantidade e gera as etiquetas.
2. Imprime (impressora térmica ou PDF) e cola no equipamento.
3. Ao ler o código, o sistema abre o **cadastro de ativo** já vinculado àquela
   etiqueta. A partir daí a leitura funciona como qualquer outra.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.core import Ativo, QRZerado
from app.services.qr_service import (
    build_payload_zerado,
    extrair_codigo_zerado,
    gerar_codigo_zerado,
)

# Limite por leva: evita gerar uma quantidade absurda por engano.
LIMITE_POR_LEVA = 1000

STATUS_LIVRE = "livre"
STATUS_USADO = "usado"


def _codigo_unico(db: Session) -> str:
    """Código curto que ainda não existe (10 caracteres, sem ambiguidade)."""
    for _ in range(30):
        codigo = gerar_codigo_zerado()
        if not db.query(QRZerado.id).filter(QRZerado.codigo == codigo).first():
            return codigo
    raise RuntimeError("Não foi possível gerar um código único. Tente novamente.")


def gerar(db: Session, quantidade: int, dominio: str | None = None) -> tuple[str, list[QRZerado]]:
    """Cria `quantidade` etiquetas em branco e devolve `(lote, etiquetas)`."""
    if quantidade < 1:
        raise ValueError("A quantidade precisa ser pelo menos 1.")
    if quantidade > LIMITE_POR_LEVA:
        raise ValueError(f"O limite por leva é {LIMITE_POR_LEVA} etiquetas.")

    lote = f"L{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"
    itens: list[QRZerado] = []
    for _ in range(quantidade):
        codigo = _codigo_unico(db)
        etiqueta = QRZerado(
            codigo=codigo,
            payload=build_payload_zerado(codigo),
            lote=lote,
            dominio=dominio,
            status=STATUS_LIVRE,
        )
        db.add(etiqueta)
        itens.append(etiqueta)
    db.flush()
    return lote, itens


def localizar(db: Session, payload_ou_codigo: str) -> QRZerado | None:
    """Encontra a etiqueta pelo payload completo ou só pelo código."""
    if not payload_ou_codigo:
        return None
    codigo = extrair_codigo_zerado(payload_ou_codigo) or payload_ou_codigo.strip()
    if not codigo:
        return None
    return db.query(QRZerado).filter(QRZerado.codigo == codigo).first()


def vincular(db: Session, payload: str, ativo: Ativo) -> QRZerado:
    """Vincula a etiqueta em branco `payload` ao ativo indicado.

    Levanta `ValueError` com mensagem clara quando a etiqueta não existe ou já
    pertence a outro ativo.
    """
    etiqueta = localizar(db, payload)
    if etiqueta is None:
        raise ValueError(
            "Etiqueta em branco não encontrada. Ela pode ter sido gerada em outro sistema "
            "ou o QR_HMAC_SECRET foi alterado."
        )
    if etiqueta.ativo_id and etiqueta.ativo_id != ativo.id:
        outro = db.get(Ativo, etiqueta.ativo_id)
        dono = outro.patrimonio if outro is not None else f"id {etiqueta.ativo_id}"
        raise ValueError(f"Esta etiqueta em branco já está vinculada ao ativo {dono}.")

    etiqueta.ativo_id = ativo.id
    etiqueta.status = STATUS_USADO
    etiqueta.usado_em = datetime.now(timezone.utc)
    db.flush()
    return etiqueta


def dados_para_etiqueta(etiqueta: QRZerado) -> dict[str, str]:
    """Valores exibidos na etiqueta em branco (o código ocupa o lugar do patrimônio)."""
    return {
        "payload_qr": etiqueta.payload,
        "patrimonio": etiqueta.codigo,
        "codigo": etiqueta.codigo,
        "modelo": "",
        "marca": "",
        "serie": "",
        "categoria": "",
        "status": "",
        "departamento": "",
        "localizacao": "",
        "valor": "",
        "garantia": "",
        "hostname": "",
        "ip": "",
        "mac": "",
        "so": "",
        "ram": "",
        "contador": "",
        "dominio": "",
    }


def resumo_por_lote(db: Session) -> list[dict]:
    """Quantas etiquetas livres/usadas em cada leva."""
    lotes: dict[str, dict] = {}
    consulta = (
        db.query(QRZerado.lote, QRZerado.status, QRZerado.created_at, QRZerado.dominio)
        .order_by(QRZerado.created_at.desc())
        .all()
    )
    for lote, status, criado_em, dominio in consulta:
        item = lotes.setdefault(
            lote,
            {
                "lote": lote,
                "total": 0,
                "livres": 0,
                "usados": 0,
                "criado_em": criado_em.isoformat() if criado_em else None,
                "dominio": dominio,
            },
        )
        item["total"] += 1
        if status == STATUS_USADO:
            item["usados"] += 1
        else:
            item["livres"] += 1
    return sorted(lotes.values(), key=lambda i: i["criado_em"] or "", reverse=True)
