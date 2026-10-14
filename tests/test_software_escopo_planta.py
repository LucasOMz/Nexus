"""Fase 1 — conformidade: escopo de planta e situação da licença.

## Os dois fazem o NÚMERO mentir

Um erro de tela a pessoa percebe. Um número errado num relatório de
conformidade ela **usa para decidir** — e é a pior classe de falha deste
módulo, porque o resultado continua parecendo plausível.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core import segredos
from app.services import conformidade as c


@pytest.fixture(autouse=True)
def _com_chave_mestra(monkeypatch):
    monkeypatch.setenv(segredos.VARIAVEL, "chave-mestra-de-teste")
    yield


@pytest.fixture
def db_session(client):
    from app.database import get_db
    from app.main import app

    return next(app.dependency_overrides[get_db]())


def _planta(db, sigla):
    from app.models.core import Planta

    p = Planta(nome=f"Unidade {sigla}", sigla=sigla)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _instalado_em(db, planta, nome, quantas):
    from app.models.core import Ativo
    from app.models.software import SoftwareInstalado

    for i in range(quantas):
        a = Ativo(dominio="ti", tipo_item="ativo",
                  patrimonio=f"{planta.sigla}-{nome[:4]}-{i}", numero_serie=f"NS-{planta.sigla}-{nome[:4]}-{i}",
                  planta_id=planta.id, status="estoque")
        db.add(a)
        db.flush()
        db.add(SoftwareInstalado(nome=nome, ativo_id=a.id, dominio="ti"))
    db.commit()


class TestEscopoDePlantaNaContagem:
    """#4 — a tela filtrava os softwares, mas a contagem somava as unidades."""

    def test_conta_so_a_planta_pedida(self, db_session):
        a = _planta(db_session, "A")
        b = _planta(db_session, "B")
        _instalado_em(db_session, a, "Google Chrome", 3)
        _instalado_em(db_session, b, "Google Chrome", 7)

        so_a = dict(c.instalados_por_nome(db_session, planta_id=a.id))
        so_b = dict(c.instalados_por_nome(db_session, planta_id=b.id))

        assert so_a.get("Google Chrome") == 3
        assert so_b.get("Google Chrome") == 7

    def test_sem_filtro_soma_tudo(self, db_session):
        """O comportamento antigo continua disponível para quem quer o total."""
        a = _planta(db_session, "A")
        b = _planta(db_session, "B")
        _instalado_em(db_session, a, "Chrome", 3)
        _instalado_em(db_session, b, "Chrome", 7)

        assert dict(c.instalados_por_nome(db_session)).get("Chrome") == 10

    def test_nao_mistura_plantas(self, db_session):
        """O caso que produzia o número errado: uma unidade acima do
        licenciado e a outra não, parecendo as duas em risco."""
        a = _planta(db_session, "A")
        b = _planta(db_session, "B")
        _instalado_em(db_session, a, "AutoCAD", 12)   # acima
        _instalado_em(db_session, b, "AutoCAD", 2)    # dentro

        assert dict(c.instalados_por_nome(db_session, planta_id=a.id))["AutoCAD"] == 12
        assert dict(c.instalados_por_nome(db_session, planta_id=b.id))["AutoCAD"] == 2

    def test_instalacao_de_ativo_apagado_nao_conta(self, db_session):
        """Máquina removida do inventário não pode seguir inflando o número."""
        from datetime import datetime, timezone

        from app.models.core import Ativo

        a = _planta(db_session, "A")
        _instalado_em(db_session, a, "Chrome", 4)

        ativo = db_session.query(Ativo).filter(Ativo.planta_id == a.id).first()
        ativo.deleted_at = datetime.now(timezone.utc)
        db_session.commit()

        assert dict(c.instalados_por_nome(db_session, planta_id=a.id)).get("Chrome", 0) == 3


class TestSituacaoDaLicenca:
    """#6 — licença cancelada continuava contando seats."""

    def _licenca(self, db_session, software, situacao, seats=10, validade=None,
                 tipo="volume"):
        from app.models.software import Licenca

        lic = Licenca(software_id=software.id, tipo=tipo, seats=seats,
                      situacao=situacao, validade=validade, chave_versao=1)
        db_session.add(lic)
        db_session.commit()
        db_session.refresh(lic)
        return lic

    def _software(self, db_session, nome="Office"):
        from app.models.software import Software

        s = Software(nome=nome, padroes="office*")
        db_session.add(s)
        db_session.commit()
        db_session.refresh(s)
        return s

    def test_cancelada_nao_conta_seats(self, db_session):
        """O contrato acabou: os seats não são mais da empresa."""
        s = self._software(db_session)
        self._licenca(db_session, s, "cancelada", seats=50)

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id]
        if linha:
            assert linha[0]["licenciado"] == 0

    def test_expirada_nao_conta_seats(self, db_session):
        s = self._software(db_session)
        self._licenca(db_session, s, "expirada", seats=50)

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id]
        if linha:
            assert linha[0]["licenciado"] == 0

    def test_ativa_conta(self, db_session):
        s = self._software(db_session)
        self._licenca(db_session, s, "ativa", seats=50)

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id][0]
        assert linha["licenciado"] == 50

    def test_suspensa_conta(self, db_session):
        """Suspender é temporário: os seats continuam contratados.

        Tratá-la como cancelada faria a empresa parecer descoberta quando
        ainda tem o direito.
        """
        s = self._software(db_session)
        self._licenca(db_session, s, "suspensa", seats=50)

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id][0]
        assert linha["licenciado"] == 50

    def test_assinatura_vencida_nao_conta(self, db_session):
        s = self._software(db_session)
        self._licenca(db_session, s, "ativa", seats=50, tipo="assinatura",
                      validade=date.today() - timedelta(days=10))

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id]
        if linha:
            assert linha[0]["licenciado"] == 0

    def test_perpetua_com_data_antiga_conta(self, db_session):
        """Perpétua não vence — uma data antiga não pode zerar o direito."""
        s = self._software(db_session)
        self._licenca(db_session, s, "ativa", seats=50, tipo="perpetua",
                      validade=date(2015, 1, 1))

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id][0]
        assert linha["licenciado"] == 50

    def test_cancelada_nao_esconde_o_excedente(self, db_session):
        """O cenário que motivou a correção.

        Com a licença cancelada contando, instalar 60 com 50 "contratados"
        parecia conforme. Sem ela, o excedente aparece — que é a verdade.
        """
        s = self._software(db_session)
        self._licenca(db_session, s, "cancelada", seats=50)

        planta = _planta(db_session, "A")
        _instalado_em(db_session, planta, "Microsoft Office 2021", 60)

        linhas = c.calcular(db_session, [s])
        linha = [x for x in linhas if x["software_id"] == s.id][0]
        assert linha["licenciado"] == 0
        assert linha["instalado"] == 60
        assert linha["situacao"] == c.SituacaoConformidade.SEM_LICENCA
