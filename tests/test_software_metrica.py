"""T9 — a métrica da licença, e o erro que ela evita.

## O cenário que custa dinheiro

    Você tem 10 licenças de Microsoft 365. 10 pessoas usam.
    Maria tem notebook E desktop → 11 máquinas com o programa instalado.
    → o sistema compara 11 instalações com 10 seats e acusa EXCEDENTE.

Está errado. E o erro **não é de exibição**: alguém compra uma licença que
não falta, e a conta "piora" a cada máquina nova, mesmo sem entrar gente
nova.

## Por que a escolha é PERGUNTADA

Um valor padrão faria o operador passar reto — e o cálculo seguiria errado em
silêncio, que é exatamente o problema que a métrica existe para resolver.
Aqui, a escolha errada vira **escolha**: alguém olhou e decidiu.
"""
from __future__ import annotations

import pytest

from app.core import segredos


@pytest.fixture(autouse=True)
def _com_chave_mestra(monkeypatch):
    monkeypatch.setenv(segredos.VARIAVEL, "chave-mestra-de-teste")
    yield


@pytest.fixture
def db_session(client):
    from app.database import get_db
    from app.main import app

    return next(app.dependency_overrides[get_db]())


def _software(db, nome="Microsoft 365", padroes="microsoft 365*"):
    from app.models.software import Software

    s = Software(nome=nome, padroes=padroes)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _licenca(db, software, metrica, seats=10):
    from app.models.software import Licenca

    lic = Licenca(software_id=software.id, tipo="assinatura", seats=seats,
                  metrica=metrica, validade=None, chave_versao=1,
                  valor_mensal=100)
    db.add(lic)
    db.commit()
    db.refresh(lic)
    return lic


def _instalado_em(db, ativo, nome):
    from app.models.software import SoftwareInstalado

    db.add(SoftwareInstalado(nome=nome, ativo_id=ativo.id, dominio="ti"))
    db.commit()


def _maquina(db, planta, patrimonio):
    from app.models.core import Ativo

    a = Ativo(dominio="ti", tipo_item="ativo", patrimonio=patrimonio, numero_serie=f"NS-{patrimonio}",
              planta_id=planta.id, status="estoque")
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _planta(db, sigla="A"):
    from app.models.core import Planta

    p = db.query(Planta).filter(Planta.sigla == sigla).first()
    if p:
        return p
    p = Planta(nome=f"Unidade {sigla}", sigla=sigla)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


class TestObrigatoria:
    """A escolha é perguntada — a API não assume."""

    def test_o_schema_exige(self):
        from app.schemas.software import LicencaIn

        assert LicencaIn.model_fields["metrica"].is_required(), (
            "a métrica ficou opcional — com um padrão, o operador passa reto "
            "e o cálculo segue errado em silêncio"
        )

    def test_a_api_recusa_sem_metrica(self, client, auth_headers):
        sw = client.post("/api/v1/softwares",
                         json={"nome": "Office"}, headers=auth_headers).json()
        r = client.post("/api/v1/licencas",
                        json={"software_id": sw["id"], "tipo": "volume", "seats": 5},
                        headers=auth_headers)
        assert r.status_code == 422, "aceitou uma licença sem dizer como conta"
        assert "metrica" in r.text

    def test_aceita_com_metrica(self, client, auth_headers):
        sw = client.post("/api/v1/softwares",
                         json={"nome": "Office"}, headers=auth_headers).json()
        r = client.post("/api/v1/licencas",
                        json={"software_id": sw["id"], "tipo": "volume",
                              "seats": 5, "metrica": "dispositivo"},
                        headers=auth_headers)
        assert r.status_code == 201, r.text
        assert r.json()["metrica"] == "dispositivo"

    def test_o_modelo_tem_padrao_para_o_legado(self, db_session):
        """O padrão existe para os registros anteriores a este campo.

        Sem ele, uma licença antiga ficaria sem valor e o cálculo quebraria
        na leitura.
        """
        s = _software(db_session, "Legado", "legado*")
        from app.models.software import Licenca

        lic = Licenca(software_id=s.id, tipo="perpetua", seats=1, chave_versao=1)
        db_session.add(lic)
        db_session.commit()
        db_session.refresh(lic)
        assert getattr(lic.metrica, "value", lic.metrica) == "dispositivo"


class TestOCalculo:
    """O cenário que custa dinheiro."""

    def test_por_dispositivo_conta_maquinas(self, db_session):
        from app.services import conformidade as c

        planta = _planta(db_session)
        s = _software(db_session)
        _licenca(db_session, s, "dispositivo", seats=10)

        for i in range(11):
            a = _maquina(db_session, planta, f"MAQ-{i}")
            _instalado_em(db_session, a, "Microsoft 365")

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id][0]
        assert linha["instalado"] == 11
        assert linha["licenciado"] == 10
        assert linha["situacao"] == c.SituacaoConformidade.EXCEDENTE
        assert linha["metrica"] == "dispositivo"

    def test_por_pessoa_nao_conta_maquinas(self, db_session):
        """O caso do Microsoft 365.

        10 pessoas, 11 máquinas (uma delas com dois computadores). Está
        CONFORME — e com a métrica errada apareceria como excedente.
        """
        from app.models.core import Usuario
        from app.models.software import AtribuicaoLicenca
        from app.services import conformidade as c

        planta = _planta(db_session)
        s = _software(db_session)
        lic = _licenca(db_session, s, "usuario", seats=10)

        # 10 pessoas, 11 máquinas instaladas.
        for i in range(11):
            a = _maquina(db_session, planta, f"PC-{i}")
            _instalado_em(db_session, a, "Microsoft 365")

        # Cada pessoa tem uma atribuição; a primeira tem duas.
        for i in range(10):
            u = Usuario(nome=f"Pessoa {i}", email=f"p{i}@teste.com",
                        senha_hash="x", papel="leitor", ativo=True)
            db_session.add(u)
            db_session.flush()
            for _ in range(2 if i == 0 else 1):
                db_session.add(AtribuicaoLicenca(licenca_id=lic.id, usuario_id=u.id))
        db_session.commit()

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id][0]
        # 10 pessoas, ainda que 11 atribuições e 11 máquinas.
        assert linha["instalado"] == 10
        assert linha["licenciado"] == 10
        assert linha["situacao"] == c.SituacaoConformidade.CONFORME
        assert linha["metrica"] == "usuario"

    def test_a_metrica_aparece_na_linha(self, db_session):
        """11 pessoas e 11 máquinas são a mesma cifra e significam coisas
        diferentes — sem saber qual foi usada, o número não é interpretável."""
        from app.services import conformidade as c

        s = _software(db_session)
        _licenca(db_session, s, "usuario", seats=5)

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id][0]
        assert "metrica" in linha
        assert linha["metrica"] == "usuario"

    def test_usuarios_distintos_nao_repete_pessoa(self, db_session):
        """Duas atribuições para a MESMA pessoa contam uma."""
        from app.models.core import Usuario
        from app.models.software import AtribuicaoLicenca
        from app.services import conformidade as c

        s = _software(db_session)
        lic = _licenca(db_session, s, "usuario", seats=5)

        u = Usuario(nome="Ana", email="ana@teste.com", senha_hash="x",
                    papel="leitor", ativo=True)
        db_session.add(u)
        db_session.flush()
        db_session.add(AtribuicaoLicenca(licenca_id=lic.id, usuario_id=u.id))
        db_session.add(AtribuicaoLicenca(licenca_id=lic.id, usuario_id=u.id))
        db_session.commit()

        assert c.usuarios_distintos(db_session, s.id) == 1

    def test_sem_atribuicao_por_pessoa_zera(self, db_session):
        """Licença por pessoa sem ninguém designado = zero em uso.

        Não é erro: é a informação de que os seats estão livres — e depende
        de alguém registrar quem usa.
        """
        from app.services import conformidade as c

        s = _software(db_session)
        _licenca(db_session, s, "usuario", seats=5)

        assert c.usuarios_distintos(db_session, s.id) == 0
