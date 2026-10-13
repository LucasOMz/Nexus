"""Libera valores únicos presos em registros excluídos.

## O problema

O sistema usa **soft delete**: excluir marca `deleted_at` e o registro some
da tela — mas **continua na tabela**. E as constraints `UNIQUE` do banco não
sabem disso: elas valem para todas as linhas.

Resultado, do ponto de vista de quem usa:

    1. Exclui o ativo de patrimônio "TI-001"     → some da lista
    2. Cadastra de novo o patrimônio "TI-001"    → 409
       "Já existe um registro com esse valor."

**A mensagem contradiz a tela.** O usuário acabou de ver que não existe
nada ali, e o sistema diz que existe.

## Por que não basta remover o `unique` do modelo

Porque isso não altera os bancos que **já existem**. E no SQLite o índice
automático que implementa `UNIQUE` numa coluna **não pode ser removido** —
seria preciso recriar a tabela inteira.

Esta solução funciona em banco já instalado, sem migração, e nos dois bancos.

## O que ela faz

Antes de gravar um valor único, procura **registros excluídos** que o estejam
ocupando e os **renomeia**, liberando o valor. O registro excluído continua
lá — com todo o histórico — só deixa de bloquear o nome.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

# Sufixo aplicado ao registro excluído. O `#id` no fim é o que garante que
# ele continue único: dois ativos com o mesmo patrimônio, excluídos em
# momentos diferentes, não colidem entre si.
SUFIXO = " (excluído #{id})"


def liberar(
    db: Session,
    modelo: Any,
    campo: str,
    valor: Any,
    limite: int | None = None,
) -> int:
    """Libera `valor` de registros excluídos. Devolve quantos foram renomeados.

    ## Quando chamar

    Antes de inserir um registro novo com um campo `UNIQUE`, **depois** de a
    checagem da aplicação (que só olha os vivos) ter passado. Se a checagem
    passou e o banco ainda reclama, é porque um excluído está segurando o
    valor — é exatamente este caso.

    ## Por que não chamar antes da checagem

    Porque renomear um registro excluído é uma alteração. Se o cadastro for
    recusado por outro motivo, a alteração teria sido feita à toa. Chamando
    depois, só se mexe no que vai ser efetivamente recadastrado.

    ## `limite`

    Tamanho máximo da coluna (`VARCHAR(n)`). O PostgreSQL **recusa** o que
    passa; o SQLite aceita, e a diferença apareceria só em produção. Quando
    informado, o nome original é encurtado para o sufixo caber.
    """
    if valor is None or valor == "":
        return 0

    presos = (
        db.query(modelo)
        .filter(getattr(modelo, campo) == valor, modelo.deleted_at.isnot(None))
        .all()
    )
    if not presos:
        return 0

    for antigo in presos:
        sufixo = SUFIXO.format(id=antigo.id)
        nome = str(valor)
        if limite and len(nome) + len(sufixo) > limite:
            # Encurta com folga para o sufixo: sem isto, o PostgreSQL
            # recusaria o UPDATE e o problema trocaria de lugar em vez de
            # ser resolvido.
            nome = nome[: max(1, limite - len(sufixo))]
        setattr(antigo, campo, f"{nome}{sufixo}")

    db.flush()
    return len(presos)
