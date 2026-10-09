"""Notificações do dia — o que o usuário precisa saber agora.

Fonte principal: **empréstimos**. Avisa no dia em que o equipamento precisa ser
devolvido, quando está atrasado e quando a devolução está próxima.

Cada usuário vê apenas o que é da **sua planta** (o administrador vê todas),
pela mesma regra usada no calendário.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from app.core.deps import get_current_user
from app.core.planta import aplicar_filtro, planta_ativa
from app.database import get_db
from app.models.core import Ativo, Usuario
from app.models.enums import StatusAtivo
from app.models.ti import AtivoTI

router = APIRouter(prefix="/notificacoes", tags=["notificacoes"])

# Quantos dias antes começa o aviso de "está chegando a hora".
DIAS_DE_ANTECEDENCIA = 3


def _texto_dias(dias: int) -> str:
    if dias == 0:
        return "hoje"
    if dias == 1:
        return "amanhã"
    return f"em {dias} dias"


@router.get("")
def listar(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta_id: int | None = Depends(planta_ativa),
) -> dict:
    """Notificações do usuário, das mais urgentes para as menos.

    Usuário comum sem planta recebe lista vazia em vez de erro: o sino não deve
    virar um alerta vermelho só porque falta configurar a planta.
    """
    if user.papel != "admin" and planta_id is None:
        return {"total": 0, "urgentes": 0, "itens": []}

    hoje = date.today()
    consulta = (
        db.query(Ativo)
        .options(selectinload(Ativo.planta), selectinload(Ativo.emprestado_para))
        .filter(
            Ativo.deleted_at.is_(None),
            Ativo.status == StatusAtivo.EMPRESTADO,
            Ativo.devolucao_prevista.isnot(None),
            Ativo.devolucao_prevista <= hoje + timedelta(days=DIAS_DE_ANTECEDENCIA),
        )
    )
    consulta = aplicar_filtro(consulta, Ativo, planta_id)

    itens: list[dict] = []
    for a in consulta.order_by(Ativo.devolucao_prevista).all():
        dias = (a.devolucao_prevista - hoje).days
        chamado = a.numero_chamado or "sem chamado"
        onde = f" · {a.planta_sigla}" if a.planta_sigla else ""
        quem = f" · com {a.emprestado_para_nome}" if a.emprestado_para_nome else ""

        if dias < 0:
            itens.append({
                "tipo": "emprestimo_atrasado",
                "nivel": "erro",
                "titulo": f"Devolução atrasada há {abs(dias)} dia(s)",
                "detalhe": f"{a.patrimonio} — {a.modelo or 'sem modelo'}{onde}. Chamado {chamado}{quem}.",
                "ativo_id": a.id,
                "patrimonio": a.patrimonio,
                "dias": dias,
            })
        elif dias == 0:
            itens.append({
                "tipo": "emprestimo_hoje",
                "nivel": "urgente",
                "titulo": "Devolução é HOJE",
                "detalhe": f"Pegar {a.patrimonio} — {a.modelo or 'sem modelo'}{onde}. Chamado {chamado}{quem}.",
                "ativo_id": a.id,
                "patrimonio": a.patrimonio,
                "dias": 0,
            })
        else:
            itens.append({
                "tipo": "emprestimo_proximo",
                "nivel": "info",
                "titulo": f"Devolução {_texto_dias(dias)}",
                "detalhe": f"{a.patrimonio} — {a.modelo or 'sem modelo'}{onde}. Chamado {chamado}{quem}.",
                "ativo_id": a.id,
                "patrimonio": a.patrimonio,
                "dias": dias,
            })

    # Ordena por urgência: atrasado, hoje, depois os próximos.
    ordem = {"emprestimo_atrasado": 0, "emprestimo_hoje": 1, "emprestimo_proximo": 2}
    itens.sort(key=lambda i: (ordem.get(i["tipo"], 9), i["dias"]))

    # --- Transferências esperando decisão deste usuário --------------------
    for item in _transferencias_pendentes(db, user):
        itens.insert(0, item)

    # --- Problemas na integração com o OCS (só o administrador) ------------
    for item in _ocs_pendencias(db, user):
        itens.insert(0, item)

    return {
        "total": len(itens),
        "urgentes": sum(1 for i in itens if i["nivel"] in ("erro", "urgente")),
        "itens": itens,
    }


def _ocs_pendencias(db: Session, user: Usuario) -> list[dict]:
    """Avisa o administrador quando a integração com o OCS vai mal.

    Três situações justificam um aviso:

    * a última sincronização **falhou** — o parque para de atualizar em silêncio
    * a sincronização automática está ligada mas **atrasou** muito
    * existem máquinas importadas **sem planta**, esperando revisão

    Avisamos também quando a integração está desligada: um erro guardado de
    quando ela estava ativa não deve ficar alarmando o sino para sempre.
    """
    from datetime import datetime, timezone

    from app.services.config_service import obter_config_ocs

    papel = getattr(user.papel, "value", user.papel)
    if papel != "admin":
        return []

    cfg = obter_config_ocs(db)
    if not cfg.ativo:
        return []

    saida: list[dict] = []

    # 1) A última sincronização falhou.
    if cfg.ultimo_erro_msg:
        falhas = int(cfg.falhas_consecutivas or 0)
        vezes = f"{falhas} vez{'es' if falhas > 1 else ''}" if falhas else "1 vez"
        saida.append({
            "tipo": "ocs_falha",
            "nivel": "erro",
            "titulo": f"Falha na sincronização com o OCS ({vezes})",
            "detalhe": f"{cfg.ultimo_erro_msg} — o inventário não está sendo atualizado.",
            "painel": "ocs",
            "dias": 0,
        })

    # 2) Sincronização automática atrasada.
    if cfg.sync_automatica and cfg.ultima_sync_em:
        try:
            ultima = datetime.fromisoformat(cfg.ultima_sync_em)
            if ultima.tzinfo is None:
                ultima = ultima.replace(tzinfo=timezone.utc)
            esperado = max(5, int(cfg.sync_intervalo_minutos or 60)) * 60
            # Só avisa quando passa do DOBRO do intervalo: um atraso pequeno é normal.
            atraso = (datetime.now(timezone.utc) - ultima).total_seconds() - (esperado * 2)
            if atraso > 0:
                horas = int(atraso // 3600)
                quando = f"{horas} hora(s)" if horas >= 1 else f"{int(atraso // 60)} minuto(s)"
                saida.append({
                    "tipo": "ocs_atrasada",
                    "nivel": "urgente",
                    "titulo": "Sincronização com o OCS atrasada",
                    "detalhe": f"A última foi em {cfg.ultima_sync_em[:16].replace('T', ' ')} — "
                               f"passou {quando} do esperado.",
                    "painel": "ocs",
                    "dias": 0,
                })
        except (ValueError, TypeError):
            pass

    # 3) Máquinas vindas do OCS ainda sem planta (esperando revisão).
    sem_planta = (
        db.query(Ativo)
        .join(AtivoTI, AtivoTI.ativo_id == Ativo.id)
        .filter(
            Ativo.deleted_at.is_(None),
            Ativo.planta_id.is_(None),
            AtivoTI.ocs_id.isnot(None),
        )
        .count()
    )
    if sem_planta:
        saida.append({
            "tipo": "ocs_sem_planta",
            "nivel": "info",
            "titulo": f"{sem_planta} máquina(s) do OCS sem planta",
            "detalhe": "Importadas pelo OCS, mas nenhuma regra de hostname definiu a planta. "
                       "Confira as regras em Administração → OCS Inventory.",
            "painel": "ocs",
            "dias": 0,
        })

    return saida


def _transferencias_pendentes(db: Session, user: Usuario) -> list[dict]:
    """O que este usuário precisa decidir agora.

    O técnico decide o que chega para a planta dele; o administrador decide o
    que já passou pelo destino.
    """
    from app.models.core import Transferencia
    from app.routers.transferencias import MOTIVOS

    papel = getattr(user.papel, "value", user.papel)
    base = db.query(Transferencia).options(
        selectinload(Transferencia.ativo),
        selectinload(Transferencia.planta_origem),
        selectinload(Transferencia.planta_destino),
        selectinload(Transferencia.solicitado_por),
    )

    if papel == "admin":
        pendentes = base.filter(Transferencia.status == "aguardando_admin").all()
        acao = "Aprovar como administrador"
    elif user.planta_id is not None and papel in ("ti", "admin"):
        pendentes = base.filter(
            Transferencia.status == "aguardando_destino",
            Transferencia.planta_destino_id == user.planta_id,
        ).all()
        acao = "Aprovar chegada"
    else:
        return []

    saida = []
    for t in pendentes:
        origem = t.planta_origem.sigla if t.planta_origem else "?"
        destino = t.planta_destino.sigla if t.planta_destino else "?"
        motivo = MOTIVOS.get(t.motivo, t.motivo)
        saida.append({
            "tipo": "transferencia_pendente",
            "nivel": "urgente",
            "titulo": f"Transferência aguardando você ({acao})",
            "detalhe": f"{(t.ativo.patrimonio if t.ativo else '?')} — {origem} → {destino}. "
                       f"{motivo}, pedido por {(t.solicitado_por.nome if t.solicitado_por else '—')}.",
            "transferencia_id": t.id,
            "patrimonio": t.ativo.patrimonio if t.ativo else None,
            "dias": 0,
        })
    return saida
