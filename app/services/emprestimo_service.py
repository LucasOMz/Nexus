"""Ciclo de empréstimo: reserva, retirada, uso, devolução e vistoria.

O que existia era um empréstimo "chato": três campos no ativo
(`emprestado_em`, `devolucao_prevista`, `emprestado_para_id`) e um aviso de
atraso. Isso registra QUE está emprestado, mas não o ciclo — nem o que foi
combinado na entrega, nem o que voltou diferente.

Este módulo é a **lógica** do ciclo, em funções puras:

* em que etapa o empréstimo está e qual é o próximo passo válido
* quando e como escalar o atraso (usuário → gestor → bloqueio)
* o que a devolução revelou, e se isso deve abrir manutenção

O documento assinado já é resolvido pelo modelo `Termo` (hash SHA-256 + PDF),
que existe e não foi alterado.
"""
from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from typing import Any

# Níveis de escalonamento do atraso, em dias.
DIAS_AVISO_USUARIO = 1
DIAS_AVISO_GESTOR = 7
DIAS_BLOQUEIO = 15


class SituacaoEmprestimo(str, enum.Enum):
    """Etapas do ciclo, na ordem em que acontecem."""

    RESERVADO = "reservado"      # separado, ainda não retirado
    RETIRADO = "retirado"        # na mão do usuário
    DEVOLVIDO = "devolvido"      # entregue de volta, aguardando vistoria
    VISTORIADO = "vistoriado"    # conferido e encerrado
    CANCELADO = "cancelado"


# Transições válidas. Um empréstimo não pula etapa nem volta sozinho.
TRANSICOES: dict[SituacaoEmprestimo, tuple[SituacaoEmprestimo, ...]] = {
    SituacaoEmprestimo.RESERVADO: (
        SituacaoEmprestimo.RETIRADO,
        SituacaoEmprestimo.CANCELADO,
    ),
    SituacaoEmprestimo.RETIRADO: (
        SituacaoEmprestimo.DEVOLVIDO,
    ),
    SituacaoEmprestimo.DEVOLVIDO: (
        SituacaoEmprestimo.VISTORIADO,
    ),
    SituacaoEmprestimo.VISTORIADO: (),
    SituacaoEmprestimo.CANCELADO: (),
}

# O que cada transição significa, para a tela explicar em vez de só bloquear.
PASSOS = {
    SituacaoEmprestimo.RETIRADO: {
        "rotulo": "Registrar retirada",
        "exige": "termo assinado e conferência de entrega",
        "exige_termo": True,
        "exige_checklist": True,
    },
    SituacaoEmprestimo.DEVOLVIDO: {
        "rotulo": "Registrar devolução",
        "exige": "conferência do que voltou",
        "exige_termo": False,
        "exige_checklist": True,
    },
    SituacaoEmprestimo.VISTORIADO: {
        "rotulo": "Concluir vistoria",
        "exige": "nada — apenas confirma a conferência",
        "exige_termo": False,
        "exige_checklist": False,
    },
    SituacaoEmprestimo.CANCELADO: {
        "rotulo": "Cancelar reserva",
        "exige": "nada",
        "exige_termo": False,
        "exige_checklist": False,
    },
}


def proximos_passos(situacao: SituacaoEmprestimo | str) -> list[dict]:
    """Para onde este empréstimo pode ir agora — e o que cada passo exige."""
    atual = SituacaoEmprestimo(situacao)
    return [
        {"situacao": destino.value, **PASSOS.get(destino, {"rotulo": destino.value})}
        for destino in TRANSICOES.get(atual, ())
    ]


def pode_transicionar(de: SituacaoEmprestimo | str, para: SituacaoEmprestimo | str) -> bool:
    return SituacaoEmprestimo(para) in TRANSICOES.get(SituacaoEmprestimo(de), ())


def validar_transicao(
    de: SituacaoEmprestimo | str,
    para: SituacaoEmprestimo | str,
    tem_termo: bool = False,
    tem_checklist: bool = False,
) -> dict[str, Any]:
    """Confere a transição — e diz o que falta, não só que não pode.

    Um ciclo de empréstimo que só responde "não pode" faz a pessoa desistir de
    usar o sistema e voltar para o caderno.
    """
    destino = SituacaoEmprestimo(para)
    if not pode_transicionar(de, para):
        return {
            "ok": False,
            "motivo": f"Não é possível ir de '{SituacaoEmprestimo(de).value}' "
                      f"para '{destino.value}'.",
        }

    regra = PASSOS.get(destino, {})
    if regra.get("exige_termo") and not tem_termo:
        return {"ok": False, "motivo": "É preciso o termo de responsabilidade assinado."}
    if regra.get("exige_checklist") and not tem_checklist:
        return {"ok": False, "motivo": "Confira e registre o estado do equipamento."}
    return {"ok": True, "situacao": destino.value}


# ---------------------------------------------------------------------------
def escalonamento(
    devolucao_prevista: Any,
    agora: datetime | None = None,
    ja_bloqueado: bool = False,
) -> dict[str, Any]:
    """Em que degrau o atraso está, e quem precisa ser avisado.

    A escada: avisa o usuário → avisa o gestor → bloqueia novo empréstimo.
    Sem ela, um atraso de 60 dias fica do mesmo tamanho de um de 2 dias.
    """
    if ja_bloqueado:
        return {
            "nivel": 3,
            "situacao": "bloqueado",
            "dias_atraso": None,
            "avisar": [],
            "bloqueia_novo_emprestimo": True,
            "mensagem": "Usuário bloqueado para novos empréstimos.",
        }

    limite = _data(devolucao_prevista)
    if limite is None:
        return {
            "nivel": 0,
            "situacao": "sem_prazo",
            "dias_atraso": 0,
            "avisar": [],
            "bloqueia_novo_emprestimo": False,
            "mensagem": "Sem prazo de devolução definido.",
        }

    hoje = (agora or datetime.now(timezone.utc)).date()
    dias = (hoje - limite).days

    if dias <= 0:
        return {
            "nivel": 0,
            "situacao": "em_dia",
            "dias_atraso": 0,
            "dias_restantes": -dias,
            "avisar": [],
            "bloqueia_novo_emprestimo": False,
            "mensagem": f"Em dia — faltam {-dias} dia(s).",
        }

    if dias >= DIAS_BLOQUEIO:
        return {
            "nivel": 3,
            "situacao": "bloqueado",
            "dias_atraso": dias,
            "avisar": ["usuario", "gestor"],
            "bloqueia_novo_emprestimo": True,
            "mensagem": f"{dias} dias de atraso — novos empréstimos bloqueados.",
        }

    if dias >= DIAS_AVISO_GESTOR:
        return {
            "nivel": 2,
            "situacao": "gestor_avisado",
            "dias_atraso": dias,
            "avisar": ["usuario", "gestor"],
            "bloqueia_novo_emprestimo": False,
            "mensagem": f"{dias} dias de atraso — o gestor foi avisado.",
        }

    if dias >= DIAS_AVISO_USUARIO:
        return {
            "nivel": 1,
            "situacao": "usuario_avisado",
            "dias_atraso": dias,
            "avisar": ["usuario"],
            "bloqueia_novo_emprestimo": False,
            "mensagem": f"{dias} dia(s) de atraso.",
        }

    return {
        "nivel": 0,
        "situacao": "em_dia",
        "dias_atraso": 0,
        "avisar": [],
        "bloqueia_novo_emprestimo": False,
        "mensagem": "Em dia.",
    }


def _data(valor: Any) -> date | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Checklist: o que foi combinado na entrega e o que voltou.
#
# A mesma lista serve para os dois momentos. Comparar os dois é o que revela
# avaria — um checklist só na devolução não prova nada.
CHECKLIST_PADRAO = [
    "Liga e inicializa",
    "Tela sem trinca ou mancha",
    "Teclado completo e funcional",
    "Carcaça sem trinca",
    "Carregador e cabo presentes",
    "Bateria segura carga",
    "Sem sinais de queda ou líquido",
]


def avaliar_devolucao(
    entrega: dict[str, bool],
    devolucao: dict[str, bool],
    itens: list[str] | None = None,
) -> dict[str, Any]:
    """Compara o que saiu com o que voltou.

    `itens` são os rótulos do checklist **configurado** na Administração. Sem
    ele, usa o padrão de fábrica — que serve de ponto de partida, mas não para
    todo tipo de bem.

    Um item que estava OK na entrega e voltou com problema é **avaria**. Um que
    já estava com problema na entrega não é — e apontá-lo como avaria seria
    cobrar do usuário o que já estava quebrado.
    """
    avarias = []
    melhorou = []
    sem_base = []

    for item in (itens if itens else CHECKLIST_PADRAO):
        saiu_ok = entrega.get(item)
        voltou_ok = devolucao.get(item)

        if saiu_ok is None or voltou_ok is None:
            # Sem os dois lados não se pode afirmar nada.
            if voltou_ok is False and saiu_ok is None:
                sem_base.append(item)
            continue

        if saiu_ok and not voltou_ok:
            avarias.append(item)
        elif not saiu_ok and voltou_ok:
            melhorou.append(item)

    precisa_vistoria = bool(avarias) or bool(sem_base)

    return {
        "avarias": avarias,
        "melhorou": melhorou,
        # Voltou com problema, mas sem registro de como saiu: alguém precisa olhar.
        "sem_base_de_comparacao": sem_base,
        "precisa_vistoria": precisa_vistoria,
        "abrir_manutencao": bool(avarias),
        "situacao": "avaria" if avarias else "conforme",
        "mensagem": (
            f"{len(avarias)} item(ns) avariado(s): {', '.join(avarias)}."
            if avarias else
            "Equipamento devolvido sem avarias registradas."
        ),
    }


def resumo_do_ciclo(
    situacao: SituacaoEmprestimo | str,
    devolucao_prevista: Any = None,
    tem_termo: bool = False,
    tem_checklist_entrega: bool = False,
    agora: datetime | None = None,
) -> dict[str, Any]:
    """Onde o empréstimo está, o que falta e o que fazer agora."""
    atual = SituacaoEmprestimo(situacao)
    alerta = escalonamento(devolucao_prevista, agora=agora)

    pendencias = []
    if atual in (SituacaoEmprestimo.RESERVADO, SituacaoEmprestimo.RETIRADO) and not tem_termo:
        pendencias.append("Termo de responsabilidade não assinado")
    if atual == SituacaoEmprestimo.RETIRADO and not tem_checklist_entrega:
        pendencias.append("Conferência de entrega não registrada")
    if atual == SituacaoEmprestimo.DEVOLVIDO:
        pendencias.append("Aguardando vistoria")

    return {
        "situacao": atual.value,
        "alerta": alerta,
        "pendencias": pendencias,
        "proximos_passos": proximos_passos(atual),
        "encerrado": atual in (SituacaoEmprestimo.VISTORIADO, SituacaoEmprestimo.CANCELADO),
    }
