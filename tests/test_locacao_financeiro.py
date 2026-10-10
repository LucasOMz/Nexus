"""Financeiro da locação — passo 2.

A regra que mais importa: **locado não entra no valor patrimonial.** Um
equipamento alugado não é bem da empresa, e somá-lo ao patrimônio infla o
balanço com algo que não é dela.

A segunda: **locado não deprecia.** Depreciar mediria a perda de valor de um
bem que não é nosso.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.services import financeiro as f

# Data fixa para os testes não dependerem do dia em que rodam.
AGORA = f.datetime(2025, 1, 1, 12, 0, tzinfo=f.timezone.utc)


class TestMesesDecorridos:
    def test_conta_meses_cheios(self):
        # 2024-01-01 até 2025-01-01 = 366 dias (2024 é bissexto)
        assert f.meses_decorridos(date(2024, 1, 1), agora=AGORA) == 12.02

    def test_inicio_no_futuro_e_zero(self):
        """Cobrar mensalidade de período que não passou infla o custo."""
        assert f.meses_decorridos(date(2025, 6, 1), agora=AGORA) == 0.0

    def test_inicio_hoje_e_zero(self):
        assert f.meses_decorridos(date(2025, 1, 1), agora=AGORA) == 0.0

    def test_sem_data_e_zero(self):
        assert f.meses_decorridos(None, agora=AGORA) == 0.0

    def test_um_mes(self):
        assert f.meses_decorridos(date(2024, 12, 1), agora=AGORA) == 1.02


class TestCustoLocacao:
    def test_multiplica_meses_por_mensalidade(self):
        c = f.custo_locacao(170.0, date(2024, 1, 1), agora=AGORA)
        assert c["aplicavel"] is True
        assert c["meses"] == 12.02
        assert c["custo_acumulado"] == 2043.4

    def test_a_depreciacao_de_locado_e_ZERO_nao_None(self):
        """Zero, e não "não calculada".

        Devolver None obrigaria todo relatório que soma a tratar o caso — e um
        deles esqueceria, virando número errado sem ninguém notar.
        """
        c = f.custo_locacao(170.0, date(2024, 1, 1), agora=AGORA)
        assert c["depreciacao"] == 0.0
        assert c["depreciacao"] is not None

    def test_projeta_doze_meses(self):
        c = f.custo_locacao(170.0, date(2024, 1, 1), agora=AGORA)
        assert c["custo_12_meses"] == 2040.0

    def test_comodato_nao_tem_custo(self):
        c = f.custo_locacao(0, date(2024, 1, 1), agora=AGORA)
        assert c["aplicavel"] is False
        assert "comodato" in c["motivo"]

    def test_sem_inicio_nao_calcula(self):
        c = f.custo_locacao(170.0, None, agora=AGORA)
        assert c["aplicavel"] is False

    def test_residual_nao_entra_no_custo(self):
        """Buyout é preço de compra futura, não custo de quem só aluga."""
        c = f.custo_locacao(170.0, date(2024, 1, 1), agora=AGORA, valor_residual=1200.0)
        assert c["valor_residual"] == 1200.0
        assert c["custo_acumulado"] == 2043.4   # sem os 1200


class TestResumoDoParque:
    def _comprado(self, valor=5000.0, anos=1):
        return {
            "valor": valor,
            "data_aquisicao": date(2025 - anos, 1, 1),
            "dominio": "ti",
            "forma_aquisicao": "comprado",
        }

    def _locado(self, mensal=170.0):
        return {
            "forma_aquisicao": "locado",
            "valor_mensal": mensal,
            "contrato_inicio": date(2024, 1, 1),
        }

    def test_separa_comprado_de_locado(self):
        r = f.resumo_do_parque([self._comprado(), self._locado()], agora=AGORA)
        assert r["comprado"]["ativos"] == 1
        assert r["locado"]["ativos"] == 1
        assert r["ativos"] == 2

    def test_locado_NAO_entra_no_valor_patrimonial(self):
        """O erro que infla o balanço.

        Um locado não é bem da empresa. Se ele entrasse em `valor_aquisicao`,
        o patrimônio mostraria equipamento que não é nosso.
        """
        so_locado = f.resumo_do_parque([self._locado(170.0)], agora=AGORA)
        assert so_locado["valor_aquisicao"] == 0.0
        assert so_locado["valor_atual"] == 0.0
        assert so_locado["comprado"]["ativos"] == 0
        # Mas o custo dele existe, e está no lugar certo.
        assert so_locado["locado"]["custo_acumulado"] > 0

    def test_locado_nao_deprecia(self):
        r = f.resumo_do_parque([self._locado()], agora=AGORA)
        assert r["valor_depreciado"] == 0.0
        assert r["percentual_depreciado"] == 0.0

    def test_custo_mensal_do_parque_locado(self):
        """O número que a gestão usa para decidir renovação."""
        itens = [self._locado(170.0) for _ in range(50)]
        r = f.resumo_do_parque(itens, agora=AGORA)
        assert r["locado"]["custo_mensal"] == 8500.0
        assert r["locado"]["custo_12_meses"] == 102000.0

    def test_soma_manutencao_dos_dois(self):
        comp = self._comprado()
        comp["custo_manutencao"] = 100.0
        loc = self._locado()
        loc["custo_manutencao"] = 50.0
        r = f.resumo_do_parque([comp, loc], agora=AGORA)
        assert r["custo_manutencao"] == 150.0

    def test_tco_do_locado_nao_inclui_o_valor_do_equipamento(self):
        r = f.resumo_do_parque([self._locado(170.0)], agora=AGORA)
        # TCO = mensalidades pagas + manutenção. Sem "valor do equipamento".
        assert r["locado"]["tco"] == r["locado"]["custo_acumulado"]

    def test_os_nomes_antigos_so_olham_o_comprado(self):
        """Quem lia `valor_atual` esperando patrimônio continua certo."""
        r = f.resumo_do_parque([self._comprado(valor=5000.0), self._locado()], agora=AGORA)
        assert r["valor_aquisicao"] == r["comprado"]["valor_aquisicao"]
        assert r["valor_atual"] == r["comprado"]["valor_atual"]

    def test_tco_total_soma_os_dois(self):
        r = f.resumo_do_parque([self._comprado(), self._locado()], agora=AGORA)
        assert round(r["tco_total"], 2) == round(r["comprado"]["tco"] + r["locado"]["tco"], 2)

    def test_locado_nao_conta_garantia(self):
        """Quem cobre o locado é o fornecedor, pelo contrato — não há garantia
        própria para rastrear."""
        loc = self._locado()
        loc["data_garantia"] = None
        r = f.resumo_do_parque([loc], agora=AGORA)
        assert r["garantias"]["nao_informada"] == 0

    def test_sem_forma_aquisicao_conta_como_comprado(self):
        """Todo ativo que já existia é comprado — e a função não pode
        depender de o chamador informar o campo."""
        antigo = {"valor": 5000.0, "data_aquisicao": date(2024, 1, 1), "dominio": "ti"}
        r = f.resumo_do_parque([antigo], agora=AGORA)
        assert r["comprado"]["ativos"] == 1
        assert r["locado"]["ativos"] == 0

    def test_parque_vazio_nao_divide_por_zero(self):
        r = f.resumo_do_parque([], agora=AGORA)
        assert r["ativos"] == 0
        assert r["percentual_depreciado"] == 0.0
        assert r["comprado"]["tco"] == 0.0
        assert r["locado"]["custo_mensal"] == 0.0

    def test_retrocompativel_com_a_assinatura_antiga(self):
        """Sem `agora`, usa a data real — e não estoura."""
        r = f.resumo_do_parque([self._comprado(anos=1)])
        assert "comprado" in r and "locado" in r
        assert r["comprado"]["ativos"] == 1


class TestGarantiaDoComprado:
    def test_garantia_vencida_continua_contando(self):
        """O comportamento antigo do comprado não pode ter mudado."""
        it = {
            "valor": 1000.0,
            "data_aquisicao": date(2020, 1, 1),
            "data_garantia": date(2021, 1, 1),
            "dominio": "ti",
        }
        r = f.resumo_do_parque([it], agora=AGORA)
        assert r["garantias"]["vencida"] == 1

    def test_garantia_vigente(self):
        it = {
            "valor": 1000.0,
            "data_aquisicao": date(2024, 1, 1),
            "data_garantia": date.today() + timedelta(days=300),
            "dominio": "ti",
        }
        r = f.resumo_do_parque([it], agora=AGORA)
        assert r["garantias"]["vigente"] == 1
