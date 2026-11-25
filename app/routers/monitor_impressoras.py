"""Monitoramento de impressoras por SNMP.

O OCS enxerga bem computador e mal impressora. Aqui a coleta é direta, pelo
protocolo que a impressora já fala — e o **contador de páginas deixa de ser
manual**.

Só lê da impressora e grava a leitura do contador. Não altera o cadastro: se o
modelo ou a série vierem diferentes, isso é divergência para a pessoa decidir,
não motivo para sobrescrever dado que alguém digitou.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_module, require_write
from app.core.permissoes import pode_inventario
from app.core.planta import aplicar_filtro, planta_ativa_obrigatoria
from app.database import get_db
from app.models.core import Ativo, Usuario
from app.models.enums import Dominio
from app.models.impressora import AtivoImpressora, LeituraContador
from app.services import snmp_service
from app.services.audit_service import audit

log = logging.getLogger("app.monitor.impressoras")

router = APIRouter(prefix="/monitor/impressoras", tags=["impressoras"])


def _impressoras(db: Session, planta_id: int | None) -> list[tuple[Ativo, AtivoImpressora]]:
    q = (
        db.query(Ativo, AtivoImpressora)
        .outerjoin(AtivoImpressora, AtivoImpressora.ativo_id == Ativo.id)
        .filter(Ativo.deleted_at.is_(None), Ativo.dominio == Dominio.IMPRESSORA)
    )
    q = aplicar_filtro(q, Ativo, planta_id)
    return q.all()


def _leituras_recentes(db: Session, ativo_id: int) -> tuple[LeituraContador | None, LeituraContador | None]:
    leituras = (
        db.query(LeituraContador)
        .filter(LeituraContador.ativo_id == ativo_id,
                LeituraContador.deleted_at.is_(None))
        .order_by(LeituraContador.data_leitura.desc(), LeituraContador.id.desc())
        .limit(2).all()
    )
    return (leituras[0] if leituras else None, leituras[1] if len(leituras) == 2 else None)


def _endereco(ficha: AtivoImpressora | None, ativo: Ativo) -> str | None:
    """Onde a impressora responde.

    O IP do cadastro vem primeiro; sem ele, o hostname serve — muitas redes
    resolvem o nome da impressora por DNS.
    """
    if ficha is None:
        return None
    return (ficha.ip or "").strip() or (ficha.hostname or "").strip() or None


def _linha(db: Session, ativo: Ativo, ficha: AtivoImpressora | None) -> dict:
    """Situação conhecida da impressora, sem tocar na rede."""
    ultima, anterior = _leituras_recentes(db, ativo.id)

    dias = None
    if ultima and anterior and ultima.data_leitura and anterior.data_leitura:
        dias = (ultima.data_leitura - anterior.data_leitura).days

    return {
        "ativo_id": ativo.id,
        "patrimonio": ativo.patrimonio,
        "modelo": ativo.modelo,
        "marca": ativo.marca,
        "endereco": _endereco(ficha, ativo),
        "com_snmp": bool(_endereco(ficha, ativo)),
        "contador_cadastro": ficha.contador_paginas if ficha else None,
        # A foto vem JUNTO com a lista, não numa segunda chamada por
        # impressora.
        #
        # O cartão do monitor mostra a imagem ao lado esquerdo. Buscá-la
        # depois faria a tela piscar: cada cartão apareceria sem foto e
        # ganharia a sua uma a uma, na ordem em que as requisições voltassem.
        "foto_id": ativo.foto_id,
        "tipo_impressao": (
            getattr(ficha.tipo_impressao, "value", ficha.tipo_impressao)
            if ficha and ficha.tipo_impressao else None
        ),
        "ultima_leitura": ultima.contador if ultima else None,
        "ultima_leitura_em": ultima.data_leitura if ultima else None,
        "consumo_desde_a_anterior": (
            (ultima.contador - anterior.contador)
            if ultima and anterior else None
        ),
        "dias_entre_leituras": dias,
    }


# ---------------------------------------------------------------------------
@router.get("", response_model=dict)
def painel(
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa_obrigatoria),
):
    """Situação de todas as impressoras, com o que já se sabe do contador."""
    itens = [_linha(db, a, f) for a, f in _impressoras(db, planta_id)]
    itens.sort(key=lambda x: x["patrimonio"] or "")
    return {
        "itens": itens,
        "total": len(itens),
        "com_snmp": len([i for i in itens if i["com_snmp"]]),
        "snmp_disponivel": snmp_service.disponivel(),
    }


@router.post("/{ativo_id}/coletar", response_model=dict)
def coletar_uma(
    ativo_id: int,
    request: Request,
    comunidade: str = Query(default="public"),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa_obrigatoria),
):
    """Consulta a impressora agora e grava a leitura do contador.

    Se o contador não vier, **nada é gravado** — gravar zero poluiria o
    histórico e faria o custo por página despencar.
    """
    q = db.query(Ativo).filter(
        Ativo.id == ativo_id, Ativo.deleted_at.is_(None), Ativo.dominio == Dominio.IMPRESSORA,
    )
    ativo = aplicar_filtro(q, Ativo, planta_id).first()
    if ativo is None:
        raise HTTPException(404, "Ativo não encontrado")
    ficha = db.get(AtivoImpressora, ativo_id)
    endereco = _endereco(ficha, ativo)
    if not endereco:
        raise HTTPException(
            400, "Esta impressora não tem IP nem hostname cadastrado — sem isso não há como consultá-la."
        )
    if not snmp_service.disponivel():
        raise HTTPException(
            400, "O suporte a SNMP precisa da biblioteca pysnmp (pip install pysnmp)."
        )

    try:
        dados = snmp_service.coletar(endereco, comunidade=comunidade)
    except snmp_service.SNMPIndisponivel as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001 — a impressora pode estar desligada
        log.warning("Falha SNMP em %s: %s", endereco, e)
        raise HTTPException(
            502, f"A impressora {endereco} não respondeu por SNMP ({type(e).__name__})."
        ) from e

    if not dados.get("respondeu"):
        raise HTTPException(502, f"A impressora {endereco} respondeu, mas sem nenhum dado conhecido.")

    gravado = False
    if dados.get("contador") is not None:
        db.add(LeituraContador(
            ativo_id=ativo.id,
            contador=dados["contador"],
            observacoes=f"Coleta SNMP automática ({endereco})",
        ))
        if ficha is not None:
            ficha.contador_paginas = dados["contador"]
        gravado = True

    audit(db, user, "coletar_snmp", "ativo", ativo.id,
          ip=request.client.host if request.client else None,
          diff={"endereco": endereco, "contador": dados.get("contador")})
    db.commit()

    return {
        "ativo_id": ativo.id,
        "endereco": endereco,
        "coletado": dados,
        "contador_gravado": gravado,
        "mensagem": (
            "Contador atualizado." if gravado
            else "A impressora respondeu, mas não informou o contador."
        ),
    }


@router.post("/coletar-todas", response_model=dict)
def coletar_todas(
    request: Request,
    comunidade: str = Query(default="public"),
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_write),
    planta_id: int | None = Depends(planta_ativa_obrigatoria),
):
    """Percorre todas as impressoras com endereço.

    Uma falha **não interrompe as outras**: impressora desligada numa sala não
    pode impedir a coleta das 200 restantes.
    """
    if not snmp_service.disponivel():
        raise HTTPException(400, "O suporte a SNMP precisa da biblioteca pysnmp.")

    ok, falhas, sem_endereco, sem_contador = 0, [], 0, 0
    for ativo, ficha in _impressoras(db, planta_id):
        endereco = _endereco(ficha, ativo)
        if not endereco:
            sem_endereco += 1
            continue
        try:
            dados = snmp_service.coletar(endereco, comunidade=comunidade)
        except Exception as e:  # noqa: BLE001
            falhas.append({"patrimonio": ativo.patrimonio, "endereco": endereco,
                           "motivo": type(e).__name__})
            continue

        if dados.get("contador") is None:
            sem_contador += 1
            continue
        db.add(LeituraContador(
            ativo_id=ativo.id, contador=dados["contador"],
            observacoes=f"Coleta SNMP automática ({endereco})",
        ))
        if ficha is not None:
            ficha.contador_paginas = dados["contador"]
        ok += 1

    audit(db, user, "coletar_snmp_lote", "ativo", None,
          ip=request.client.host if request.client else None,
          diff={"ok": ok, "falhas": len(falhas)})
    db.commit()

    return {
        "atualizadas": ok,
        "falharam": falhas,
        "sem_endereco": sem_endereco,
        "sem_contador": sem_contador,
        "mensagem": f"{ok} impressora(s) com contador atualizado.",
    }


@router.get("/{ativo_id}/alertas", response_model=dict)
def alertas_de_suprimento(
    ativo_id: int,
    comunidade: str = Query(default="public"),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa_obrigatoria),
):
    """Nível de tonner e estimativa de quanto ainda dura.

    Traz os **suprimentos todos** (uma colorida tem um por cor) e a projeção
    pelo ritmo real de impressão — porque 20% não diz quando acaba, e 20% a
    5.000 páginas por dia dura horas.
    """
    q = db.query(Ativo).filter(
        Ativo.id == ativo_id, Ativo.deleted_at.is_(None), Ativo.dominio == Dominio.IMPRESSORA,
    )
    ativo = aplicar_filtro(q, Ativo, planta_id).first()
    if ativo is None:
        raise HTTPException(404, "Ativo não encontrado")
    ficha = db.get(AtivoImpressora, ativo_id)
    endereco = _endereco(ficha, ativo)
    if not endereco:
        raise HTTPException(400, "Sem IP ou hostname cadastrado para esta impressora.")

    # Varredura completa: sem isso só o primeiro cartucho seria lido.
    suprimentos = _varrer_suprimentos(endereco, comunidade)
    _estimar_suprimentos(suprimentos, _linha(db, ativo, ficha))
    return {"ativo_id": ativo_id, "endereco": endereco, "suprimentos": suprimentos,
            "alertas": snmp_service.alertas_de_suprimento(suprimentos)}


def _estimar_suprimentos(suprimentos: list[dict], linha: dict) -> None:
    ultima = linha["ultima_leitura"]
    consumo = linha["consumo_desde_a_anterior"]
    anterior = ultima - consumo if ultima is not None and consumo is not None else None
    for s in suprimentos:
        s["estimativa"] = snmp_service.estimar_duracao(
            s.get("percentual"), ultima, anterior, linha["dias_entre_leituras"],
        )


@router.get("/{ativo_id}/situacao", response_model=dict)
def situacao_da_impressora(
    ativo_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_module("monitor")),
    planta_id: int | None = Depends(planta_ativa_obrigatoria),
):
    """Consulta a comunicação e os suprimentos sem gravar contador."""
    if not pode_inventario(user, Dominio.IMPRESSORA.value):
        raise HTTPException(403, "Seu usuário não tem acesso ao inventário de impressoras.")
    consulta = db.query(Ativo).filter(
        Ativo.id == ativo_id, Ativo.deleted_at.is_(None), Ativo.dominio == Dominio.IMPRESSORA,
    )
    ativo = aplicar_filtro(consulta, Ativo, planta_id).first()
    if ativo is None:
        raise HTTPException(404, "Ativo não encontrado")
    ficha = db.get(AtivoImpressora, ativo_id)
    linha = _linha(db, ativo, ficha)
    endereco = linha["endereco"]
    suprimentos = []
    comunicacao = "sem_endereco"
    if endereco:
        try:
            suprimentos, respondeu = snmp_service.monitorar_suprimentos(endereco)
        except snmp_service.SNMPIndisponivel:
            comunicacao = "indisponivel"
        except Exception as e:  # noqa: BLE001 — mantém o cadastro disponível se a consulta falhar
            log.warning("Falha ao verificar comunicação SNMP de %s (%s)", ativo_id, type(e).__name__)
            comunicacao = "falha_na_consulta"
        else:
            comunicacao = "online" if respondeu else "sem_resposta"
    _estimar_suprimentos(suprimentos, linha)
    return {**linha, "comunicacao": comunicacao, "verificado_em": snmp_service.carimbo(),
            "suprimentos": suprimentos, "alertas": snmp_service.alertas_de_suprimento(suprimentos)}


def _varrer_suprimentos(endereco: str, comunidade: str) -> list[dict]:
    """Percorre a tabela de suprimentos da impressora."""
    if not snmp_service.disponivel():
        raise HTTPException(400, "O suporte a SNMP precisa da biblioteca pysnmp.")
    try:
        pares = snmp_service.varrer_suprimentos(endereco, comunidade=comunidade)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            502, f"A impressora {endereco} não respondeu ({type(e).__name__})."
        ) from e
    return snmp_service.extrair_suprimentos(pares)
