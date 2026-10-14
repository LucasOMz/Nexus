"""Contratos — CRUD e a transição locado → comprado (passo 3).

O `exercer_compra` é o único ponto do sistema em que um ativo muda de
natureza patrimonial. Cada teste aqui corresponde a uma das cinco regras, e
inverter qualquer uma produz número errado que ninguém percebe.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.database import get_db
from app.main import app
from app.models.core import Ativo, Planta
from app.models.enums import FormaAquisicao


def _db(client):
    return next(app.dependency_overrides[get_db]())


def _planta(db, sigla="TAT"):
    p = Planta(nome=f"Planta {sigla}", sigla=sigla)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _corpo(numero="2024/117", **campos):
    base = {
        "numero": numero,
        "tipo": "locacao",
        "inicio": "2024-01-01",
        "valor_mensal": "8500.00",
    }
    base.update(campos)
    return base


def _locado(db, planta_id, contrato_id, patrimonio):
    a = Ativo(
        dominio="ti", tipo_item="ativo", patrimonio=patrimonio, numero_serie=f"NS-{patrimonio}",
        planta_id=planta_id, status="estoque",
        contrato_id=contrato_id, forma_aquisicao=FormaAquisicao.LOCADO,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


class TestCriarContrato:
    def test_cria_locacao(self, client, auth_headers):
        r = client.post("/api/v1/contratos", json=_corpo(), headers=auth_headers)
        assert r.status_code == 201, r.text
        d = r.json()
        assert d["numero"] == "2024/117"
        assert d["em_aberto"] is True
        assert d["dias_para_vencer"] is None      # prazo indeterminado

    def test_numero_repetido_e_recusado(self, client, auth_headers):
        client.post("/api/v1/contratos", json=_corpo(), headers=auth_headers)
        r = client.post("/api/v1/contratos", json=_corpo(), headers=auth_headers)
        assert r.status_code == 409

    def test_locacao_sem_mensalidade_e_recusada(self, client, auth_headers):
        """Sem valor mensal não é locação — é comodato."""
        r = client.post("/api/v1/contratos",
                        json=_corpo(valor_mensal=None), headers=auth_headers)
        assert r.status_code == 422
        assert "mensal" in r.text.lower()

    def test_comodato_com_mensalidade_e_recusado(self, client, auth_headers):
        r = client.post("/api/v1/contratos",
                        json=_corpo(tipo="comodato", valor_mensal="100.00"),
                        headers=auth_headers)
        assert r.status_code == 422

    def test_comodato_sem_mensalidade_e_aceito(self, client, auth_headers):
        r = client.post("/api/v1/contratos",
                        json=_corpo(numero="COM-1", tipo="comodato", valor_mensal=None),
                        headers=auth_headers)
        assert r.status_code == 201, r.text

    def test_fim_antes_do_inicio_e_recusado(self, client, auth_headers):
        """Erro de digitação que faria o alerta disparar desde o dia 1."""
        r = client.post("/api/v1/contratos",
                        json=_corpo(inicio="2024-06-01", fim="2024-01-01"),
                        headers=auth_headers)
        assert r.status_code == 422


class TestListarEConsultar:
    def test_lista(self, client, auth_headers):
        client.post("/api/v1/contratos", json=_corpo("A-1"), headers=auth_headers)
        client.post("/api/v1/contratos", json=_corpo("A-2"), headers=auth_headers)
        r = client.get("/api/v1/contratos", headers=auth_headers)
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_busca_por_numero(self, client, auth_headers):
        client.post("/api/v1/contratos", json=_corpo("BUSCA-1"), headers=auth_headers)
        client.post("/api/v1/contratos", json=_corpo("OUTRO"), headers=auth_headers)
        r = client.get("/api/v1/contratos?busca=BUSCA", headers=auth_headers)
        assert [c["numero"] for c in r.json()] == ["BUSCA-1"]

    def test_apenas_abertos_filtra_vencidos(self, client, auth_headers):
        client.post("/api/v1/contratos",
                    json=_corpo("VENCIDO", inicio="2020-01-01", fim="2021-01-01"),
                    headers=auth_headers)
        client.post("/api/v1/contratos", json=_corpo("VIVO"), headers=auth_headers)

        r = client.get("/api/v1/contratos?apenas_abertos=true", headers=auth_headers)
        assert [c["numero"] for c in r.json()] == ["VIVO"]

    def test_contrato_inexistente_da_404(self, client, auth_headers):
        assert client.get("/api/v1/contratos/9999", headers=auth_headers).status_code == 404


class TestVinculoDeAtivos:
    def _contrato_e_ativos(self, client, auth_headers, quantos=3):
        db = _db(client)
        planta = _planta(db)
        cid = client.post("/api/v1/contratos", json=_corpo(), headers=auth_headers).json()["id"]

        ids = []
        for i in range(quantos):
            a = Ativo(dominio="ti", tipo_item="ativo", patrimonio=f"V-{i}", numero_serie=f"NS-V-{i}",
                      planta_id=planta.id, status="estoque")
            db.add(a)
            db.commit()
            db.refresh(a)
            ids.append(a.id)
        return cid, ids

    def test_vincular_marca_como_locado(self, client, auth_headers):
        cid, ids = self._contrato_e_ativos(client, auth_headers, 3)

        r = client.post(f"/api/v1/contratos/{cid}/ativos",
                        json={"ativo_ids": ids}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["total_ativos"] == 3
        # 8500 / 3
        assert Decimal(r.json()["valor_mensal_por_ativo"]) == Decimal("2833.33")

        db = _db(client)
        a = db.get(Ativo, ids[0])
        assert a.forma_aquisicao == FormaAquisicao.LOCADO

    def test_vincular_limpa_o_valor_de_compra(self, client, auth_headers):
        """Locado não tem valor de compra.

        Se o ativo tinha um valor (de quando era comprado), ele sai — senão o
        patrimônio continuaria contando um bem que passou a ser alugado.
        """
        db = _db(client)
        planta = _planta(db)
        cid = client.post("/api/v1/contratos", json=_corpo(), headers=auth_headers).json()["id"]

        a = Ativo(dominio="ti", tipo_item="ativo", patrimonio="ERA-COMPRADO", numero_serie="NS-ERA-COMPRADO",
                  planta_id=planta.id, status="estoque",
                  valor=Decimal("5000.00"), data_aquisicao=date(2023, 1, 1))
        db.add(a)
        db.commit()
        db.refresh(a)

        client.post(f"/api/v1/contratos/{cid}/ativos",
                    json={"ativo_ids": [a.id]}, headers=auth_headers)

        db.refresh(a)
        assert a.forma_aquisicao == FormaAquisicao.LOCADO
        assert a.valor is None
        assert a.data_aquisicao is None

    def test_ativo_inexistente_da_404(self, client, auth_headers):
        cid, _ = self._contrato_e_ativos(client, auth_headers, 1)
        r = client.post(f"/api/v1/contratos/{cid}/ativos",
                        json={"ativo_ids": [99999]}, headers=auth_headers)
        assert r.status_code == 404

    def test_desvincular_sobe_o_rateio(self, client, auth_headers):
        """A mensalidade não cai quando um equipamento sai."""
        cid, ids = self._contrato_e_ativos(client, auth_headers, 4)

        client.post(f"/api/v1/contratos/{cid}/ativos",
                    json={"ativo_ids": ids}, headers=auth_headers)

        r = client.delete(f"/api/v1/contratos/{cid}/ativos?ativo_ids={ids[0]}",
                          headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["total_ativos"] == 3
        # 8500 / 3 = 2833,33 — antes era 2125,00
        assert Decimal(r.json()["valor_mensal_por_ativo"]) == Decimal("2833.33")


class TestExercerCompra:
    """As cinco regras da transição."""

    def _locado_no_contrato(self, client, auth_headers, mensal="170.00"):
        db = _db(client)
        planta = _planta(db)
        cid = client.post(
            "/api/v1/contratos",
            json=_corpo("COMPRA-1", valor_mensal=mensal), headers=auth_headers,
        ).json()["id"]
        a = _locado(db, planta.id, cid, "TP98000011212")
        return cid, a.id

    def test_regra1_muda_a_natureza(self, client, auth_headers):
        cid, aid = self._locado_no_contrato(client, auth_headers)
        r = client.post(f"/api/v1/contratos/{cid}/ativos/{aid}/exercer-compra",
                        json={"valor": "1200.00"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["forma_aquisicao"] == "comprado"

    def test_regra2_o_valor_e_o_preco_pago(self, client, auth_headers):
        cid, aid = self._locado_no_contrato(client, auth_headers)
        client.post(f"/api/v1/contratos/{cid}/ativos/{aid}/exercer-compra",
                    json={"valor": "1200.00"}, headers=auth_headers)
        db = _db(client)
        assert db.get(Ativo, aid).valor == Decimal("1200.00")

    def test_regra3_a_data_e_a_da_compra_nao_o_inicio_da_locacao(self, client, auth_headers):
        """**A regra que mais importa.**

        A locação começou em 2024-01-01. Se a depreciação partisse dali,
        estaria depreciando um bem que não era da empresa até hoje.
        """
        cid, aid = self._locado_no_contrato(client, auth_headers)
        client.post(f"/api/v1/contratos/{cid}/ativos/{aid}/exercer-compra",
                    json={"valor": "1200.00", "data": "2025-06-15"}, headers=auth_headers)

        db = _db(client)
        a = db.get(Ativo, aid)
        assert a.data_aquisicao == date(2025, 6, 15), "não pode retroagir à locação"

    def test_regra4_sai_do_contrato(self, client, auth_headers):
        """Continua vinculado faria o rateio dividir por quem não é mais alugado."""
        cid, aid = self._locado_no_contrato(client, auth_headers)
        r = client.post(f"/api/v1/contratos/{cid}/ativos/{aid}/exercer-compra",
                        json={"valor": "1200.00"}, headers=auth_headers)

        db = _db(client)
        assert db.get(Ativo, aid).contrato_id is None
        assert r.json()["ativos_restantes"] == 0

    def test_regra5_o_residual_e_zerado(self, client, auth_headers):
        """O buyout foi pago e virou `valor`. Mantê-lo faria parecer que ainda
        há uma compra futura."""
        cid, aid = self._locado_no_contrato(client, auth_headers)
        db = _db(client)
        db.get(Ativo, aid).valor_residual = Decimal("1200.00")
        db.commit()

        client.post(f"/api/v1/contratos/{cid}/ativos/{aid}/exercer-compra",
                    json={"valor": "1200.00"}, headers=auth_headers)
        db.refresh(db.get(Ativo, aid))
        assert db.get(Ativo, aid).valor_residual is None

    def test_valor_zero_e_recusado(self, client, auth_headers):
        """Sem preço, o ativo entraria no patrimônio valendo zero."""
        cid, aid = self._locado_no_contrato(client, auth_headers)
        r = client.post(f"/api/v1/contratos/{cid}/ativos/{aid}/exercer-compra",
                        json={"valor": "0"}, headers=auth_headers)
        assert r.status_code == 422

    def test_ja_comprado_e_recusado(self, client, auth_headers):
        cid, aid = self._locado_no_contrato(client, auth_headers)
        client.post(f"/api/v1/contratos/{cid}/ativos/{aid}/exercer-compra",
                    json={"valor": "1200.00"}, headers=auth_headers)
        r = client.post(f"/api/v1/contratos/{cid}/ativos/{aid}/exercer-compra",
                        json={"valor": "500.00"}, headers=auth_headers)
        assert r.status_code in (400, 404)

    def test_ativo_de_outro_contrato_da_404(self, client, auth_headers):
        cid, aid = self._locado_no_contrato(client, auth_headers)
        outro = client.post("/api/v1/contratos",
                            json=_corpo("OUTRO-C"), headers=auth_headers).json()["id"]
        r = client.post(f"/api/v1/contratos/{outro}/ativos/{aid}/exercer-compra",
                        json={"valor": "1200.00"}, headers=auth_headers)
        assert r.status_code == 404

    def test_a_resposta_avisa_o_novo_rateio(self, client, auth_headers):
        """O gestor precisa entender por que o custo por equipamento mudou."""
        cid, aid = self._locado_no_contrato(client, auth_headers)
        r = client.post(f"/api/v1/contratos/{cid}/ativos/{aid}/exercer-compra",
                        json={"valor": "1200.00"}, headers=auth_headers)
        assert "rateio_apos_compra" in r.json()
        assert "mensagem" in r.json()


class TestEncerrarContrato:
    def test_encerrar_nao_apaga_os_vinculos(self, client, auth_headers):
        """O histórico de onde cada equipamento veio não se apaga."""
        db = _db(client)
        planta = _planta(db)
        cid = client.post("/api/v1/contratos", json=_corpo(), headers=auth_headers).json()["id"]
        a = _locado(db, planta.id, cid, "FICA")

        client.delete(f"/api/v1/contratos/{cid}", headers=auth_headers)

        db.refresh(a)
        assert a.contrato_id == cid
        # Mas o contrato sai da lista.
        r = client.get("/api/v1/contratos", headers=auth_headers)
        assert all(c["id"] != cid for c in r.json())
