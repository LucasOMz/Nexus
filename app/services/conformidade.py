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
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
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

    ## Por que também remove acento

    Num sistema em português, `Antivírus`, `Configuração`, `Impressão` e
    `Aplicação` são comuns. O OCS reporta com acento; o operador digita o
    padrão sem (`antivirus*`) — e os dois **não casavam**.

    A consequência era o número mentindo: o software sumia da contagem de
    instalados e aparecia como "sem licença", ou o inverso. Nenhum dos dois
    dá erro — só leva a decidir errado.

    ## O que NÃO é alterado

    O **nome original continua gravado** em `softwares_instalados.nome`. Esta
    função só padroniza para comparar; a tela mostra o texto como o OCS
    mandou, com acento. Sem isso, a evidência de por que uma instalação
    contou (ou não) se perderia.

    A normalização é a mesma dos dois lados — nome instalado e padrão — então
    `Aplicação` e `Aplicacao` passam a ser o mesmo, que é o comportamento
    desejado: são o mesmo programa escrito de duas formas.
    """
    if not nome:
        return ""
    # NFD separa a letra do acento; descartar os "combining marks" devolve a
    # letra base. `ç` vira `c`, `ã` vira `a` — e a comparação fica estável.
    decomposto = unicodedata.normalize("NFD", nome)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acento.strip().lower().split())


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



def usuarios_distintos(db: Session, software_id: int) -> int:
    """Quantas PESSOAS distintas usam este software.

    ## Por que não vem do OCS

    `Ativo` não guarda quem usa a máquina. O OCS sabe que o programa está
    instalado no computador da Maria — e não que é a Maria quem o usa.

    Então a contagem por pessoa vem das **atribuições**: quem foi designado.
    Depende de alguém ter registrado, e é o único dado que existe para isso.

    Conta `usuario_id` distinto: duas licenças atribuídas à mesma pessoa
    somam **uma**, que é o ponto de medir por pessoa.
    """
    from app.models.software import AtribuicaoLicenca
    from app.models.software import Licenca as _Licenca

    return (
        db.query(func.count(func.distinct(AtribuicaoLicenca.usuario_id)))
        .join(_Licenca, _Licenca.id == AtribuicaoLicenca.licenca_id)
        .filter(
            _Licenca.software_id == software_id,
            _Licenca.deleted_at.is_(None),
            AtribuicaoLicenca.deleted_at.is_(None),
            AtribuicaoLicenca.usuario_id.isnot(None),
        )
        .scalar()
        or 0
    )


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

        # A MÉTRICA decide o que se compara.
        #
        # Por dispositivo: instalações contadas pelo OCS — o que ele sabe
        # medir. Por pessoa: atribuições a usuários distintos, porque o OCS
        # não sabe de quem é a máquina (`Ativo` não tem responsável).
        #
        # A licença manda. Se alguma do software é por pessoa, a comparação
        # é por pessoa: misturar as unidades na mesma linha daria um número
        # sem significado — 11 máquinas contra 10 pessoas.
        por_pessoa = any(
            getattr(lic.metrica, "value", lic.metrica) == "usuario"
            for lic in vivas
        )
        if por_pessoa:
            instalado = usuarios_distintos(db, s.id)

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
            # Como esta linha foi contada. A tela mostra, para o número ser
            # interpretável: 11 pessoas e 11 máquinas são a mesma cifra e
            # significam coisas diferentes.
            "metrica": "usuario" if por_pessoa else "dispositivo",
            "metrica": "usuario" if por_pessoa else "dispositivo",
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

    # --- T11: a explicação, que é o que faz o relatório decidir ---------
    #
    # O número sozinho (+13) não diz se a ação é comprar licença ou corrigir
    # cadastro — e as duas custam coisas muito diferentes. A explicação
    # distingue; a `acao` diz o próximo passo.
    padroes_por_software = {s.id: s.lista_de_padroes() for s in softwares}
    for linha in linhas:
        linha.update(
            explicar(linha, padroes_por_software.get(linha["software_id"], []))
        )

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



def explicar(linha: dict, padroes: list[str]) -> dict:
    """A causa da situação, a ação recomendada e os padrões tentados.

    ## Por que a explicação importa mais que o número

    `+13` sozinho não diz o que fazer. A diferença entre **comprar 13
    licenças** e **corrigir um padrão** é de milhares de reais — e o número
    não distingue as duas.

    A explicação distingue, e a `acao` diz o próximo passo.
    """
    situacao = linha["situacao"]
    lic = linha["licenciado"]
    inst = linha["instalado"]
    diff = abs(linha["diferenca"])
    por_pessoa = linha.get("metrica") == "usuario"
    unidade = "pessoa(s)" if por_pessoa else "máquina(s)"

    if situacao == SituacaoConformidade.CONFORME:
        explicacao = (
            f"{inst} {unidade} em uso para {lic} seat(s) — dentro do "
            f"licenciado."
        )
        acao = "Nada a fazer."

    elif situacao == SituacaoConformidade.EXCEDENTE:
        explicacao = (
            f"{inst} {unidade} em uso e apenas {lic} seat(s) comprado(s). "
            f"{diff} acima do licenciado."
        )
        # A ação muda conforme a métrica — e é aqui que o operador descobre
        # se o problema é compra ou cadastro.
        acao = (
            "Comprar mais seats, ou revisar: parte do uso pode estar "
            "atribuída a quem não precisa."
        )

    elif situacao == SituacaoConformidade.SEM_LICENCA:
        if lic == 0 and inst == 0:
            explicacao = "Software obrigatório que não está instalado em nenhuma máquina."
            acao = "Verificar por que a instalação não foi feita."
        else:
            explicacao = (
                f"{inst} {unidade} com o programa instalado e **nenhuma "
                f"licença cadastrada**."
            )
            acao = (
                "Cadastrar a licença se ela existe, ou **confirmar que o "
                "padrão de reconhecimento está certo** antes de comprar — "
                "pode ser software livre ou cadastro faltando."
            )

    elif situacao == SituacaoConformidade.OCIOSO:
        explicacao = (
            f"{lic} seat(s) comprado(s) e {inst} {unidade} em uso — "
            f"{diff} sem uso."
        )
        acao = (
            "Seats livres. Verificar se há demanda represada ou se a compra "
            "foi maior que o necessário."
        )
    else:
        explicacao = "Cadastrado, sem uso e sem licença."
        acao = "Revisar o cadastro."

    return {
        "explicacao": explicacao,
        "acao": acao,
        "padroes": padroes,
        # Quando não casou nada, os padrões são a pista mais útil: quase
        # sempre o problema está neles, e não na licença.
        "alerta_padrao": (
            "Nenhum nome do OCS casou com os padrões deste software. "
            "Os números acima podem estar incompletos."
            if (not linha.get("origens") and padroes and inst == 0)
            else None
        ),
    }

def ordenar(linhas: list[dict]) -> list[dict]:
    """O que preocupa primeiro.

    A tela abre por aqui: quem entra quer saber se está em risco, não quantos
    títulos existem. Ordenar por nome enterraria o problema na página 4.
    """
    return sorted(linhas, key=lambda x: (_peso(x), -abs(x["diferenca"])))


def ultima_coleta(db: Session) -> datetime | None:
    """Quando o OCS reportou software pela última vez.

    ## Por que não é datetime.now()

    A tela mostrava a hora em que ela mesma foi consultada — e não a hora em
    que o dado foi coletado. Um inventário de três meses aparecia como
    recém-atualizado.

    **É o pior tipo de data errada: tranquiliza.** Quem lê conclui que o dado
    é fresco e decide em cima dele. Devolver None quando não há coleta é
    mais honesto que devolver a hora atual.
    """
    from app.models.software import SoftwareInstalado

    return (
        db.query(func.max(SoftwareInstalado.coletado_em))
        .filter(SoftwareInstalado.deleted_at.is_(None))
        .scalar()
    )



def para_csv(linhas: list[dict]) -> str:
    """O relatório em CSV, para abrir no Excel e levar para reunião.

    Separador `;` e decimal `,` — o padrão do Excel em português. Com vírgula,
    o arquivo abre com as colunas todas grudadas numa só, e quem recebe
    conclui que o sistema exporta errado.

    O BOM no começo é o que faz o acento aparecer certo no Excel do Windows.
    """
    import csv
    import io as _io

    buf = _io.StringIO()
    campos = [
        "software", "fabricante", "licenciado", "instalado", "diferenca",
        "situacao", "metrica", "explicacao", "acao", "padroes", "origens",
    ]
    w = csv.DictWriter(buf, fieldnames=campos, delimiter=";",
                       extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    for linha in linhas:
        registro = dict(linha)
        registro["padroes"] = "; ".join(linha.get("padroes") or [])
        registro["origens"] = "; ".join(linha.get("origens") or [])
        w.writerow(registro)

    return "\ufeff" + buf.getvalue()

def resumo(linhas: list[dict], coletado_em: datetime | None = None) -> dict:
    """Os números do topo da tela.

    coletado_em é a data REAL da coleta no OCS — ver ultima_coleta. O
    padrão None significa "nunca coletado", e é a resposta certa quando
    não houve coleta nenhuma.
    """
    return {
        "titulos": len(linhas),
        "excedente": sum(1 for x in linhas if x["situacao"] == SituacaoConformidade.EXCEDENTE),
        "ocioso": sum(1 for x in linhas if x["situacao"] == SituacaoConformidade.OCIOSO),
        "sem_licenca": sum(1 for x in linhas if x["situacao"] == SituacaoConformidade.SEM_LICENCA),
        "custo_mensal": sum((x["custo_mensal"] for x in linhas), Decimal("0")),
        "atualizado_em": coletado_em,
    }
