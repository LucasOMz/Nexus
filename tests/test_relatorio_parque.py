"""Relatórios: o bloco do parque (comprado x locado).

Depois da locação, "valor do parque" deixou de ser um número só. Somar
patrimônio com mensalidade daria um valor sem significado — por isso o
relatório separa as duas naturezas, como o financeiro já faz.

A parte que mais precisa de atenção é o **rateio por domínio**: um contrato
pode cobrir ativos de TI e de impressora, e cada inventário deve mostrar só a
sua fatia. Contar o contrato inteiro nos dois inflaria a despesa dos dois.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.database import get_db
from app.main import app
from app.models.contrato import Contrato
from app.models.core import Ativo, Planta
from app.models.enums import FormaAquisicao, TipoContrato


def _db(client):
    return next(app.dependency_overrides[get_db]())


def _planta(db):
    p = Planta(nome="Planta R", sigla="R")
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _ativo(db, planta_id, patrimonio, dominio="ti", **campos):
    a = Ativo(
        dominio=dominio, tipo_item="ativo", patrimonio=patrimonio,
        planta_id=planta_id, status="estoque", **campos,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _contrato(db, numero, mensal):
    c = Contrato(numero=numero, tipo=TipoContrato.LOCACAO, inicio=date(2024, 1, 1),
                 valor_mensal=Decimal(mensal))
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _parque(client, headers, dominio="ti"):
    r = client.get(f"/api/v1/relatorios/graficos?dominio={dominio}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["parque"]


class TestComposicao:
    def test_conta_comprado_e_locado(self, client, auth_headers):
        db = _db(client)
        planta = _planta(db)
        _ativo(db, planta.id, "C-1", forma_aquisicao=FormaAquisicao.COMPRADO)
        _ativo(db, planta.id, "L-1", forma_aquisicao=FormaAquisicao.LOCADO)
        _ativo(db, planta.id, "L-2", forma_aquisicao=FormaAquisicao.LOCADO)

        p = _parque(client, auth_headers)
        assert p["comprados"] == 1
        assert p["locados"] == 2

    def test_o_ativo_antigo_conta_como_comprado(self, client, auth_headers):
        """Quem não conhece o campo continua comprado — é o padrão do banco."""
        db = _db(client)
        planta = _planta(db)
        db.add(Ativo(dominio="ti", tipo_item="ativo", patrimonio="ANTIGO",
                     planta_id=planta.id, status="estoque"))
        db.commit()

        p = _parque(client, auth_headers)
        assert p["comprados"] == 1
        assert p["locados"] == 0

    def test_a_composicao_vem_rotulada_para_o_grafico(self, client, auth_headers):
        db = _db(client)
        _ativo(db, _planta(db).id, "X-1", forma_aquisicao=FormaAquisicao.LOCADO)
        p = _parque(client, auth_headers)
        assert p["composicao"], "sem série para desenhar"
        assert p["composicao"][0].get("rotulo")


class TestValores:
    def test_o_patrimonio_conta_so_o_comprado(self, client, auth_headers):
        """Um locado não é bem da empresa — somá-lo inflaria o balanço."""
        db = _db(client)
        planta = _planta(db)
        _ativo(db, planta.id, "C-1", forma_aquisicao=FormaAquisicao.COMPRADO,
               valor=Decimal("5000.00"))
        _ativo(db, planta.id, "L-1", forma_aquisicao=FormaAquisicao.LOCADO)

        assert _parque(client, auth_headers)["valor_patrimonial"] == 5000.0

    def test_o_custo_mensal_vem_do_contrato(self, client, auth_headers):
        db = _db(client)
        planta = _planta(db)
        c = _contrato(db, "CT-1", "8500.00")
        for i in range(3):
            _ativo(db, planta.id, f"L-{i}", forma_aquisicao=FormaAquisicao.LOCADO,
                   contrato_id=c.id)

        p = _parque(client, auth_headers)
        assert p["custo_mensal"] == 8500.0
        assert p["custo_12_meses"] == 102000.0

    def test_contrato_sem_ativos_nao_entra(self, client, auth_headers):
        """Mensalidade sem equipamento não é custo deste inventário."""
        db = _db(client)
        _contrato(db, "VAZIO", "1000.00")
        assert _parque(client, auth_headers)["custo_mensal"] == 0.0

    def test_parque_vazio_nao_estoura(self, client, auth_headers):
        _db(client)
        p = _parque(client, auth_headers)
        assert p["comprados"] == 0
        assert p["custo_mensal"] == 0.0
        assert p["top_contratos"] == []


class TestSeparacaoPorDominio:
    def test_cada_inventario_conta_os_seus_ativos(self, client, auth_headers):
        db = _db(client)
        planta = _planta(db)
        c = _contrato(db, "MISTO", "1000.00")
        _ativo(db, planta.id, "TI-1", dominio="ti",
               forma_aquisicao=FormaAquisicao.LOCADO, contrato_id=c.id)
        _ativo(db, planta.id, "IMP-1", dominio="impressora",
               forma_aquisicao=FormaAquisicao.LOCADO, contrato_id=c.id)

        ti = _parque(client, auth_headers, "ti")
        imp = _parque(client, auth_headers, "impressora")
        assert ti["locados"] == 1
        assert imp["locados"] == 1

    def test_o_custo_por_ativo_usa_so_o_inventario_escolhido(self, client, auth_headers):
        """Um contrato que cobre TI e impressoras não pode aparecer com o
        mesmo custo por equipamento nos dois relatórios."""
        db = _db(client)
        planta = _planta(db)
        c = _contrato(db, "MISTO", "1000.00")
        for i in range(3):
            _ativo(db, planta.id, f"TI-{i}", dominio="ti",
                   forma_aquisicao=FormaAquisicao.LOCADO, contrato_id=c.id)
        _ativo(db, planta.id, "IMP-1", dominio="impressora",
               forma_aquisicao=FormaAquisicao.LOCADO, contrato_id=c.id)

        ti = _parque(client, auth_headers, "ti")
        linha = [x for x in ti["top_contratos"] if x["contrato"] == "MISTO"][0]
        # 1000 / 3 ativos de TI — e não / 4 (o total do contrato).
        assert linha["por_ativo"] == 333.33

    def test_top_contratos_ordena_pelo_maior(self, client, auth_headers):
        db = _db(client)
        planta = _planta(db)
        for numero, mensal in (("PEQUENO", "100.00"), ("GRANDE", "9000.00")):
            c = _contrato(db, numero, mensal)
            _ativo(db, planta.id, f"A-{numero}",
                   forma_aquisicao=FormaAquisicao.LOCADO, contrato_id=c.id)

        top = _parque(client, auth_headers)["top_contratos"]
        assert top[0]["contrato"] == "GRANDE"

    def test_limita_a_oito_contratos(self, client, auth_headers):
        """Ranking é para decidir negociação — uma lista longa não ajuda."""
        db = _db(client)
        planta = _planta(db)
        for i in range(12):
            c = _contrato(db, f"C-{i:02d}", "100.00")
            _ativo(db, planta.id, f"A-{i}", forma_aquisicao=FormaAquisicao.LOCADO,
                   contrato_id=c.id)

        assert len(_parque(client, auth_headers)["top_contratos"]) == 8


class TestFiltroDeDominio:
    def test_so_conta_o_inventario_pedido(self, client, auth_headers):
        db = _db(client)
        planta = _planta(db)
        _ativo(db, planta.id, "TI-1", dominio="ti", valor=Decimal("1000.00"))
        _ativo(db, planta.id, "IMP-1", dominio="impressora", valor=Decimal("9000.00"))

        assert _parque(client, auth_headers, "ti")["valor_patrimonial"] == 1000.0
        assert _parque(client, auth_headers, "impressora")["valor_patrimonial"] == 9000.0

    def test_ativo_apagado_nao_conta(self, client, auth_headers):
        from datetime import datetime, timezone

        db = _db(client)
        planta = _planta(db)
        a = _ativo(db, planta.id, "SUMIDO", forma_aquisicao=FormaAquisicao.LOCADO)
        a.deleted_at = datetime.now(timezone.utc)
        db.commit()

        assert _parque(client, auth_headers)["locados"] == 0
