"""Alerta de vencimento de contrato (passo 4).

Duas coisas precisam estar certas:

1. **Um aviso por contrato, não por ativo.** Um contrato com 50 notebooks
   geraria 50 itens idênticos — e o sino vira ruído que ninguém olha.
2. **O nível acompanha a urgência.** Contrato vencido não pode aparecer igual
   a um que vence em 85 dias.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.database import get_db
from app.main import app
from app.models.contrato import Contrato
from app.models.core import Ativo, Planta
from app.models.enums import FormaAquisicao, TipoContrato


def _db(client):
    return next(app.dependency_overrides[get_db]())


def _planta(db, sigla="TAT"):
    p = Planta(nome=f"Planta {sigla}", sigla=sigla)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _contrato(db, dias, numero="CT-1", tipo=TipoContrato.LOCACAO, planta_id=None):
    """Contrato que vence em `dias` (negativo = já venceu)."""
    c = Contrato(
        numero=numero, tipo=tipo, inicio=date(2024, 1, 1),
        fim=date.today() + timedelta(days=dias),
        valor_mensal=8500 if tipo == TipoContrato.LOCACAO else None,
        planta_id=planta_id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _avisos(client, headers):
    r = client.get("/api/v1/notificacoes", headers=headers)
    assert r.status_code == 200, r.text
    return [i for i in r.json()["itens"] if i["tipo"] == "contrato_vencendo"]


class TestNiveisDoSinal:
    def test_vencido_e_erro(self, client, auth_headers):
        _contrato(_db(client), -5)
        avisos = _avisos(client, auth_headers)
        assert len(avisos) == 1
        assert avisos[0]["nivel"] == "erro"
        assert "venceu" in avisos[0]["titulo"]

    def test_vence_hoje_e_erro(self, client, auth_headers):
        _contrato(_db(client), 0)
        avisos = _avisos(client, auth_headers)
        assert avisos[0]["nivel"] == "erro"
        assert "HOJE" in avisos[0]["titulo"]

    def test_trinta_dias_e_urgente(self, client, auth_headers):
        _contrato(_db(client), 20)
        assert _avisos(client, auth_headers)[0]["nivel"] == "urgente"

    def test_setenta_dias_e_informativo(self, client, auth_headers):
        _contrato(_db(client), 70)
        assert _avisos(client, auth_headers)[0]["nivel"] == "info"

    def test_a_mensagem_muda_com_a_urgencia(self, client, auth_headers):
        """O texto diz o que fazer — 'renove' só faz sentido perto do fim."""
        db = _db(client)
        _contrato(db, -3, numero="VENCIDO")
        avisos = _avisos(client, auth_headers)
        assert "multa" in avisos[0]["detalhe"]

    def test_aviso_de_vencendo_fala_de_renovacao(self, client, auth_headers):
        _contrato(_db(client), 15)
        assert "renov" in _avisos(client, auth_headers)[0]["detalhe"].lower()


class TestJanela:
    def test_alem_de_90_dias_nao_avisa(self, client, auth_headers):
        """Encheria a lista de coisas para depois."""
        _contrato(_db(client), 120)
        assert _avisos(client, auth_headers) == []

    def test_exatamente_90_dias_avisa(self, client, auth_headers):
        _contrato(_db(client), 90)
        assert len(_avisos(client, auth_headers)) == 1

    def test_prazo_indeterminado_nunca_vence(self, client, auth_headers):
        db = _db(client)
        c = Contrato(numero="SEM-FIM", tipo=TipoContrato.LOCACAO,
                     inicio=date(2024, 1, 1), fim=None, valor_mensal=1000)
        db.add(c)
        db.commit()
        assert _avisos(client, auth_headers) == []


class TestUmAvisoPorContrato:
    def test_contrato_com_50_ativos_gera_UM_aviso(self, client, auth_headers):
        """O ponto do passo 4.

        Avisar por equipamento encheria o sino de 50 itens idênticos, e
        ninguém olharia nenhum.
        """
        db = _db(client)
        planta = _planta(db)
        c = _contrato(db, 10)
        for i in range(50):
            db.add(Ativo(dominio="ti", tipo_item="ativo", patrimonio=f"T-{i}",
                         planta_id=planta.id, status="estoque",
                         contrato_id=c.id, forma_aquisicao=FormaAquisicao.LOCADO))
        db.commit()

        avisos = _avisos(client, auth_headers)
        assert len(avisos) == 1, f"gerou {len(avisos)} avisos"

    def test_o_aviso_diz_quantos_equipamentos(self, client, auth_headers):
        db = _db(client)
        planta = _planta(db)
        c = _contrato(db, 10)
        for i in range(3):
            db.add(Ativo(dominio="ti", tipo_item="ativo", patrimonio=f"Q-{i}",
                         planta_id=planta.id, status="estoque",
                         contrato_id=c.id, forma_aquisicao=FormaAquisicao.LOCADO))
        db.commit()

        assert "3 equipamento" in _avisos(client, auth_headers)[0]["detalhe"]

    def test_dois_contratos_geram_dois_avisos(self, client, auth_headers):
        db = _db(client)
        _contrato(db, 10, numero="CT-A")
        _contrato(db, 40, numero="CT-B")
        assert len(_avisos(client, auth_headers)) == 2

    def test_ordena_pelo_mais_urgente(self, client, auth_headers):
        db = _db(client)
        _contrato(db, 80, numero="LONGE")
        _contrato(db, -2, numero="VENCIDO")
        avisos = _avisos(client, auth_headers)
        assert avisos[0]["contrato_numero"] == "VENCIDO"


class TestTiposEIsolamento:
    def test_contrato_de_compra_nao_avisa_vencimento(self, client, auth_headers):
        """Compra não se devolve — não há prazo a perder."""
        _contrato(_db(client), 10, numero="COMPRA", tipo=TipoContrato.COMPRA)
        assert _avisos(client, auth_headers) == []

    def test_comodato_avisa(self, client, auth_headers):
        """Comodato também tem devolução — e multa por atraso."""
        _contrato(_db(client), 10, numero="COMOD", tipo=TipoContrato.COMODATO)
        assert len(_avisos(client, auth_headers)) == 1

    def test_contrato_encerrado_nao_avisa(self, client, auth_headers):
        from datetime import datetime, timezone

        db = _db(client)
        c = _contrato(db, 10)
        c.deleted_at = datetime.now(timezone.utc)
        db.commit()
        assert _avisos(client, auth_headers) == []


class TestIntegracaoComOSino:
    def test_nao_estoura_a_contagem_de_urgentes(self, client, auth_headers):
        """O alerta entra na contagem do sino, e não a quebra."""
        _contrato(_db(client), -1)
        r = client.get("/api/v1/notificacoes", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert d["total"] >= 1
        assert d["urgentes"] >= 1

    def test_o_aviso_traz_a_rota_para_clicar(self, client, auth_headers):
        c = _contrato(_db(client), 10)
        aviso = _avisos(client, auth_headers)[0]
        assert aviso["rota"] == f"#/contratos/{c.id}"
        assert aviso["contrato_id"] == c.id
