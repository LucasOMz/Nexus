"""Camada financeira: depreciação, garantia, TCO, rateio e custo por página.

Funções puras com `agora` por parâmetro — os testes não dependem do relógio.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.financeiro import (
    custo_por_pagina,
    depreciacao,
    garantia,
    rateio_por_departamento,
    resumo_do_parque,
    tco,
)

AGORA = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _ha(dias: int) -> str:
    return (AGORA - timedelta(days=dias)).date().isoformat()


class TestDepreciacao:
    """Valor do parque hoje — o número que ninguém sabe de cabeça."""

    def test_metade_da_vida(self):
        """5 anos de vida útil (20%/ano): com 2,5 anos, metade do valor."""
        d = depreciacao(1000, _ha(int(2.5 * 365.25)), dominio="ti", agora=AGORA)
        assert d["aplicavel"]
        assert abs(d["valor_atual"] - 500) < 5

    def test_valor_novo_permanece(self):
        d = depreciacao(1000, _ha(1), dominio="ti", agora=AGORA)
        assert d["valor_atual"] > 900

    def test_nao_deprecia_abaixo_de_zero(self):
        d = depreciacao(1000, _ha(365 * 30), dominio="ti", agora=AGORA)
        assert d["valor_atual"] >= 0
        assert d["totalmente_depreciado"]

    def test_impressora_deprecia_mais_devagar(self):
        """10 anos de vida útil contra 5: no mesmo tempo, vale mais."""
        imp = depreciacao(1000, _ha(365 * 3), dominio="impressora", agora=AGORA)
        ti = depreciacao(1000, _ha(365 * 3), dominio="ti", agora=AGORA)
        assert imp["valor_atual"] > ti["valor_atual"]

    def test_sem_valor_nao_e_aplicavel(self):
        d = depreciacao(None, _ha(100), agora=AGORA)
        assert not d["aplicavel"]
        assert "valor" in d["motivo"]

    def test_sem_data_nao_e_aplicavel(self):
        d = depreciacao(1000, None, agora=AGORA)
        assert not d["aplicavel"]
        assert "data" in d["motivo"]

    def test_data_no_futuro_nao_e_aplicavel(self):
        futuro = (AGORA + timedelta(days=30)).date().isoformat()
        d = depreciacao(1000, futuro, agora=AGORA)
        assert not d["aplicavel"]

    def test_taxa_customizada(self):
        """A empresa pode ter a taxa dela."""
        d = depreciacao(1000, _ha(365), taxa_anual=50.0, agora=AGORA)
        assert abs(d["valor_atual"] - 500) < 5

    def test_residual_e_respeitado(self):
        d = depreciacao(1000, _ha(365 * 30), residual=100, agora=AGORA)
        assert d["valor_atual"] >= 100

    def test_percentual_depreciado(self):
        d = depreciacao(1000, _ha(int(2.5 * 365.25)), dominio="ti", agora=AGORA)
        assert abs(d["percentual_depreciado"] - 50) < 2


class TestGarantia:
    """Evita pagar reparo que estava coberto."""

    def test_vigente(self):
        g = garantia((AGORA + timedelta(days=200)).date().isoformat(), agora=AGORA)
        assert g["situacao"] == "vigente"
        assert g["sob_garantia"]

    def test_vencendo_em_30_dias(self):
        g = garantia((AGORA + timedelta(days=10)).date().isoformat(), agora=AGORA)
        assert g["situacao"] == "vencendo"

    def test_atencao_em_90_dias(self):
        g = garantia((AGORA + timedelta(days=60)).date().isoformat(), agora=AGORA)
        assert g["situacao"] == "atencao"

    def test_vencida(self):
        g = garantia((AGORA - timedelta(days=1)).date().isoformat(), agora=AGORA)
        assert g["situacao"] == "vencida"
        assert not g["sob_garantia"]

    def test_nao_informada(self):
        g = garantia(None, agora=AGORA)
        assert g["situacao"] == "nao_informada"
        assert g["dias_restantes"] is None

    def test_dias_restantes(self):
        g = garantia((AGORA + timedelta(days=45)).date().isoformat(), agora=AGORA)
        assert g["dias_restantes"] == 45


class TestTCO:
    """Compra + manutenção + consumível."""

    def test_soma_as_tres_parcelas(self):
        t = tco(1000, custo_manutencao=200, custo_consumiveis=50, agora=AGORA)
        assert t["total"] == 1250

    def test_custo_por_mes(self):
        t = tco(1200, data_aquisicao=_ha(int(365.25 * 2)), agora=AGORA)
        assert t["meses_de_uso"] > 20
        assert t["custo_por_mes"] > 0

    def test_mostra_quanto_a_manutencao_pesa(self):
        """Uma impressora que custou 1000 e já gastou 800 em conserto."""
        t = tco(1000, custo_manutencao=800, agora=AGORA)
        assert t["manutencao_sobre_aquisicao"] == 80.0

    def test_sem_valor_nao_divide_por_zero(self):
        t = tco(0, custo_manutencao=100, agora=AGORA)
        assert t["manutencao_sobre_aquisicao"] is None


class TestRateio:
    """Cobrar do departamento certo."""

    def test_agrupa_por_departamento(self):
        itens = [
            {"departamento": "TI", "valor": 1000},
            {"departamento": "TI", "valor": 500},
            {"departamento": "RH", "valor": 300},
        ]
        r = rateio_por_departamento(itens, agora=AGORA)
        assert len(r) == 2
        ti = [x for x in r if x["departamento"] == "TI"][0]
        assert ti["ativos"] == 2
        assert ti["valor_aquisicao"] == 1500

    def test_ordena_do_maior_custo(self):
        itens = [
            {"departamento": "RH", "valor": 100},
            {"departamento": "TI", "valor": 9000},
        ]
        r = rateio_por_departamento(itens, agora=AGORA)
        assert r[0]["departamento"] == "TI"

    def test_sem_departamento_nao_desaparece(self):
        r = rateio_por_departamento([{"valor": 100}], agora=AGORA)
        assert r[0]["departamento"] == "Sem departamento"

    def test_inclui_manutencao(self):
        r = rateio_por_departamento(
            [{"departamento": "TI", "valor": 1000, "custo_manutencao": 400}], agora=AGORA)
        assert r[0]["total"] == 1400
        assert r[0]["custo_manutencao"] == 400


class TestCustoPorPagina:
    """O diferencial: o sistema já tem o contador."""

    def test_tonner_dividido_pelo_rendimento(self):
        c = custo_por_pagina(custo_tonner=400, rendimento_paginas=2000)
        assert c["custo_por_pagina_tonner"] == 0.2
        assert c["completo"]

    def test_inclui_manutencao_por_pagina(self):
        c = custo_por_pagina(custo_tonner=400, rendimento_paginas=2000,
                             custo_manutencao=100, paginas_impressas=1000)
        assert c["custo_por_pagina_manutencao"] == 0.1
        assert abs(c["custo_por_pagina_total"] - 0.3) < 0.001

    def test_inclui_depreciacao_por_pagina(self):
        """O que a maioria dos sistemas esquece.

        Sem a depreciação, o custo por página parece bom e a impressora sai
        caro no fim da vida.
        """
        c = custo_por_pagina(custo_tonner=400, rendimento_paginas=2000,
                             custo_aquisicao=3000, vida_util_paginas=100000)
        assert c["custo_por_pagina_depreciacao"] == 0.03
        assert c["custo_por_pagina_total"] > c["custo_por_pagina_tonner"]

    def test_tonner_mais_caro_custa_mais_por_pagina(self):
        caro = custo_por_pagina(custo_tonner=900, rendimento_paginas=2000)
        barato = custo_por_pagina(custo_tonner=300, rendimento_paginas=2000)
        assert caro["custo_por_pagina_total"] > barato["custo_por_pagina_total"]

    def test_rendimento_maior_barateia(self):
        rende = custo_por_pagina(custo_tonner=600, rendimento_paginas=6000)
        assert rende["custo_por_pagina_tonner"] == 0.1

    def test_sem_tonner_nao_e_completo(self):
        c = custo_por_pagina(custo_tonner=None, rendimento_paginas=None)
        assert not c["completo"]
        assert c["custo_por_pagina_total"] is None

    def test_rendimento_zero_nao_divide(self):
        c = custo_por_pagina(custo_tonner=400, rendimento_paginas=0)
        assert c["custo_por_pagina_tonner"] is None

    def test_custo_total_estimado(self):
        c = custo_por_pagina(custo_tonner=400, rendimento_paginas=2000,
                             paginas_impressas=10000)
        assert c["custo_total_estimado"] == 2000.0


class TestResumoDoParque:
    def test_soma_tudo(self):
        itens = [
            {"valor": 1000, "data_aquisicao": _ha(365 * 5), "dominio": "ti",
             "custo_manutencao": 200, "data_garantia": None},
            {"valor": 500, "data_aquisicao": _ha(10), "dominio": "ti",
             "custo_manutencao": 0, "data_garantia": None},
        ]
        r = resumo_do_parque(itens, agora=AGORA)
        assert r["ativos"] == 2
        assert r["valor_aquisicao"] == 1500
        assert r["tco_total"] == 1700
        assert r["valor_atual"] < 1500

    def test_conta_garantias_por_situacao(self):
        itens = [
            {"valor": 100, "data_garantia": (AGORA + timedelta(days=200)).date().isoformat()},
            {"valor": 100, "data_garantia": (AGORA + timedelta(days=10)).date().isoformat()},
            {"valor": 100, "data_garantia": (AGORA - timedelta(days=10)).date().isoformat()},
        ]
        r = resumo_do_parque(itens, agora=AGORA)
        assert r["garantias"]["vigente"] == 1
        assert r["garantias"]["vencendo"] == 1
        assert r["garantias"]["vencida"] == 1
        assert r["garantias_vencendo"] == 1

    def test_parque_vazio_nao_quebra(self):
        r = resumo_do_parque([], agora=AGORA)
        assert r["ativos"] == 0
        assert r["percentual_depreciado"] == 0.0

    def test_ativo_sem_data_conta_pelo_valor_cheio(self):
        r = resumo_do_parque([{"valor": 800}], agora=AGORA)
        assert r["valor_atual"] == 800
