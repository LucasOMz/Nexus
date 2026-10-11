"""Coleta do software instalado no OCS Inventory.

## Por que é um serviço separado

`ocs_service` cuida do **hardware** — sincroniza máquinas, série, SO, disco.
Aqui é a lista de **programas**, que é outra ordem de grandeza: uma máquina
tem dezenas, então 5.000 máquinas significam ~300.000 linhas.

Separar mantém o caminho que já funciona intocado, e permite rodar esta
coleta noutro horário — ela é bem mais pesada.

## O que esta coleta faz

```
OCS  /ocsapi/v1/computer/{id}/software
        │
        ├─ grava em `softwares_instalados` (nome como veio)
        └─ casa com `Software.padroes` → grava `software_id`
```

O casamento acontece **na coleta**, e não a cada consulta: com 300 mil
linhas, refazer o cruzamento toda vez que alguém abre a tela seria inviável.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.core import Ativo
from app.models.software import Software, SoftwareInstalado
from app.models.ti import AtivoTI
from app.services import conformidade, ocs_service

log = logging.getLogger(__name__)

# Pausa entre as chamadas de software. O OCS é um servidor PHP que costuma
# rodar junto de outras coisas — puxar 5.000 listas sem respiro derruba ele.
PAUSA = 0.05


def _nome(item: dict) -> str | None:
    """Extrai o nome do software de um item do OCS.

    O OCS varia o rótulo entre versões e entre agentes (`NAME`, `name`,
    `pubname`…). Tentar as chaves conhecidas é mais barato que exigir um
    formato — e um formato exigido seria quebrado na próxima versão do OCS.
    """
    for chave in ("name", "NAME", "Name", "pubname", "software", "nome"):
        valor = item.get(chave)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return None


def _versao(item: dict) -> str | None:
    for chave in ("version", "VERSION", "Version", "versao"):
        valor = item.get(chave)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return None


def _fabricante(item: dict) -> str | None:
    for chave in ("publisher", "PUBLISHER", "Publisher", "fabricante", "editor"):
        valor = item.get(chave)
        if isinstance(valor, str) and valor.strip():
            return valor.strip()
    return None


def listar_softwares(cfg: Any, maquina_id: Any) -> list[dict]:
    """A lista de programas de uma máquina. Tolerante a falha.

    Uma máquina que não responde não pode derrubar a coleta inteira — ela
    simplesmente não contribui, e o resumo mostra quantas falharam.
    """
    try:
        with ocs_service._cliente(cfg) as cli:
            r = cli.get(f"/ocsapi/v1/computer/{maquina_id}/software")
            if r.status_code != 200:
                return []
            dados = r.json()
    except Exception as e:  # noqa: BLE001 - a coleta não pode parar por uma máquina
        log.debug("OCS: software de %s falhou: %s", maquina_id, e)
        return []

    if isinstance(dados, dict):
        for chave in ("software", "data", "items", "results"):
            if isinstance(dados.get(chave), list):
                return dados[chave]
        return []
    return dados if isinstance(dados, list) else []


@dataclass
class Resumo:
    """O que a coleta produziu. Vai para o log e para o resumo da sync."""

    maquinas: int = 0
    com_software: int = 0
    instalados: int = 0
    reconhecidos: int = 0
    sem_ativo: int = 0
    falhas: int = 0
    nomes: set[str] = field(default_factory=set)

    def como_dict(self) -> dict:
        return {
            "maquinas": self.maquinas,
            "com_software": self.com_software,
            "instalados": self.instalados,
            "reconhecidos": self.reconhecidos,
            "sem_ativo": self.sem_ativo,
            "falhas": self.falhas,
            "nomes_distintos": len(self.nomes),
        }


def _mapa_de_padroes(db: Session) -> list[tuple[int, list[str]]]:
    """(software_id, padroes) de todos os softwares cadastrados."""
    softwares = db.query(Software).filter(Software.deleted_at.is_(None)).all()
    return [(s.id, s.lista_de_padroes()) for s in softwares if s.lista_de_padroes()]


def _reconhecer(nome: str, mapa: list[tuple[int, list[str]]]) -> int | None:
    """Qual software cadastrado reconhece este nome. Nulo = nenhum."""
    for software_id, padroes in mapa:
        if conformidade.casa(nome, padroes):
            return software_id
    return None


def coletar(
    db: Session,
    cfg: Any,
    *,
    limite: int | None = None,
    substituir: bool = True,
) -> Resumo:
    """Coleta o software de todas as máquinas inventariadas.

    ## `substituir`

    A lista de uma máquina é **substituída** a cada coleta, e não somada. Um
    programa desinstalado precisa sair do relatório — se as coletas
    acumulassem, a conformidade passaria a acusar instalações que não existem
    mais, e o número só cresceria.

    ## Máquinas sem ativo correspondente

    Contadas em `sem_ativo`. Um OCS que reporta máquinas que o inventário não
    conhece é um problema de sincronização de hardware, e não de software —
    misturar os dois esconderia qual dos dois está falhando.
    """
    resumo = Resumo()
    mapa = _mapa_de_padroes(db)

    # Só as máquinas de TI: impressora não tem lista de programas.
    pares = (
        db.query(AtivoTI.ocs_id, AtivoTI.ativo_id)
        .join(Ativo, Ativo.id == AtivoTI.ativo_id)
        .filter(AtivoTI.ocs_id.isnot(None), Ativo.deleted_at.is_(None))
        .all()
    )
    if limite:
        pares = pares[:limite]

    for ocs_id, ativo_id in pares:
        resumo.maquinas += 1
        itens = listar_softwares(cfg, ocs_id)

        if not itens:
            resumo.falhas += 1
            continue

        if substituir:
            db.query(SoftwareInstalado).filter(
                SoftwareInstalado.ativo_id == ativo_id,
                SoftwareInstalado.origem == "ocs",
            ).delete(synchronize_session=False)

        agora = datetime.now(timezone.utc)
        vistos: set[str] = set()
        quantos = 0

        for item in itens:
            if not isinstance(item, dict):
                continue
            nome = _nome(item)
            if not nome:
                continue
            # O OCS repete o mesmo programa (atualizações lado a lado).
            chave = conformidade.normalizar(nome) + "|" + (conformidade.normalizar(_versao(item)))
            if chave in vistos:
                continue
            vistos.add(chave)

            software_id = _reconhecer(nome, mapa)
            db.add(SoftwareInstalado(
                ativo_id=ativo_id, nome=nome, versao=_versao(item),
                fabricante=_fabricante(item), dominio="ti", origem="ocs",
                coletado_em=agora, software_id=software_id,
            ))
            quantos += 1
            resumo.instalados += 1
            resumo.nomes.add(nome)
            if software_id:
                resumo.reconhecidos += 1

        if quantos:
            resumo.com_software += 1

        db.commit()
        time.sleep(PAUSA)

    return resumo


def aplicar_reconhecimento(db: Session) -> int:
    """Recasa o que já está gravado com os padrões atuais.

    ## Por que isto é separado da coleta

    Ajustar um padrão em `Software` precisa refletir no que já foi coletado —
    sem isso, cadastrar o padrão certo só valeria na **próxima** coleta, e o
    operador acharia que a correção não funcionou.

    Não toca no OCS: trabalha só no banco.
    """
    mapa = _mapa_de_padroes(db)
    if not mapa:
        return 0

    # Só os nomes distintos: recasar 300 mil linhas idênticas é desperdício.
    nomes = [
        n for (n,) in db.query(SoftwareInstalado.nome)
        .filter(SoftwareInstalado.deleted_at.is_(None))
        .distinct().all()
    ]

    decisao = {n: _reconhecer(n, mapa) for n in nomes}

    mudados = 0
    for nome, software_id in decisao.items():
        mudados += (
            db.query(SoftwareInstalado)
            .filter(
                SoftwareInstalado.nome == nome,
                SoftwareInstalado.software_id.is_(None),
                SoftwareInstalado.deleted_at.is_(None),
            )
            .update({"software_id": software_id}, synchronize_session=False)
            if software_id else 0
        )

    db.commit()
    return mudados


def resumo_do_banco(db: Session) -> dict:
    """O que já está gravado — para conferir sem refazer a coleta."""
    from sqlalchemy import func

    q = db.query(SoftwareInstalado).filter(SoftwareInstalado.deleted_at.is_(None))
    total = q.count()
    distintos = db.query(func.count(func.distinct(SoftwareInstalado.nome))).filter(
        SoftwareInstalado.deleted_at.is_(None)
    ).scalar()
    reconhecidos = q.filter(SoftwareInstalado.software_id.isnot(None)).count()
    maquinas = db.query(func.count(func.distinct(SoftwareInstalado.ativo_id))).filter(
        SoftwareInstalado.deleted_at.is_(None)
    ).scalar()

    return {
        "instalados": total,
        "nomes_distintos": distintos or 0,
        "reconhecidos": reconhecidos,
        "sem_reconhecimento": total - reconhecidos,
        "maquinas": maquinas or 0,
        # A proporção é o indicador de saúde: baixa significa padrões fracos,
        # e o relatório de conformidade vai mostrar muito "sem licença".
        "taxa_reconhecimento": round(reconhecidos / total, 3) if total else 0.0,
    }
