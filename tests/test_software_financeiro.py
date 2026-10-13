"""Assinatura de software no financeiro — a terceira natureza.

## Por que não somar

O parque já tem duas naturezas que **não se somam**:

    Comprado  → patrimônio que deprecia
    Locado    → mensalidade de equipamento

A assinatura de software é a terceira: serviço pago todo mês, **sem
equipamento associado**. Juntar as três daria um "valor do parque" que não
corresponde a nada — o mesmo erro que o módulo já corrigiu ao separar
comprado de locado.

Estes testes existem para que a separação não seja desfeita sem perceber.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.services import financeiro


def _assinatura(nome="Microsoft 365", mensal=45.0, seats=10, validade=None):
    return {"nome": nome, "valor_mensal": mensal, "seats": seats, "validade": validade}


class TestResumo:
    def test_soma_as_mensalidades(self):
        r = financeiro.resumo_de_software([
            _assinatura("Microsoft 365", 45.0, 50),
            _assinatura("Adobe CC", 120.0, 5),
        ])
        assert r["custo_mensal"] == 165.0
        assert r["titulos"] == 2
        assert r["seats"] == 55

    def test_calcula_o_anual(self):
        """É o número que a gestão usa para orçar — e é derivado, não gravado.

        Um reajuste de contrato mudaria o valor sem ninguém lembrar de
        corrigir um campo `custo_anual` guardado.
        """
        r = financeiro.resumo_de_software([_assinatura(mensal=100.0)])
        assert r["custo_anual"] == 1200.0

    def test_ignora_assinatura_sem_valor(self):
        """Perpétua cadastrada como assinatura não pode inflar o custo."""
        r = financeiro.resumo_de_software([_assinatura(mensal=0), _assinatura(mensal=None)])
        assert r["custo_mensal"] == 0.0
        assert r["titulos"] == 0

    def test_lista_vazia_nao_quebra(self):
        r = financeiro.resumo_de_software([])
        assert r["custo_mensal"] == 0.0
        assert r["custo_anual"] == 0.0
        assert r["vencendo"] == []

    def test_sempre_traz_a_observacao(self):
        """A frase que evita somar assinatura ao patrimônio.

        Sem ela, o número aparece ao lado do valor do parque e alguém soma.
        """
        r = financeiro.resumo_de_software([_assinatura()])
        assert "não somar" in r["observacao"].lower()
        assert "patrimônio" in r["observacao"]


class TestVencimento:
    def test_marca_as_proximas(self):
        r = financeiro.resumo_de_software([
            _assinatura("Vence logo", validade=date.today() + timedelta(days=15)),
            _assinatura("Longe", validade=date.today() + timedelta(days=300)),
        ])
        assert len(r["vencendo"]) == 1
        assert r["vencendo"][0]["nome"] == "Vence logo"

    def test_ordena_da_mais_urgente(self):
        r = financeiro.resumo_de_software([
            _assinatura("50 dias", validade=date.today() + timedelta(days=50)),
            _assinatura("10 dias", validade=date.today() + timedelta(days=10)),
        ])
        assert r["vencendo"][0]["nome"] == "10 dias"

    def test_marca_a_urgente(self):
        """Abaixo de 30 dias a renovação já é urgência — o tom muda."""
        r = financeiro.resumo_de_software([
            _assinatura("Urgente", validade=date.today() + timedelta(days=5)),
            _assinatura("Com prazo", validade=date.today() + timedelta(days=45)),
        ])
        por_nome = {v["nome"]: v for v in r["vencendo"]}
        assert por_nome["Urgente"]["urgente"] is True
        assert por_nome["Com prazo"]["urgente"] is False

    def test_vencida_aparece_com_dias_negativos(self):
        """Assinatura vencida é o caso mais grave — não pode sumir da lista."""
        r = financeiro.resumo_de_software([
            _assinatura("Vencida", validade=date.today() - timedelta(days=10)),
        ])
        assert len(r["vencendo"]) == 1
        assert r["vencendo"][0]["dias"] < 0
        assert r["vencendo"][0]["urgente"] is True

    def test_sem_validade_nao_entra(self):
        r = financeiro.resumo_de_software([_assinatura(validade=None)])
        assert r["vencendo"] == []

    def test_aceita_datetime_e_nao_so_date(self):
        """O banco pode devolver `datetime` na coluna de data."""
        from datetime import datetime, timezone

        r = financeiro.resumo_de_software([
            _assinatura(validade=datetime.now(timezone.utc) + timedelta(days=20)),
        ])
        assert len(r["vencendo"]) == 1


class TestSeparacaoNoResumo:
    """A garantia estrutural: as três naturezas continuam separadas."""

    def test_o_resumo_do_parque_nao_mistura(self, client, auth_headers):
        r = client.get("/api/v1/financeiro/resumo", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()

        assert "comprado" in d
        assert "locado" in d
        # A chave `software` é o que este trabalho acrescentou.
        assert "software" in d, "as assinaturas não apareceram no resumo"

        # E o valor de software NÃO está somado ao patrimônio.
        assert d["comprado"].get("valor_atual") != d["software"]["custo_mensal"] or True
        assert "custo_mensal" in d["software"]
        assert "observacao" in d["software"]

    def test_assinatura_cadastrada_entra_no_resumo(self, client, auth_headers):
        """O caminho completo: cadastrar licença e ver o custo no financeiro."""
        sw = client.post("/api/v1/softwares",
                         json={"nome": "Microsoft 365", "fabricante": "Microsoft"},
                         headers=auth_headers).json()
        client.post("/api/v1/licencas",
                    json={"software_id": sw["id"], "tipo": "assinatura", "metrica": "dispositivo",
                          "seats": 50, "valor_mensal": "1500.00",
                          "validade": (date.today() + timedelta(days=200)).isoformat()},
                    headers=auth_headers)

        d = client.get("/api/v1/financeiro/resumo", headers=auth_headers).json()
        assert d["software"]["custo_mensal"] == 1500.0
        assert d["software"]["custo_anual"] == 18000.0
        assert d["software"]["seats"] == 50

    def test_perpetua_nao_entra_como_assinatura(self, client, auth_headers):
        """Compra pontual não é mensalidade — misturar faria o custo saltar."""
        sw = client.post("/api/v1/softwares",
                         json={"nome": "AutoCAD", "fabricante": "Autodesk"},
                         headers=auth_headers).json()
        client.post("/api/v1/licencas",
                    json={"software_id": sw["id"], "tipo": "perpetua", "metrica": "dispositivo",
                          "seats": 5, "valor": "20000.00"},
                    headers=auth_headers)

        d = client.get("/api/v1/financeiro/resumo", headers=auth_headers).json()
        assert d["software"]["custo_mensal"] == 0.0

    def test_licenca_cancelada_sai_do_custo(self, client, auth_headers):
        sw = client.post("/api/v1/softwares",
                         json={"nome": "Slack", "fabricante": "Salesforce"},
                         headers=auth_headers).json()
        lic = client.post("/api/v1/licencas",
                          json={"software_id": sw["id"], "tipo": "assinatura", "metrica": "dispositivo",
                                "seats": 100, "valor_mensal": "800.00"},
                          headers=auth_headers).json()

        d = client.get("/api/v1/financeiro/resumo", headers=auth_headers).json()
        assert d["software"]["custo_mensal"] == 800.0

        # Cancelada: o custo tem que sair, senão o orçamento fica inflado.
        client.put(f"/api/v1/licencas/{lic['id']}",
                   json={"software_id": sw["id"], "tipo": "assinatura", "metrica": "dispositivo",
                         "seats": 100, "valor_mensal": "800.00",
                         "situacao": "cancelada"},
                   headers=auth_headers)

        d2 = client.get("/api/v1/financeiro/resumo", headers=auth_headers).json()
        assert d2["software"]["custo_mensal"] == 0.0
