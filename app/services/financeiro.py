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


def resumo_do_parque(itens: list[dict], agora: datetime | None = None) -> dict[str, Any]:
    """Números do parque inteiro, para o topo da tela financeira."""
    total_aquisicao = 0.0
    total_depreciado = 0.0
    total_atual = 0.0
    total_manutencao = 0.0
    garantias = {"vigente": 0, "atencao": 0, "vencendo": 0, "vencida": 0, "nao_informada": 0}

    for it in itens:
        total_aquisicao += float(it.get("valor") or 0)
        total_manutencao += float(it.get("custo_manutencao") or 0)

        d = depreciacao(it.get("valor"), it.get("data_aquisicao"),
                        dominio=it.get("dominio"), agora=agora)
        if d["aplicavel"]:
            total_atual += d["valor_atual"]
            total_depreciado += d["depreciado"]
        else:
            total_atual += float(it.get("valor") or 0)

        g = garantia(it.get("data_garantia"), agora=agora)
        garantias[g["situacao"]] = garantias.get(g["situacao"], 0) + 1

    return {
        "ativos": len(itens),
        "valor_aquisicao": round(total_aquisicao, 2),
        "valor_depreciado": round(total_depreciado, 2),
        "valor_atual": round(total_atual, 2),
        "custo_manutencao": round(total_manutencao, 2),
        "tco_total": round(total_aquisicao + total_manutencao, 2),
        "percentual_depreciado": (
            round(total_depreciado / total_aquisicao * 100, 1) if total_aquisicao else 0.0
        ),
        "garantias": garantias,
        # O que merece ação agora.
        "garantias_vencendo": garantias.get("vencendo", 0) + garantias.get("atencao", 0),
    }
