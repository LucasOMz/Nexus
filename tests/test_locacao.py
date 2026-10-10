"""Contrato de locação — o que o passo 1 precisa garantir.

O ponto mais delicado é o **rateio**: o custo por equipamento é
`valor_mensal / nº de ativos vivos no contrato`. Ele tem que ser calculado na
hora, porque devolver um equipamento não reduz a mensalidade — o custo dos que
ficaram sobe. Um valor gravado mentiria a partir da primeira devolução.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.contrato import Contrato
from app.models.core import Ativo, Planta
from app.models.enums import FormaAquisicao, TipoContrato


def _db(client):
    from app.database import get_db
    from app.main import app

    return next(app.dependency_overrides[get_db]())


def _planta(db, sigla="TAT"):
    p = Planta(nome=f"Planta {sigla}", sigla=sigla)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


class TestFormaAquisicao:
    def test_o_padrao_e_comprado(self, client):
        """Todo ativo que já existia foi tratado como comprado.

        O campo nascer como `locado` mudaria o significado do parque inteiro
        no dia do deploy.
        """
        db = _db(client)
        a = Ativo(dominio="ti", tipo_item="ativo", patrimonio="PADRAO",
                  planta_id=_planta(db).id, status="estoque")
        db.add(a)
        db.commit()
        db.refresh(a)
        assert a.forma_aquisicao == FormaAquisicao.COMPRADO

    def test_os_valores_do_enum(self):
        assert FormaAquisicao.COMPRADO == "comprado"
        assert FormaAquisicao.LOCADO == "locado"

    def test_tipos_de_contrato(self):
        assert TipoContrato.LOCACAO == "locacao"
        assert TipoContrato.COMODATO == "comodato"
        assert TipoContrato.COMPRA == "compra"


class TestContrato:
    def _contrato(self, db, **campos):
        c = Contrato(
            numero=campos.pop("numero", "2024/117"),
            tipo=campos.pop("tipo", TipoContrato.LOCACAO),
            inicio=campos.pop("inicio", date(2024, 1, 1)),
            valor_mensal=campos.pop("valor_mensal", Decimal("8500.00")),
            **campos,
        )
        db.add(c)
        db.commit()
        db.refresh(c)
        return c

    def test_cria_contrato(self, client):
        db = _db(client)
        c = self._contrato(db)
        assert c.id is not None
        assert c.numero == "2024/117"

    def test_numero_e_unico(self, client):
        db = _db(client)
        self._contrato(db)
        with pytest.raises(Exception):
            self._contrato(db)

    def test_sem_fim_e_indeterminado_e_em_aberto(self, client):
        db = _db(client)
        c = self._contrato(db, fim=None)
        assert c.em_aberto is True
        assert c.dias_para_vencer is None

    def test_contrato_futuro_esta_em_aberto(self, client):
        db = _db(client)
        c = self._contrato(db, fim=date.today() + timedelta(days=45))
        assert c.em_aberto is True
        assert c.dias_para_vencer == 45

    def test_contrato_vencido_nao_esta_em_aberto(self, client):
        db = _db(client)
        c = self._contrato(db, fim=date.today() - timedelta(days=3))
        assert c.em_aberto is False
        assert c.dias_para_vencer == -3

    def test_vencendo_hoje_conta_como_em_aberto(self, client):
        """No último dia ainda vale — só depois de vencer é que não."""
        db = _db(client)
        c = self._contrato(db, fim=date.today())
        assert c.em_aberto is True
        assert c.dias_para_vencer == 0


class TestRateio:
    """O coração do passo 1."""

    def _contrato_com_ativos(self, db, quantos, mensal="8500.00"):
        planta = _planta(db)
        c = Contrato(numero="R-1", tipo=TipoContrato.LOCACAO,
                     inicio=date(2024, 1, 1),
                     # `Decimal(None)` estoura: comodato não tem mensalidade.
                     valor_mensal=Decimal(mensal) if mensal is not None else None)
        db.add(c)
        db.commit()
        db.refresh(c)
        for i in range(quantos):
            db.add(Ativo(dominio="ti", tipo_item="ativo", patrimonio=f"R-{i}",
                         planta_id=planta.id, status="estoque",
                         contrato_id=c.id, forma_aquisicao=FormaAquisicao.LOCADO))
        db.commit()
        db.refresh(c)
        return c

    def test_divide_pelo_numero_de_ativos(self, client):
        db = _db(client)
        c = self._contrato_com_ativos(db, 50)
        # 8500 / 50 = 170
        assert c.valor_mensal_por_ativo == Decimal("170.00")

    def test_sem_ativos_nao_divide_por_zero(self, client):
        db = _db(client)
        c = Contrato(numero="VAZIO", tipo=TipoContrato.LOCACAO,
                     inicio=date(2024, 1, 1), valor_mensal=Decimal("100.00"))
        db.add(c)
        db.commit()
        db.refresh(c)
        assert c.valor_mensal_por_ativo is None

    def test_comodato_sem_mensalidade_nao_rateia(self, client):
        db = _db(client)
        c = self._contrato_com_ativos(db, 10, mensal=None)
        assert c.valor_mensal_por_ativo is None

    def test_o_rateio_SOBE_quando_devolvem_equipamento(self, client):
        """O ponto que engana — e o motivo de não gravar o valor.

        A mensalidade do contrato não cai quando um equipamento é devolvido.
        O custo dos que ficaram sobe. Um valor gravado continuaria mostrando
        R$ 170 para sempre.
        """
        db = _db(client)
        c = self._contrato_com_ativos(db, 50)
        assert c.valor_mensal_por_ativo == Decimal("170.00")

        # Devolve 10: restam 40.
        devolvidos = (
            db.query(Ativo).filter(Ativo.contrato_id == c.id).limit(10).all()
        )
        for a in devolvidos:
            a.deleted_at = date.today()
        db.commit()
        db.refresh(c)

        # 8500 / 40 = 212,50 — não 170.
        assert c.valor_mensal_por_ativo == Decimal("212.50")

    def test_ativo_apagado_sai_da_conta(self, client):
        db = _db(client)
        c = self._contrato_com_ativos(db, 4)
        assert c.valor_mensal_por_ativo == Decimal("2125.00")

        um = db.query(Ativo).filter(Ativo.contrato_id == c.id).first()
        um.deleted_at = date.today()
        db.commit()
        db.refresh(c)
        # 8500 / 3
        assert c.valor_mensal_por_ativo == Decimal("2833.33")


class TestVinculo:
    def test_ativo_aponta_para_o_contrato(self, client):
        db = _db(client)
        planta = _planta(db)
        c = Contrato(numero="V-1", tipo=TipoContrato.LOCACAO,
                     inicio=date(2024, 1, 1), valor_mensal=Decimal("100.00"))
        db.add(c)
        db.commit()
        db.refresh(c)

        a = Ativo(dominio="ti", tipo_item="ativo", patrimonio="V-ATIVO",
                  planta_id=planta.id, status="estoque",
                  contrato_id=c.id, forma_aquisicao=FormaAquisicao.LOCADO)
        db.add(a)
        db.commit()
        # `c.ativos` foi carregado ANTES deste ativo existir (lazy="selectin"
        # guarda a lista no objeto). Sem o refresh, a relação mostraria a
        # lista velha — e o teste falharia por causa do cache, não do código.
        db.refresh(c)

        assert a.contrato_id == c.id
        assert a.contrato.numero == "V-1"
        assert a in c.ativos

    def test_apagar_ativo_nao_apaga_o_contrato(self, client):
        """O contrato cobre outros cinquenta — não pode sumir junto."""
        from app.database import get_db
        from app.main import app
        from tests.conftest import TestingSession

        db = next(app.dependency_overrides[get_db]())
        planta = _planta(db)
        c = Contrato(numero="NAO-SUMIR", tipo=TipoContrato.LOCACAO,
                     inicio=date(2024, 1, 1), valor_mensal=Decimal("100.00"))
        db.add(c)
        db.commit()
        db.refresh(c)
        cid = c.id

        a = Ativo(dominio="ti", tipo_item="ativo", patrimonio="X",
                  planta_id=planta.id, status="estoque", contrato_id=cid)
        db.add(a)
        db.commit()
        db.delete(a)
        db.commit()

        outro = TestingSession()
        assert outro.get(Contrato, cid) is not None
        outro.close()


class TestValorResidual:
    def test_guarda_o_preco_da_compra_futura(self, client):
        """Serve para planejar o buyout antes de ele acontecer."""
        db = _db(client)
        a = Ativo(dominio="ti", tipo_item="ativo", patrimonio="BUYOUT",
                  planta_id=_planta(db).id, status="estoque",
                  forma_aquisicao=FormaAquisicao.LOCADO,
                  valor_residual=Decimal("1200.00"))
        db.add(a)
        db.commit()
        db.refresh(a)
        assert a.valor_residual == Decimal("1200.00")
        # Locado não tem valor de compra — só o residual.
        assert a.valor is None
