"""Coleta de software enviada pelo agente.

## Por que um endpoint separado do inventário

O inventário de hardware e a lista de software tem **frequências
diferentes**: hardware muda quando alguém troca um pente de memória; software
muda toda semana com atualização do navegador.

Juntar os dois faria o hardware ser reenviado junto com 150 programas a cada
coleta, e obrigaria a mesma frequência para coisas que não têm.

## O custo que isso impõe

3.000 máquinas × ~150 programas = **450 mil linhas**. Se cada coleta
reinserir tudo, em uma semana são milhões de linhas e o banco vira lixo.

A estratégia aqui é **substituir**, não acumular:

1. deduplica o que veio (o registro do Windows repete entradas)
2. apaga o que o **agente** gravou para aquele ativo
3. insere o conjunto novo em um único lote

Uma transação, dois comandos por máquina. Sem consulta por item.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.software import SoftwareInstalado

log = logging.getLogger(__name__)

# Teto por máquina. Um Windows de estação tem entre 100 e 250 programas;
# um servidor com muitos runtimes pode passar de 400. Acima disso é payload
# corrompido ou tentativa de encher o banco — os dois merecem recusa.
MAX_ITENS = 500

# Tamanho dos campos, iguais aos da coluna. Cortar aqui evita que um nome
# gigante derrube o lote inteiro no PostgreSQL.
MAX_NOME = 200
MAX_VERSAO = 80
MAX_FABRICANTE = 160

ORIGEM_AGENTE = "agente"


def _limpar(valor, limite: int) -> str:
    """Normaliza um campo, garantindo string não vazia e dentro do limite."""
    if valor is None:
        return ""
    return str(valor).strip()[:limite]


def registrar_software(
    db: Session,
    ativo_id: int,
    itens: list[dict],
) -> dict:
    """Substitui a lista de software de um ativo.

    Devolve `{"ok": True, "gravados": n, "descartados": n, "truncado": bool}`.

    ## Duplicatas

    O registro do Windows traz a mesma entrada mais de uma vez (`Wow6432Node`
    repete programas de 32 bits). Deduplicar por `(nome, versão)` em
    minúsculas evita duas linhas para o mesmo programa.

    ## Substituição, não acúmulo

    Apagar e reinserir é mais barato que comparar item a item, e o resultado é
    sempre o estado real da máquina. A alternativa — fazer diff — exigiria
    carregar as linhas antigas e comparar, com o mesmo custo de escrita e mais
    de leitura.
    """
    if not isinstance(itens, list):
        return {"ok": False, "motivo": "formato_invalido"}

    truncado = len(itens) > MAX_ITENS
    vistos: set[tuple[str, str]] = set()
    linhas: list[dict] = []
    descartados = 0

    for item in itens:
        if not isinstance(item, dict):
            descartados += 1
            continue

        nome = _limpar(item.get("nome"), MAX_NOME)
        if not nome:
            descartados += 1
            continue

        chave = (nome.lower(), _limpar(item.get("versao"), MAX_VERSAO).lower())
        if chave in vistos:
            descartados += 1
            continue
        vistos.add(chave)

        linhas.append({
            "ativo_id": ativo_id,
            "nome": nome,
            "versao": chave[1],
            "fabricante": _limpar(item.get("fabricante"), MAX_FABRICANTE) or None,
            "dominio": item.get("dominio"),
            "origem": ORIGEM_AGENTE,
            "coletado_em": datetime.now(timezone.utc),
        })

        if len(linhas) >= MAX_ITENS:
            break

    # Só o que o agente gravou. O que veio do OCS fica: enquanto a migração
    # não termina, os dois convivem, e apagar o do OCS perderia histórico.
    db.query(SoftwareInstalado).filter(
        SoftwareInstalado.ativo_id == ativo_id,
        SoftwareInstalado.origem == ORIGEM_AGENTE,
    ).delete(synchronize_session=False)

    if linhas:
        # `bulk_insert_mappings` monta um único INSERT com N tuplas — é o que
        # permite 150 programas caberem em uma ida ao banco em vez de 150.
        db.bulk_insert_mappings(SoftwareInstalado, linhas)

    db.commit()

    return {
        "ok": True,
        "gravados": len(linhas),
        "descartados": descartados,
        "truncado": truncado,
    }
