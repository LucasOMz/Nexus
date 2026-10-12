"""Conformidade: cruzamento entre o que está instalado e o que foi comprado.

## Por que este é o módulo que justifica o inventário de software

Uma lista de licenças é um cadastro. O que a gestão precisa saber é outra
coisa:

    Temos 50 licenças de Office e 63 máquinas com ele instalado.
    Estamos 13 acima — e isso é risco em auditoria.

## ⚠️ O detalhe que faz ou quebra tudo

**Comparar por nome exato não acha nada.**

O OCS reporta `Microsoft Office LTSC Professional Plus 2021`.
A licença está cadastrada como `Office 2021`.
`"office ltsc professional plus 2021" == "office 2021"` é `False`.

Um relatório que não casa nada não é um relatório com zero problemas — é um
relatório **quebrado que parece limpo**. A pessoa olha, vê tudo conforme, e
conclui que está tudo bem.

Por isso cada `Software` guarda **padrões de reconhecimento**
(`microsoft office*2021`), e o casamento é por curinga, sem diferenciar
maiúsculas.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.core import Ativo
from app.models.enums import SituacaoConformidade, TipoLicenca
from app.models.software import (
    AtribuicaoLicenca,
    Licenca,
    Software,
    SoftwareInstalado,
)


def normalizar(nome: str | None) -> str:
    """Padroniza um nome de software para comparação.

    O OCS varia maiúsculas, espaços duplos e sufixos de versão entre
    coletas — a comparação não pode depender disso.
    """
    if not nome:
        return ""
    return " ".join(nome.strip().lower().split())


def casa(nome_instalado: str, padroes: list[str]) -> bool:
    """O nome instalado corresponde a algum dos padrões?

    ## Por que curinga, e não igualdade

    O nome que o OCS reporta carrega edição, idioma e sufixo de build:
    `Microsoft Office LTSC Professional Plus 2021 - pt-br`. Exigir igualdade
    obrigaria a cadastrar uma variação por idioma.

    Com `*`, o padrão `microsoft office*2021*` cobre todas — e é o que o
    operador consegue escrever sem consultar a lista do OCS.
    """
    alvo = normalizar(nome_instalado)
    if not alvo:
        return False
    for p in padroes:
        padrao = normalizar(p)
        if not padrao:
            continue
        if "*" in padrao or "?" in padrao:
            # `fnmatch` ancora no início: `acrobat*` NÃO casa
            # `adobe acrobat pro dc`. O nome que o OCS reporta quase sempre
            # começa pelo fabricante, então o padrão precisa valer em
            # QUALQUER posição — daí o `*` dos dois lados.
            alvo_padrao = padrao
            if not alvo_padrao.startswith("*"):
                alvo_padrao = "*" + alvo_padrao
            if not alvo_padrao.endswith("*"):
                alvo_padrao = alvo_padrao + "*"
            if fnmatch.fnmatch(alvo, alvo_padrao):
                return True
        # Sem curinga, exige o trecho contido: assim `office 2021` casa
        # `microsoft office 2021`, que é o caso comum.
        elif padrao in alvo:
            return True
    return False


@dataclass
class Contagem:
    """O que foi encontrado para um software."""

    licenciado: int = 0
    instalado: int = 0
    origens: list[str] = field(default_factory=list)
    custo_mensal: Decimal = Decimal("0")


def situacao(licenciado: int, instalado: int) -> SituacaoConformidade:
    """Classifica o cruzamento.

    ## Por que "ocioso" existe

    Comprar 50 seats e usar 31 é dinheiro parado. Um relatório que só acusa
    excesso esconde a metade do problema — e justamente a metade que ninguém
    procura, porque não há risco legal nela, só financeiro.
    """
    if licenciado == 0 and instalado == 0:
        return SituacaoConformidade.NAO_INSTALADO
    if licenciado == 0:
        # Instalado e nenhuma licença cadastrada. É o caso mais grave, e o
        # que passa batido: não há linha de licença para comparar.
        return SituacaoConformidade.SEM_LICENCA
    if instalado > licenciado:
        return SituacaoConformidade.EXCEDENTE
    if instalado < licenciado:
        return SituacaoConformidade.OCIOSO
    return SituacaoConformidade.CONFORME


def instalados_por_nome(
    db: Session, dominio: str | None = None, planta_id: int | None = None
) -> list[tuple[str, int]]:
    """Nomes instalados e quantas máquinas têm cada um — **do OCS**.

    Agrupado no banco: um parque de 5.000 máquinas pode reportar 300.000
    linhas de software, e trazer isso para a memória só para contar seria
    caro em toda abertura de tela.
    """
    q = (
        db.query(SoftwareInstalado.nome, func.count(func.distinct(SoftwareInstalado.ativo_id)))
        .filter(SoftwareInstalado.deleted_at.is_(None))
        # Sem esta junção, a contagem somava TODAS as plantas: a tela
        # filtrava os softwares, mas o número de instalações misturava
        # as unidades — e continuava parecendo plausível.
        .join(Ativo, Ativo.id == SoftwareInstalado.ativo_id)
        .filter(Ativo.deleted_at.is_(None))
    )
    if planta_id is not None:
        q = q.filter(Ativo.planta_id == planta_id)
    if dominio:
        q = q.filter(SoftwareInstalado.dominio == dominio)
    return q.group_by(SoftwareInstalado.nome).all()


def instalados_das_atribuicoes(db: Session) -> list[tuple[str, int]]:
    """Alternativa ao OCS: o que o operador registrou como em uso.

    ## Por que existe

    Nem toda instalação tem OCS. Sem ele, o cruzamento ficaria vazio — e um
    relatório vazio é lido como "está tudo certo", que é a pior conclusão
    possível.

    Aqui o "instalado" é o que foi **atribuído**: menos exato (depende de
    alguém ter registrado), mas honesto e suficiente para responder quantos
    seats estão livres.

    A chave é o **nome do software**, para o resultado ter a mesma forma do
    caminho do OCS e o resto do código não precisar saber qual dos dois rodou.
    """
    linhas = (
        db.query(Software.nome, func.count(func.distinct(AtribuicaoLicenca.id)))
        .join(Licenca, Licenca.software_id == Software.id)
        .join(AtribuicaoLicenca, AtribuicaoLicenca.licenca_id == Licenca.id)
        .filter(
            Software.deleted_at.is_(None),
            Licenca.deleted_at.is_(None),
            AtribuicaoLicenca.deleted_at.is_(None),
        )
        .group_by(Software.nome)
        .all()
    )
    return linhas



def _licencas_vivas(software: Software) -> list[Licenca]:
    """As licenças que **contam** para conformidade.

    ## Por que não basta `deleted_at is None`

    Uma licença pode estar no banco e não valer mais:

    - **cancelada** — o contrato acabou; os seats não são mais da empresa;
    - **expirada** — a data passou; instalação com ela é uso irregular.

    Contá-las faz o sistema parecer conforme quando não está. É o pior
    resultado possível aqui: a pessoa lê "em conformidade" e não age.

    `suspensa` **conta**, de propósito: suspender é uma decisão temporária
    (disputa de contrato, projeto parado) e os seats continuam contratados.
    Tratá-la como cancelada faria a empresa parecer descoberta quando ainda
    tem o direito.
    """
    from app.models.enums import SituacaoLicenca

    validas = {SituacaoLicenca.ATIVA, SituacaoLicenca.SUSPENSA}
    vivas = []
    for lic in software.licencas:
        if lic.deleted_at is not None:
            continue
        if lic.situacao not in validas:
            continue
        # Vencida só sai quando o tipo realmente vence: perpétua não tem data.
        if lic.vencida:
            continue
        vivas.append(lic)
    return vivas


def calcular(db: Session, softwares: list[Software],
             instalados: list[tuple[str, int]] | None = None) -> list[dict]:
    """Cruza a lista de softwares cadastrados com o que está instalado.

    Devolve uma linha por software, já classificada. Os softwares cadastrados
    que não casam com nada aparecem com `instalado = 0` — **não são
    escondidos**, porque "compramos e ninguém usa" é informação.
    """
    if instalados is None:
        instalados = instalados_por_nome(db)

    # Cada nome instalado é atribuído a NO MÁXIMO um software: o primeiro que
    # casar, na ordem de cadastro. Sem isso, um padrão genérico (`*office*`)
    # faria o mesmo parque contar duas vezes, dobrando o número de instalações.
    consumo: dict[int, int] = {}
    origens: dict[int, list[str]] = {}
    usados: set[str] = set()

    for s in softwares:
        padroes = s.lista_de_padroes()
        if not padroes:
            continue
        for nome, quantas in instalados:
            if nome in usados or not casa(nome, padroes):
                continue
            usados.add(nome)
            consumo[s.id] = consumo.get(s.id, 0) + quantas
            origens.setdefault(s.id, []).append(nome)

    linhas = []
    for s in softwares:
        vivas = _licencas_vivas(s)
        licenciado = sum(lic.seats for lic in vivas)
        custo = sum(
            (lic.valor_mensal or Decimal("0")) for lic in vivas
            if lic.tipo == TipoLicenca.ASSINATURA
        )
        instalado = consumo.get(s.id, 0)

        # Um software OBRIGATÓRIO que não está instalado é a pendência mais
        # importante que este relatório pode mostrar: alguém decidiu que ele
        # deveria estar em toda máquina, e não está em nenhuma.
        #
        # Sem esta exceção, o `continue` abaixo descartava exatamente esse
        # caso — e o campo `obrigatorio` nunca produzia o que promete.
        if licenciado == 0 and instalado == 0 and not s.obrigatorio:
            continue  # cadastrado, sem uso e sem licença: não é linha de risco

        linhas.append({
            "software_id": s.id,
            "software": s.nome,
            "fabricante": s.fabricante,
            "licenciado": licenciado,
            "instalado": instalado,
            "diferenca": instalado - licenciado,
            "situacao": situacao(licenciado, instalado),
            "origens": origens.get(s.id, [])[:8],
            "obrigatorio": bool(s.obrigatorio),
            "custo_mensal": custo,
        })

    # Instalado e NÃO reconhecido por nenhum software cadastrado. É o caso
    # que nenhum relatório tradicional mostra: não há licença para comparar,
    # então nada acusa — e é uso irregular.
    for nome, quantas in instalados:
        if nome in usados:
            continue
        linhas.append({
            "software_id": 0,
            "software": nome,
            "fabricante": None,
            "licenciado": 0,
            "instalado": quantas,
            "diferenca": quantas,
            "situacao": SituacaoConformidade.SEM_LICENCA,
            "origens": [nome],
            "custo_mensal": Decimal("0"),
            "obrigatorio": False,
        })

    return linhas


def _peso(linha: dict) -> int:
    """Obrigatório ausente preocupa mais que qualquer outra linha.

    É a única situação em que a empresa decidiu que algo deveria estar em
    toda máquina e **não está em nenhuma** — e o campo `obrigatorio` existe
    justamente para isso aparecer.
    """
    if linha.get("obrigatorio") and linha.get("instalado", 0) == 0:
        return -1
    return ORDEM.get(linha["situacao"], 9)


ORDEM = {
    SituacaoConformidade.EXCEDENTE: 0,
    SituacaoConformidade.SEM_LICENCA: 1,
    SituacaoConformidade.OCIOSO: 2,
    SituacaoConformidade.CONFORME: 3,
    SituacaoConformidade.NAO_INSTALADO: 4,
}


def ordenar(linhas: list[dict]) -> list[dict]:
    """O que preocupa primeiro.

    A tela abre por aqui: quem entra quer saber se está em risco, não quantos
    títulos existem. Ordenar por nome enterraria o problema na página 4.
    """
    return sorted(linhas, key=lambda x: (_peso(x), -abs(x["diferenca"])))


def resumo(linhas: list[dict]) -> dict:
    """Os números do topo da tela."""
    return {
        "titulos": len(linhas),
        "excedente": sum(1 for x in linhas if x["situacao"] == SituacaoConformidade.EXCEDENTE),
        "ocioso": sum(1 for x in linhas if x["situacao"] == SituacaoConformidade.OCIOSO),
        "sem_licenca": sum(1 for x in linhas if x["situacao"] == SituacaoConformidade.SEM_LICENCA),
        "custo_mensal": sum((x["custo_mensal"] for x in linhas), Decimal("0")),
        "atualizado_em": datetime.now(timezone.utc),
    }
