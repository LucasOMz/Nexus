"""Reconciliação entre o inventário e o que o OCS enxerga na rede.

O OCS diz o que **existe agora**. O inventário diz o que **deveria existir**.
A diferença entre os dois é onde mora o trabalho:

* **fantasma** — a máquina está na rede e não está no inventário
* **perdido** — está no inventário e sumiu da rede (ou nunca apareceu)
* **divergência** — está nos dois, mas com dados diferentes

A comparação é uma **função pura** (`comparar`), separada da coleta de dados.
Isso permite testá-la com dados sintéticos, sem depender de um servidor OCS
no ar — que é justamente o que torna este tipo de tela difícil de confiar.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# Quantos dias sem contato fazem um ativo ser considerado sumido da rede.
DIAS_PADRAO = 30

# Campos comparados entre o inventário e o OCS, e como são chamados na tela.
CAMPOS = [
    ("hostname", "Hostname"),
    ("ip", "IP"),
    ("mac_address", "MAC"),
    ("so", "Sistema operacional"),
]


def _limpo(valor: Any) -> str | None:
    """Normaliza para comparar: sem espaços, sem caixa, sem vazio."""
    if valor is None:
        return None
    texto = str(valor).strip().lower()
    return texto or None


def _mac_limpo(valor: Any) -> str | None:
    """MAC sem separadores: '00:1A:2B' e '00-1a-2b' são a mesma coisa."""
    texto = _limpo(valor)
    if texto is None:
        return None
    return texto.replace(":", "").replace("-", "").replace(".", "")


def _quando(valor: Any) -> datetime | None:
    """Aceita datetime ou texto ISO — o OCS devolve datas em formatos variados."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    try:
        texto = str(valor).replace("Z", "+00:00")
        d = datetime.fromisoformat(texto)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _chave_dispositivo(d: dict) -> str | None:
    """Como identificar uma máquina vinda do OCS.

    Prefere o id do OCS (estável); cai para o hostname; por último o MAC.
    """
    for campo, normalizar in (("ocs_id", _limpo), ("hostname", _limpo), ("mac_address", _mac_limpo)):
        valor = normalizar(d.get(campo) if campo != "mac_address" else d.get("mac_address") or d.get("mac"))
        if valor:
            return f"{campo}:{valor}"
    return None


def _chave_ativo(a: dict) -> str | None:
    for campo, normalizar in (("ocs_id", _limpo), ("hostname", _limpo), ("mac_address", _mac_limpo)):
        valor = normalizar(a.get(campo))
        if valor:
            return f"{campo}:{valor}"
    return None


def comparar(
    inventario: list[dict],
    dispositivos: list[dict],
    dias_sem_contato: int = DIAS_PADRAO,
    agora: datetime | None = None,
) -> dict[str, Any]:
    """Compara o inventário com o que o OCS enxerga.

    `inventario`: ativos de TI (dicts com ativo_id, patrimonio, hostname, ip,
    mac_address, ocs_id, ocs_ultimo_contato).
    `dispositivos`: máquinas mapeadas do OCS (mesmos campos, mais `nome`).
    """
    agora = agora or datetime.now(timezone.utc)
    limite = agora - timedelta(days=dias_sem_contato)

    # --- Índices ----------------------------------------------------------
    por_chave_inv: dict[str, dict] = {}
    for a in inventario:
        k = _chave_ativo(a)
        if k:
            por_chave_inv.setdefault(k, a)

    por_chave_ocs: dict[str, dict] = {}
    for d in dispositivos:
        k = _chave_dispositivo(d)
        if k:
            por_chave_ocs.setdefault(k, d)

    # --- Fantasmas: na rede, fora do inventário ---------------------------
    # Só é fantasma se NENHUMA das chaves casar. Um ativo pode estar no
    # inventário sem `ocs_id`, mas com o mesmo hostname — não é fantasma.
    fantasmas = []
    for k, d in por_chave_ocs.items():
        if k in por_chave_inv:
            continue
        alternativas = {
            f"hostname:{_limpo(d.get('hostname'))}" if _limpo(d.get("hostname")) else None,
            f"ocs_id:{_limpo(d.get('ocs_id'))}" if _limpo(d.get("ocs_id")) else None,
            f"mac_address:{_mac_limpo(d.get('mac_address') or d.get('mac'))}"
            if _mac_limpo(d.get("mac_address") or d.get("mac")) else None,
        }
        if alternativas & set(por_chave_inv):
            continue
        fantasmas.append({
            "hostname": d.get("hostname") or d.get("nome"),
            "ip": d.get("ip"),
            "mac_address": d.get("mac_address") or d.get("mac"),
            "numero_serie": d.get("numero_serie") or d.get("serial"),
            "so": d.get("so"),
            "ocs_id": d.get("ocs_id"),
        })

    # --- Perdidos: no inventário, sem sinal na rede -----------------------
    # Só faz sentido para ativos que o OCS acompanha (têm `ocs_id`) — do
    # contrário estaríamos cobrando do OCS itens que ele nunca viu.
    perdidos = []
    for a in inventario:
        if not _limpo(a.get("ocs_id")) and not _limpo(a.get("hostname")):
            continue
        contato = _quando(a.get("ocs_ultimo_contato"))
        k = _chave_ativo(a)
        if contato is None:
            perdidos.append({
                "ativo_id": a.get("ativo_id"),
                "patrimonio": a.get("patrimonio"),
                "hostname": a.get("hostname"),
                "motivo": "nunca visto",
                "ocs_ultimo_contato": None,
                "dias": None,
            })
        elif contato < limite:
            dias = (agora - contato).days
            # Se o OCS voltou a enxergar agora, o ativo não está perdido.
            if k in por_chave_ocs:
                por_chave_ocs[k]["_visto"] = True
                continue
            perdidos.append({
                "ativo_id": a.get("ativo_id"),
                "patrimonio": a.get("patrimonio"),
                "hostname": a.get("hostname"),
                "motivo": f"{dias} dias sem contato",
                "ocs_ultimo_contato": contato.isoformat(),
                "dias": dias,
            })

    # --- Divergências: casados, mas com dados diferentes ------------------
    divergencias = []
    for k, a in por_chave_inv.items():
        d = por_chave_ocs.get(k)
        if d is None:
            # Tenta achar pelo hostname, mesmo que a chave principal difira.
            h = _limpo(a.get("hostname"))
            d = por_chave_ocs.get(f"hostname:{h}") if h else None
        if d is None:
            continue

        for campo, rotulo in CAMPOS:
            inventariado = a.get(campo)
            if campo == "mac_address":
                iguais = _mac_limpo(inventariado) == _mac_limpo(d.get("mac_address") or d.get("mac"))
            else:
                iguais = _limpo(inventariado) == _limpo(d.get(campo))
            # Campo vazio no inventário não é divergência: é informação que
            # falta, e apontar toda linha vazia afogaria o relatório.
            if _limpo(inventariado) is None:
                continue
            if not iguais:
                divergencias.append({
                    "ativo_id": a.get("ativo_id"),
                    "patrimonio": a.get("patrimonio"),
                    "campo": campo,
                    "rotulo": rotulo,
                    "no_inventario": inventariado,
                    "na_rede": d.get(campo) if campo != "mac_address" else (d.get("mac_address") or d.get("mac")),
                })

    casados = len([k for k in por_chave_inv if k in por_chave_ocs])
    return {
        "fantasmas": fantasmas,
        "perdidos": perdidos,
        "divergencias": divergencias,
        "resumo": {
            "na_rede": len(por_chave_ocs),
            "no_inventario": len(inventario),
            "casados": casados,
            "fantasmas": len(fantasmas),
            "perdidos": len(perdidos),
            "divergencias": len(divergencias),
        },
        "dias_sem_contato": dias_sem_contato,
        "conferido_em": agora.isoformat(),
    }
