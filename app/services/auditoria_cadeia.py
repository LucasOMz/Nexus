"""Auditoria imutável — cadeia de hash sobre o log que já existe.

O log de auditoria diz quem fez o quê. Mas um log que pode ser **editado** não
serve para auditar: quem tem acesso ao banco apaga a linha que o incrimina.

A cadeia resolve isso sem trocar o banco nem o modelo:

    registro N guarda  hash = SHA256(hash_do_anterior + conteudo_do_registro)

Alterar qualquer registro antigo quebra o hash de **todos os seguintes** — e a
verificação aponta exatamente onde a cadeia rompeu.

## O que isto é e o que não é

É **detecção de adulteração**, e é honesto dizer os limites:

* não **impede** a alteração — permite **provar** que houve;
* quem controla o banco pode recalcular a cadeia inteira. Contra isso, o certo
  é externar o hash do último registro (e-mail diário, outro servidor, cartório);
* por isso o módulo expõe `selo()`, que devolve o topo da cadeia para ser
  guardado fora.

Sem essa ressalva, "auditoria imutável" viraria promessa maior do que entrega.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

# Marca o primeiro registro: antes dele não há anterior.
GENESIS = "0" * 64


def _canonico(registro: dict[str, Any]) -> str:
    """Representação estável do registro.

    `sort_keys` e separadores fixos: sem isso, dois dicionários iguais com
    ordem diferente de chave gerariam hashes diferentes.
    """
    base = {k: v for k, v in registro.items() if k not in ("hash", "hash_anterior")}
    return json.dumps(base, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), default=str)


def calcular_hash(registro: dict[str, Any], hash_anterior: str) -> str:
    """Hash deste registro, encadeado ao anterior."""
    material = f"{hash_anterior}|{_canonico(registro)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def encadear(registros: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Percorre a lista e devolve cada registro com seus dois hashes.

    Espera a ordem cronológica — a cadeia depende da ordem.
    """
    saida = []
    anterior = GENESIS
    for r in registros:
        atual = dict(r)
        atual["hash_anterior"] = anterior
        atual["hash"] = calcular_hash(atual, anterior)
        anterior = atual["hash"]
        saida.append(atual)
    return saida


def verificar(registros: list[dict[str, Any]]) -> dict[str, Any]:
    """A cadeia está íntegra? Se não, onde rompeu e por quê.

    Devolve o índice do primeiro rompimento — apontar *onde* foi alterado é o
    que torna a verificação útil numa investigação.
    """
    anterior = GENESIS
    for i, r in enumerate(registros):
        esperado_anterior = r.get("hash_anterior")
        if esperado_anterior != anterior:
            return {
                "integra": False,
                "indice": i,
                "registro_id": r.get("id"),
                "motivo": "encadeamento quebrado",
                "detalhe": (
                    "Este registro aponta para um hash anterior diferente do "
                    "registro que vem antes dele — houve remoção ou reordenação."
                ),
                "verificados": i,
            }

        esperado = calcular_hash(r, anterior)
        if r.get("hash") != esperado:
            return {
                "integra": False,
                "indice": i,
                "registro_id": r.get("id"),
                "motivo": "conteudo alterado",
                "detalhe": (
                    "O conteúdo deste registro não corresponde ao hash gravado — "
                    "a linha foi editada depois de escrita."
                ),
                "verificados": i,
            }
        anterior = r["hash"]

    return {
        "integra": True,
        "indice": None,
        "motivo": None,
        "detalhe": None,
        "verificados": len(registros),
    }


def selo(registros: list[dict[str, Any]], agora: datetime | None = None) -> dict[str, Any]:
    """Topo da cadeia, para ser guardado FORA do sistema.

    É o que fecha a brecha: se alguém recalcular a cadeia inteira no banco, o
    selo guardado fora não vai bater. Sem isso, a cadeia só prova adulteração
    de quem não tem acesso ao banco.
    """
    momento = agora or datetime.now(timezone.utc)
    ultimo = registros[-1]["hash"] if registros else GENESIS
    return {
        "selado_em": momento.isoformat(),
        "registros": len(registros),
        "ultimo_hash": ultimo,
        "raiz": GENESIS,
    }


def conferir_selo(registros: list[dict[str, Any]], selo_guardado: dict[str, Any]) -> dict[str, Any]:
    """A cadeia de agora ainda começa/termina onde o selo dizia?

    Se a contagem **diminuiu**, alguém apagou registros antigos. Se o último
    hash de um prefixo mudou, a história foi reescrita.
    """
    total_guardado = int(selo_guardado.get("registros") or 0)
    if len(registros) < total_guardado:
        return {
            "confere": False,
            "motivo": "registros removidos",
            "detalhe": f"O selo cobria {total_guardado} registros; restam {len(registros)}.",
        }

    if total_guardado and registros:
        prefixo = verificar(registros[:total_guardado])
        if not prefixo["integra"]:
            return {
                "confere": False,
                "motivo": "historico reescrito",
                "detalhe": prefixo["detalhe"],
            }
        if registros[total_guardado - 1]["hash"] != selo_guardado.get("ultimo_hash"):
            return {
                "confere": False,
                "motivo": "historico reescrito",
                "detalhe": "O último hash selado não corresponde ao registro daquela posição.",
            }

    return {"confere": True, "motivo": None, "detalhe": None}
