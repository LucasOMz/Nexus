"""LGPD — retenção e expurgo de dados.

## O que esta rota faz

Diz **quanto tempo cada tipo de registro é guardado** e **por quê**, mostra o
que já passou do prazo, e executa o expurgo quando pedido.

## Por que a política fica no código, e não numa tela

Cada prazo tem um motivo (prescricional fiscal, vida útil do bem, segurança).
Um número editável numa tela viraria "prazo que alguém digitou" — e o valor
jurídico da política se perde. Aqui ela é versionada junto com o sistema.

## O que o expurgo NÃO faz

Não apaga movimentação nem manutenção: o histórico patrimonial precisa
sobreviver à auditoria. Esses prazos são de **guarda mínima**, não de
descarte — o `acao` de cada um diz o que fazer, e só `apagar` apaga.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import require_admin
from app.database import get_db
from app.models.core import LogAuditoria, Manutencao, Movimentacao, Usuario
from app.services import plataforma

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/lgpd", tags=["lgpd"])

# Modelo e campo de data de cada tipo da política.
#
# `reportes`, `logs_acesso` e `notificacoes` estão em `RETENCAO` mas não têm
# tabela no sistema: a política os prevê para quando existirem. Ficam de fora
# do plano em vez de aparecerem com zero — um zero sugeriria "nada vencido"
# quando o certo é "não se aplica".
FONTES = {
    "auditoria": (LogAuditoria, "created_at"),
    "movimentacoes": (Movimentacao, "created_at"),
    "manutencoes": (Manutencao, "created_at"),
}


def _contar_vencidos(db: Session) -> list[dict]:
    """Um item por tipo de registro, com o total e o que passou do prazo."""
    agora = datetime.now(timezone.utc)
    itens = []

    for tipo, (modelo, campo_data) in FONTES.items():
        coluna = getattr(modelo, campo_data)
        total = db.query(func.count(modelo.id)).scalar() or 0

        prazo = plataforma.prazo_de(tipo, agora=agora)
        # Item sem prazo (`None`) nunca vence: a foto do ativo vive enquanto o
        # ativo existir. Contar como "0 vencidos" está certo, mas o texto
        # precisa dizer que é por não haver prazo, e não por não haver dado.
        vencidos = 0
        if prazo is not None:
            vencidos = (
                db.query(func.count(modelo.id)).filter(coluna < prazo).scalar() or 0
            )

        politica = plataforma.RETENCAO.get(tipo, {})
        itens.append({
            "tipo": tipo,
            "total": total,
            "vencidos": vencidos,
            "prazo": prazo.isoformat() if prazo else None,
            "dias": politica.get("dias"),
            "acao": politica.get("acao"),
            "motivo": politica.get("motivo"),
        })

    return itens


@router.get("/retencao", response_model=dict)
def retencao(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
) -> dict:
    """Política de retenção e o que já passou do prazo.

    Não apaga nada — é a prévia. Quem decide expurgar chama o POST.
    """
    itens = _contar_vencidos(db)

    # O que a política prevê mas o sistema ainda não tem tabela. Aparece para
    # a política ficar completa na tela, marcado como não aplicável.
    sem_tabela = [t for t in plataforma.RETENCAO if t not in FONTES]

    total_vencido = sum(i["vencidos"] for i in itens)
    a_apagar = sum(i["vencidos"] for i in itens if i["acao"] == "apagar")
    a_anonimizar = sum(i["vencidos"] for i in itens if i["acao"] == "anonimizar")

    return {
        "itens": itens,
        "sem_tabela": sem_tabela,
        "total_vencido": total_vencido,
        "a_apagar": a_apagar,
        "a_anonimizar": a_anonimizar,
        "mensagem": (
            "Nada passou do prazo de retenção."
            if not total_vencido else
            f"{total_vencido} registro(s) passaram do prazo. "
            f"{a_apagar} seriam apagados e {a_anonimizar} anonimizados."
        ),
    }


@router.post("/expurgar", response_model=dict)
def expurgar(
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
    confirmo: bool = Query(default=False),
    limite: int = Query(default=5000, ge=1, le=50000),
) -> dict:
    """Executa o expurgo do que passou do prazo.

    ## Duas travas

    **`confirmo=true`** é obrigatório. Sem ele, um GET acidental ou um clique
    duplo apagaria dados — e apagar não tem volta.

    **`limite`** existe porque o expurgo roda em transação: apagar 200 mil
    linhas de uma vez travaria o banco. Quem quiser mais chama de novo.

    ## O que é anonimizado, e não apagado

    A auditoria tem valor **probatório**: apagar a linha que registra quem
    excluiu um ativo destruiria a prova. O prazo dela vence, e o que sai são
    os **dados pessoais** — o IP e o autor —, preservando o fato.
    """
    if not confirmo:
        raise HTTPException(
            400,
            "Confirmação necessária. Envie ?confirmo=true — o expurgo não "
            "tem volta.",
        )

    agora = datetime.now(timezone.utc)
    apagados: dict[str, int] = {}
    anonimizados = 0

    # --- Apagar o que a política manda apagar ----------------------------
    for tipo, (modelo, campo_data) in FONTES.items():
        politica = plataforma.RETENCAO.get(tipo, {})
        if politica.get("acao") != "apagar":
            continue
        prazo = plataforma.prazo_de(tipo, agora=agora)
        if prazo is None:
            continue

        alvos = (
            db.query(modelo)
            .filter(getattr(modelo, campo_data) < prazo)
            .limit(limite)
            .all()
        )
        for obj in alvos:
            db.delete(obj)
        apagados[tipo] = len(alvos)

    # --- Anonimizar o que a política manda anonimizar ---------------------
    for tipo, (modelo, campo_data) in FONTES.items():
        politica = plataforma.RETENCAO.get(tipo, {})
        if politica.get("acao") != "anonimizar":
            continue
        prazo = plataforma.prazo_de(tipo, agora=agora)
        if prazo is None:
            continue

        alvos = (
            db.query(modelo)
            .filter(getattr(modelo, campo_data) < prazo)
            # Só o que AINDA tem vínculo. Sem este filtro, uma segunda
            # execução re-selecionaria as linhas já anonimizadas e gastaria o
            # `limite` sem tratar as que faltam — o expurgo nunca terminaria
            # numa base com mais vencidos do que o limite.
            .filter(modelo.usuario_id.isnot(None))
            .limit(limite)
            .all()
        )
        for obj in alvos:
            limpo = plataforma.anonimizar({
                "usuario_id": obj.usuario_id,
                "ip": getattr(obj, "ip", None),
            })

            # O VÍNCULO COM A PESSOA precisa sair de verdade. O serviço só
            # marca `usuario_id_original = None` — se ficássemos com o
            # `usuario_id` original, a trilha continuaria ligada à pessoa e a
            # anonimização não teria acontecido.
            #
            # O fato ("alguém alterou o ativo X no dia Y") permanece: é o que
            # concilia LGPD com auditoria.
            obj.usuario_id = None

            if hasattr(obj, "ip"):
                obj.ip = limpo.get("ip")
        anonimizados += len(alvos)

    db.commit()

    total = sum(apagados.values()) + anonimizados
    log.info("Expurgo LGPD por %s: %s", getattr(user, "email", "?"), apagados)

    return {
        "ok": True,
        "apagados": apagados,
        "anonimizados": anonimizados,
        "total": total,
        "mensagem": (
            "Nada a expurgar."
            if not total else
            f"{sum(apagados.values())} registro(s) apagado(s) e "
            f"{anonimizados} anonimizado(s)."
        ),
    }


@router.get("/proximo", response_model=dict)
def proximo_expurgo(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
) -> dict:
    """Quando o próximo registro vence — útil para agendar a rotina."""
    itens = _contar_vencidos(db)
    vencendo = [
        i for i in itens
        if i["prazo"] and i["total"] and i["vencidos"] == 0
    ]
    if not vencendo:
        return {"quando": None, "tipo": None, "mensagem": "Sem prazo em vista."}

    # O tipo cujo prazo chega primeiro.
    vencendo.sort(key=lambda i: i["prazo"])
    primeiro = vencendo[0]
    return {
        "quando": primeiro["prazo"],
        "tipo": primeiro["tipo"],
        "dias": primeiro["dias"],
        "mensagem": (
            f"O próximo expurgo é de {primeiro['tipo']}, "
            f"a partir de {primeiro['prazo']}."
        ),
    }
