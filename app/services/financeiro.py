"""Camada financeira: depreciação, garantia, TCO, rateio e custo por página.

Tudo aqui é **derivado** do que já existe no banco — `Ativo.valor`,
`data_aquisicao`, `data_garantia`, `departamento_id`, `Manutencao.custo` e
`Produto.preco_unitario`. Nenhuma coluna nova foi necessária, e nenhum dado
precisa ser digitado duas vezes: se o valor da compra está no cadastro, a
depreciação sai dele.

As funções são **puras** e recebem `agora` por parâmetro, para os testes não
dependerem do relógio.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

# Taxa de depreciação linear ao ano, por tipo de bem.
#
# Valores usuais na prática contábil brasileira para bens de informática:
# computadores e periféricos depreciam rápido (vida útil ~5 anos), impressoras
# são mais duráveis (~10 anos). São PADRÕES: cada empresa pode ter o seu, e o
# parâmetro existe para isso.
TAXA_PADRAO = {
    "ti": 20.0,          # 5 anos
    "impressora": 10.0,  # 10 anos
}
TAXA_FALLBACK = 20.0

# Abaixo disso o bem é considerado sem valor contábil.
VALOR_RESIDUAL_PADRAO = 0.0


def _data(valor: Any) -> date | None:
    """Aceita date, datetime ou texto ISO."""
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


def _hoje(agora: datetime | None) -> date:
    return (agora or datetime.now(timezone.utc)).date()


def _anos_decorridos(inicio: date, hoje: date) -> float:
    return max(0.0, (hoje - inicio).days / 365.25)


def taxa_do_dominio(dominio: str | None) -> float:
    return TAXA_PADRAO.get((dominio or "").lower(), TAXA_FALLBACK)


def depreciacao(
    valor: float | None,
    data_aquisicao: Any,
    taxa_anual: float | None = None,
    dominio: str | None = None,
    residual: float = VALOR_RESIDUAL_PADRAO,
    agora: datetime | None = None,
) -> dict[str, Any]:
    """Valor atual do bem pela depreciação linear.

    Devolve também quanto já foi depreciado e o percentual — o relatório
    precisa dos três para ser útil, não só do valor final.
    """
    v = float(valor or 0)
    if v <= 0:
        return {"aplicavel": False, "motivo": "sem valor de aquisição"}

    inicio = _data(data_aquisicao)
    if inicio is None:
        return {"aplicavel": False, "motivo": "sem data de aquisição"}

    hoje = _hoje(agora)
    if inicio > hoje:
        return {"aplicavel": False, "motivo": "data de aquisição no futuro"}

    taxa = taxa_anual if taxa_anual is not None else taxa_do_dominio(dominio)
    anos = _anos_decorridos(inicio, hoje)
    perda_pct = min(100.0, taxa * anos)

    piso = max(0.0, float(residual or 0))
    atual = max(piso, v * (1 - perda_pct / 100))
    # Não se deprecia abaixo do residual.
    perda_pct = min(perda_pct, ((v - atual) / v * 100) if v else 0)

    return {
        "aplicavel": True,
        "valor_aquisicao": round(v, 2),
        "valor_atual": round(atual, 2),
        "depreciado": round(v - atual, 2),
        "percentual_depreciado": round(perda_pct, 1),
        "anos_decorridos": round(anos, 2),
        "taxa_anual": taxa,
        "totalmente_depreciado": atual <= piso + 0.01,
    }


def garantia(data_garantia: Any, agora: datetime | None = None) -> dict[str, Any]:
    """Situação da garantia — o que evita pagar reparo que estava coberto."""
    fim = _data(data_garantia)
    if fim is None:
        return {"informada": False, "dias_restantes": None, "situacao": "nao_informada"}

    dias = (fim - _hoje(agora)).days
    if dias < 0:
        situacao = "vencida"
    elif dias <= 30:
        situacao = "vencendo"
    elif dias <= 90:
        situacao = "atencao"
    else:
        situacao = "vigente"

    return {
        "informada": True,
        "data": fim.isoformat(),
        "dias_restantes": dias,
        "situacao": situacao,
        "sob_garantia": dias >= 0,
        # A pergunta que o gestor faz de verdade.
        "economia_potencial": dias >= 0,
    }


def tco(
    valor: float | None,
    custo_manutencao: float = 0.0,
    custo_consumiveis: float = 0.0,
    agora: datetime | None = None,
    data_aquisicao: Any = None,
) -> dict[str, Any]:
    """Custo total de propriedade: compra + manutenção + consumíveis.

    Devolve o custo por mês quando há data de aquisição — é o número que
    permite comparar um equipamento novo com um antigo que dá problema.
    """
    v = float(valor or 0)
    m = float(custo_manutencao or 0)
    c = float(custo_consumiveis or 0)
    total = v + m + c

    saida = {
        "valor_aquisicao": round(v, 2),
        "custo_manutencao": round(m, 2),
        "custo_consumiveis": round(c, 2),
        "total": round(total, 2),
        "manutencao_sobre_aquisicao": (
            round((m / v) * 100, 1) if v > 0 else None
        ),
    }

    inicio = _data(data_aquisicao)
    if inicio is not None:
        meses = max(1.0, (_hoje(agora) - inicio).days / 30.44)
        saida["meses_de_uso"] = round(meses, 1)
        saida["custo_por_mes"] = round(total / meses, 2)

    return saida


def rateio_por_departamento(itens: list[dict], agora: datetime | None = None) -> list[dict]:
    """Quanto cada centro de custo consome.

    `itens`: dicts com `departamento`, `valor`, `custo_manutencao`,
    `custo_consumiveis`, `data_aquisicao`, `dominio`.
    """
    grupos: dict[str, dict] = {}

    for it in itens:
        chave = it.get("departamento") or "Sem departamento"
        g = grupos.setdefault(chave, {
            "departamento": chave,
            "ativos": 0,
            "valor_aquisicao": 0.0,
            "valor_depreciado": 0.0,
            "custo_manutencao": 0.0,
            "custo_consumiveis": 0.0,
        })
        g["ativos"] += 1
        g["valor_aquisicao"] += float(it.get("valor") or 0)
        g["custo_manutencao"] += float(it.get("custo_manutencao") or 0)
        g["custo_consumiveis"] += float(it.get("custo_consumiveis") or 0)

        d = depreciacao(it.get("valor"), it.get("data_aquisicao"),
                        dominio=it.get("dominio"), agora=agora)
        if d["aplicavel"]:
            g["valor_depreciado"] += d["depreciado"]

    saida = []
    for g in grupos.values():
        for campo in ("valor_aquisicao", "valor_depreciado",
                      "custo_manutencao", "custo_consumiveis"):
            g[campo] = round(g[campo], 2)
        g["valor_atual"] = round(g["valor_aquisicao"] - g["valor_depreciado"], 2)
        g["total"] = round(
            g["valor_aquisicao"] + g["custo_manutencao"] + g["custo_consumiveis"], 2
        )
        saida.append(g)

    # Do que mais custa para o que menos custa: é a ordem em que se age.
    return sorted(saida, key=lambda x: x["total"], reverse=True)


def custo_por_pagina(
    custo_tonner: float | None,
    rendimento_paginas: int | None,
    custo_manutencao: float = 0.0,
    paginas_impressas: int = 0,
    custo_aquisicao: float | None = None,
    vida_util_paginas: int | None = None,
) -> dict[str, Any]:
    """Custo por página de uma impressora.

    O diferencial deste sistema: ele **já tem o contador**. Com o preço do
    tonner e o rendimento, sai o custo por página — e com ele dá para dizer
    qual impressora é cara e qual se paga.

    A depreciação por página (aquisição ÷ vida útil em páginas) é o que a
    maioria dos sistemas não faz: sem ela, o custo por página parece bom e a
    impressora sai caro no fim.
    """
    cpp_tonner = None
    if custo_tonner and rendimento_paginas and rendimento_paginas > 0:
        cpp_tonner = float(custo_tonner) / float(rendimento_paginas)

    cpp_manutencao = None
    if paginas_impressas and paginas_impressas > 0:
        cpp_manutencao = float(custo_manutencao or 0) / float(paginas_impressas)

    cpp_depreciacao = None
    if custo_aquisicao and vida_util_paginas and vida_util_paginas > 0:
        cpp_depreciacao = float(custo_aquisicao) / float(vida_util_paginas)

    partes = [x for x in (cpp_tonner, cpp_manutencao, cpp_depreciacao) if x is not None]

    return {
        "custo_por_pagina_tonner": round(cpp_tonner, 4) if cpp_tonner is not None else None,
        "custo_por_pagina_manutencao": round(cpp_manutencao, 4) if cpp_manutencao is not None else None,
        "custo_por_pagina_depreciacao": round(cpp_depreciacao, 4) if cpp_depreciacao is not None else None,
        "custo_por_pagina_total": round(sum(partes), 4) if partes else None,
        "paginas_impressas": paginas_impressas or 0,
        "custo_total_estimado": (
            round(sum(partes) * paginas_impressas, 2) if partes and paginas_impressas else None
        ),
        # Sem tonner informado não há custo por página confiável.
        "completo": cpp_tonner is not None,
    }


# ===========================================================================
# Locação
# ===========================================================================
# Comprado e locado NÃO se somam. Um tem valor patrimonial que deprecia; o
# outro tem mensalidade e não é bem da empresa. Somar os dois numa métrica só
# ("valor do parque") produz um número sem significado — e é o erro fácil de
# cometer aqui.
# ===========================================================================

# Dias médios do mês gregoriano (365,25 / 12). Usar 30 fixo acumularia 5 dias
# de erro por ano — num contrato de 36 meses, quase meio mês de mensalidade.
DIAS_DO_MES = 30.44


def meses_decorridos(inicio, agora: datetime | None = None) -> float:
    """Meses desde o início da locação.

    Zero quando ainda não começou (contrato com início no futuro): cobrar
    mensalidade de um período que não passou infla o custo.
    """
    d = _data(inicio)
    if d is None:
        return 0.0
    hoje = _hoje(agora)
    if d > hoje:
        return 0.0
    return round((hoje - d).days / DIAS_DO_MES, 2)


def custo_locacao(
    valor_mensal,
    inicio,
    agora: datetime | None = None,
    valor_residual=None,
) -> dict[str, Any]:
    """Custo acumulado de um ativo LOCADO.

    Aqui **não há depreciação**: o equipamento não é patrimônio da empresa, e
    depreciar mediria um bem que não é dela. O que existe é o que já foi pago.

    `valor_residual` não é custo — é o preço do buyout, se um dia for
    exercido. Fica separado para não entrar no custo de quem nunca comprar.
    """
    mensal = float(valor_mensal or 0)
    if mensal <= 0:
        return {
            "aplicavel": False,
            "motivo": "sem valor mensal (comodato ou contrato sem cobrança)",
        }

    d = _data(inicio)
    if d is None:
        return {"aplicavel": False, "motivo": "sem data de início"}

    meses = meses_decorridos(d, agora=agora)

    return {
        "aplicavel": True,
        "valor_mensal": round(mensal, 2),
        "meses": meses,
        "custo_acumulado": round(mensal * meses, 2),
        # Doze meses adiante: o horizonte que a gestão olha para decidir
        # renovação.
        "custo_12_meses": round(mensal * 12, 2),
        "inicio": d.isoformat(),
        "valor_residual": round(float(valor_residual), 2) if valor_residual else None,
        # A depreciação de um locado é ZERO, e não "não calculada": devolver
        # None obrigaria todo relatório que soma a tratar o caso, e um deles
        # esqueceria — virando número errado em relatório de gestão.
        "depreciacao": 0.0,
    }


def resumo_do_parque(itens: list[dict], agora: datetime | None = None) -> dict[str, Any]:
    """Números do parque, **separados por forma de aquisição**.

    Comprado e locado têm naturezas diferentes: um é patrimônio que perde
    valor, o outro é serviço pago todo mês. Somá-los daria um "valor do
    parque" que não corresponde a nada.

    Os totais de contagem continuam existindo; o **dinheiro vem separado**.
    """
    comprado = {
        "ativos": 0, "valor_aquisicao": 0.0, "valor_depreciado": 0.0,
        "valor_atual": 0.0, "custo_manutencao": 0.0,
    }
    locado = {
        "ativos": 0, "custo_acumulado": 0.0, "custo_mensal": 0.0,
        "custo_manutencao": 0.0, "residual_total": 0.0,
    }
    garantias = {"vigente": 0, "atencao": 0, "vencendo": 0, "vencida": 0, "nao_informada": 0}

    for it in itens:
        # `forma_aquisicao` ausente = comprado. É o padrão do campo no banco, e
        # também o certo para quem chama a função só com os campos antigos.
        locado_mesmo = it.get("forma_aquisicao") == "locado"
        manut = float(it.get("custo_manutencao") or 0)

        if locado_mesmo:
            locado["ativos"] += 1
            locado["custo_manutencao"] += manut
            c = custo_locacao(
                it.get("valor_mensal"),
                it.get("contrato_inicio") or it.get("data_aquisicao"),
                agora=agora,
                valor_residual=it.get("valor_residual"),
            )
            if c["aplicavel"]:
                locado["custo_acumulado"] += c["custo_acumulado"]
                locado["custo_mensal"] += c["valor_mensal"]
            if c.get("valor_residual"):
                locado["residual_total"] += c["valor_residual"]

            # Locado não tem garantia própria: quem cobre é o fornecedor, pelo
            # contrato. Contar como "não informada" só poluiria o indicador.
            continue

        comprado["ativos"] += 1
        comprado["custo_manutencao"] += manut
        v = float(it.get("valor") or 0)
        comprado["valor_aquisicao"] += v

        d = depreciacao(v, it.get("data_aquisicao"), dominio=it.get("dominio"), agora=agora)
        if d["aplicavel"]:
            comprado["valor_atual"] += d["valor_atual"]
            comprado["valor_depreciado"] += d["depreciado"]
        else:
            comprado["valor_atual"] += v

        g = garantia(it.get("data_garantia"), agora=agora)
        garantias[g["situacao"]] = garantias.get(g["situacao"], 0) + 1

    # TCO de comprado = o que custou + o que gastou. O de locado é o que já foi
    # pago + manutenção. Não se soma o `valor` de um locado: ele não existe.
    tco_comprado = comprado["valor_aquisicao"] + comprado["custo_manutencao"]
    tco_locado = locado["custo_acumulado"] + locado["custo_manutencao"]

    return {
        "ativos": comprado["ativos"] + locado["ativos"],
        # --- Comprado: patrimônio ---------------------------------------
        "comprado": {
            "ativos": comprado["ativos"],
            "valor_aquisicao": round(comprado["valor_aquisicao"], 2),
            "valor_depreciado": round(comprado["valor_depreciado"], 2),
            "valor_atual": round(comprado["valor_atual"], 2),
            "custo_manutencao": round(comprado["custo_manutencao"], 2),
            "tco": round(tco_comprado, 2),
            "percentual_depreciado": (
                round(comprado["valor_depreciado"] / comprado["valor_aquisicao"] * 100, 1)
                if comprado["valor_aquisicao"] else 0.0
            ),
        },
        # --- Locado: serviço -------------------------------------------
        "locado": {
            "ativos": locado["ativos"],
            "custo_mensal": round(locado["custo_mensal"], 2),
            "custo_acumulado": round(locado["custo_acumulado"], 2),
            "custo_manutencao": round(locado["custo_manutencao"], 2),
            "tco": round(tco_locado, 2),
            "residual_total": round(locado["residual_total"], 2),
            # Doze meses do parque locado: o número que a gestão usa para
            # decidir renovação, e que não sai de `valor_atual`.
            "custo_12_meses": round(locado["custo_mensal"] * 12, 2),
        },
        # --- Nomes antigos, agora restritos ao COMPRADO -----------------
        # Quem lia `valor_atual` esperando patrimônio continua certo. Antes, um
        # locado somava zero ali e ninguém notava a diferença.
        "valor_aquisicao": round(comprado["valor_aquisicao"], 2),
        "valor_depreciado": round(comprado["valor_depreciado"], 2),
        "valor_atual": round(comprado["valor_atual"], 2),
        "custo_manutencao": round(comprado["custo_manutencao"] + locado["custo_manutencao"], 2),
        "tco_total": round(tco_comprado + tco_locado, 2),
        "percentual_depreciado": (
            round(comprado["valor_depreciado"] / comprado["valor_aquisicao"] * 100, 1)
            if comprado["valor_aquisicao"] else 0.0
        ),
        "garantias": garantias,
        "garantias_vencendo": garantias.get("vencendo", 0) + garantias.get("atencao", 0),
    }


def resumo_de_software(assinaturas: list[dict]) -> dict[str, Any]:
    """Custo das assinaturas de software — a **terceira natureza**.

    ## Por que é um bloco separado, e não mais um número somado

    O parque já tem duas naturezas que não se somam:

        Comprado  → patrimônio que deprecia
        Locado    → mensalidade de equipamento

    A assinatura de software é a terceira: **serviço pago todo mês**, sem
    equipamento nenhum associado. Somar as três daria um "valor do parque"
    sem significado — e foi exatamente o erro que o módulo financeiro já
    corrigiu uma vez, ao separar comprado de locado.

    ## O que entra aqui

    Só **assinatura**. Licença perpétua é compra pontual: já foi paga, não
    tem mensalidade, e misturá-la aqui faria o custo mensal saltar no mês da
    compra e sumir no seguinte.

    Cada item esperado:
        {"nome": str, "valor_mensal": float, "seats": int, "validade": date|None}
    """
    total_mensal = 0.0
    total_seats = 0
    titulos = 0
    vencendo: list[dict] = []

    hoje = date.today()

    for a in assinaturas:
        mensal = float(a.get("valor_mensal") or 0)
        if mensal <= 0:
            continue
        titulos += 1
        total_mensal += mensal
        total_seats += int(a.get("seats") or 0)

        validade = a.get("validade")
        if isinstance(validade, datetime):
            validade = validade.date()
        if not isinstance(validade, date):
            continue

        dias = (validade - hoje).days
        # 60 dias é a janela em que ainda dá tempo de renegociar. Abaixo de
        # 30, a renovação já é urgência — e o tom muda.
        if dias <= 60:
            vencendo.append({
                "nome": a.get("nome") or "—",
                "validade": validade.isoformat(),
                "dias": dias,
                "valor_mensal": round(mensal, 2),
                "urgente": dias <= 30,
            })

    vencendo.sort(key=lambda x: x["dias"])

    return {
        "titulos": titulos,
        "seats": total_seats,
        "custo_mensal": round(total_mensal, 2),
        # O anual é o número que a gestão usa para orçar. Calculado, e não
        # gravado: reajuste de contrato mudaria o valor sem ninguém lembrar
        # de corrigir o campo.
        "custo_anual": round(total_mensal * 12, 2),
        "vencendo": vencendo,
        # A frase que evita a leitura errada — sem ela, alguém soma este
        # valor ao patrimônio.
        "observacao": (
            "Assinatura é serviço, não patrimônio: o custo é a mensalidade e "
            "não há valor residual. Não somar ao valor do parque."
        ),
    }
