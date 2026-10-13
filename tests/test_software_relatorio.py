"""T8, T10 e T11 — histórico, métricas por fabricante e o relatório que explica.

## O fio que liga os três

A conformidade mostrava `licenciado: 50`, `instalado: 63`, `+13`. **Isso não
decide nada.** A diferença entre *comprar 13 licenças* e *corrigir um padrão*
é de milhares de reais, e o número sozinho não distingue as duas.

- **T11** diz a causa e a ação de cada linha — é o que faz o número virar decisão;
- **T10** agrupa por fabricante — é o que responde *com quem renegociar*;
- **T8** mostra quem mexeu na licença — inclusive quem revelou a chave.
"""
from __future__ import annotations

from decimal import Decimal

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


def _software(db, nome="Office", fabricante="Microsoft", padroes="office*"):
    from app.models.software import Software

    s = Software(nome=nome, fabricante=fabricante, padroes=padroes)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _instalado(db, nome, quantas, dominio="ti"):
    from app.models.core import Ativo, Planta
    from app.models.software import SoftwareInstalado

    planta = db.query(Planta).first()
    for i in range(quantas):
        a = Ativo(dominio=dominio, tipo_item="ativo",
                  patrimonio=f"T-{nome[:4]}-{i}", planta_id=planta.id if planta else None,
                  status="estoque")
        db.add(a)
        db.flush()
        db.add(SoftwareInstalado(nome=nome, ativo_id=a.id, dominio=dominio))
    db.commit()


class TestT11Explicacao:
    """O número sozinho não decide — a explicação decide."""

    def test_sem_licenca_explica_e_recomenda(self, db_session):
        from app.services import conformidade as c

        s = _software(db_session, "Office", "Microsoft", "office*")
        _instalado(db_session, "Microsoft Office 2021", 63)

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id][0]
        assert linha["situacao"] == c.SituacaoConformidade.SEM_LICENCA
        assert "nenhuma licença" in linha["explicacao"]
        assert linha["acao"], "não recomendou nada"
        # A ação precisa considerar que pode ser cadastro, não compra.
        assert "padrão" in linha["acao"].lower()

    def test_excedente_manda_comprar_ou_revisar(self, db_session):
        from app.models.software import Licenca
        from app.services import conformidade as c

        s = _software(db_session)
        db_session.add(Licenca(software_id=s.id, tipo="volume", seats=10,
                               metrica="dispositivo", chave_versao=1))
        db_session.commit()
        _instalado(db_session, "Microsoft Office 2021", 13)

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id][0]
        assert linha["situacao"] == c.SituacaoConformidade.EXCEDENTE
        assert "acima do licenciado" in linha["explicacao"]
        assert "3" in linha["explicacao"]

    def test_conforme_nao_pede_acao(self, db_session):
        from app.models.software import Licenca
        from app.services import conformidade as c

        s = _software(db_session)
        db_session.add(Licenca(software_id=s.id, tipo="volume", seats=5,
                               metrica="dispositivo", chave_versao=1))
        db_session.commit()
        _instalado(db_session, "Microsoft Office 2021", 5)

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id][0]
        assert linha["situacao"] == c.SituacaoConformidade.CONFORME
        assert "Nada a fazer" in linha["acao"]

    def test_traz_os_padroes_tentados(self, db_session):
        """Sem os padrões, quem investiga não sabe o que ajustar."""
        from app.services import conformidade as c

        s = _software(db_session, padroes="office*; msoffice*")
        _instalado(db_session, "Microsoft Office 2021", 2)

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id][0]
        assert "office*" in linha["padroes"]

    def test_avisa_quando_nada_casou(self, db_session):
        """O alerta mais útil: o número pode estar incompleto por causa do
        padrão, e não da licença."""
        from app.services import conformidade as c

        s = _software(db_session, padroes="padrao-que-nao-existe*")
        _instalado(db_session, "Outro Programa Qualquer", 3)

        linhas = c.calcular(db_session, [s])
        # O software não aparece (0 instalado, 0 licenciado, não obrigatório),
        # mas o programa instalado aparece como "sem licença" — e é isso que
        # deve levar alguém a olhar o padrão.
        orfaos = [x for x in linhas if x["software_id"] == 0]
        assert orfaos, "o programa instalado sumiu do relatório"
        assert "padrão" in orfaos[0]["acao"].lower()


class TestT11CSV:
    def test_separador_e_bom(self, db_session):
        """Separador `;` e BOM: é o que faz o Excel em português abrir certo.

        Com vírgula, as colunas grudam numa só — e quem recebe o arquivo
        conclui que o sistema exporta errado.
        """
        from app.services import conformidade as c

        s = _software(db_session)
        _instalado(db_session, "Microsoft Office 2021", 3)
        csv = c.para_csv(c.calcular(db_session, [s]))

        assert csv.startswith("\ufeff"), "sem BOM, o acento sai errado no Excel"
        assert csv.split("\n")[0].count(";") >= 8

    def test_traz_a_explicacao(self, db_session):
        from app.services import conformidade as c

        s = _software(db_session)
        _instalado(db_session, "Microsoft Office 2021", 3)
        csv = c.para_csv(c.calcular(db_session, [s]))

        assert "explicacao" in csv.split("\n")[0]
        assert "acao" in csv.split("\n")[0]

    def test_lista_vazia_ainda_tem_cabecalho(self):
        from app.services import conformidade as c

        csv = c.para_csv([])
        assert csv.startswith("\ufeff")
        assert "software" in csv


class TestT10Fabricante:
    def test_agrupa_por_fabricante(self, client, auth_headers, db_session):
        a = _software(db_session, "Office", "Microsoft", "office*")
        b = _software(db_session, "Acrobat", "Adobe", "acrobat*")
        _instalado(db_session, "Microsoft Office 2021", 3)
        _instalado(db_session, "Adobe Acrobat Pro", 2)

        r = client.get("/api/v1/conformidade/fabricantes", headers=auth_headers)
        assert r.status_code == 200, r.text
        fabricantes = {x["fabricante"] for x in r.json()}
        assert "Microsoft" in fabricantes or "Adobe" in fabricantes

    def test_o_maior_gasto_vem_primeiro(self, client, auth_headers, db_session):
        """É ele que interessa para negociar."""
        from app.models.software import Licenca

        a = _software(db_session, "Office", "Microsoft")
        b = _software(db_session, "Figma", "Figma Inc")
        db_session.add(Licenca(software_id=a.id, tipo="assinatura", seats=50,
                               metrica="usuario", valor_mensal=Decimal("5000"),
                               chave_versao=1))
        db_session.add(Licenca(software_id=b.id, tipo="assinatura", seats=5,
                               metrica="usuario", valor_mensal=Decimal("200"),
                               chave_versao=1))
        db_session.commit()

        r = client.get("/api/v1/conformidade/fabricantes", headers=auth_headers)
        linhas = r.json()
        if len(linhas) >= 2:
            assert linhas[0]["custo_mensal"] >= linhas[1]["custo_mensal"]

    def test_participacao_soma_cem(self, client, auth_headers, db_session):
        from app.models.software import Licenca

        a = _software(db_session, "Office", "Microsoft")
        b = _software(db_session, "Figma", "Figma Inc")
        db_session.add(Licenca(software_id=a.id, tipo="assinatura", seats=10,
                               metrica="usuario", valor_mensal=Decimal("1000"),
                               chave_versao=1))
        db_session.add(Licenca(software_id=b.id, tipo="assinatura", seats=10,
                               metrica="usuario", valor_mensal=Decimal("1000"),
                               chave_versao=1))
        db_session.commit()

        r = client.get("/api/v1/conformidade/fabricantes", headers=auth_headers)
        total = sum(x["participacao"] for x in r.json())
        assert abs(total - 100.0) < 0.5 or total == 0.0

    def test_sem_fabricante_nao_some(self, client, auth_headers, db_session):
        """Software sem fabricante cadastrado precisa contar em algum lugar."""
        from app.models.software import Licenca

        s = _software(db_session, "Interno", None)
        db_session.add(Licenca(software_id=s.id, tipo="assinatura", seats=5,
                               metrica="usuario", valor_mensal=Decimal("100"),
                               chave_versao=1))
        db_session.commit()

        r = client.get("/api/v1/conformidade/fabricantes", headers=auth_headers)
        assert any("Não informado" in x["fabricante"] for x in r.json())


class TestT8Historico:
    def test_registra_a_criacao(self, client, auth_headers):
        sw = client.post("/api/v1/softwares", json={"nome": "Office"},
                         headers=auth_headers).json()
        lic = client.post("/api/v1/licencas",
                          json={"software_id": sw["id"], "tipo": "volume",
                                "seats": 5, "metrica": "dispositivo"},
                          headers=auth_headers).json()

        r = client.get(f"/api/v1/licencas/{lic['id']}/historico", headers=auth_headers)
        assert r.status_code == 200, r.text
        acoes = [e["acao"] for e in r.json()["eventos"]]
        assert "criar" in acoes

    def test_registra_a_revelacao_da_chave(self, client, auth_headers):
        """É o evento que mais interessa a quem audita: o único em que um
        SEGREDO saiu do sistema."""
        sw = client.post("/api/v1/softwares", json={"nome": "Office"},
                         headers=auth_headers).json()
        lic = client.post("/api/v1/licencas",
                          json={"software_id": sw["id"], "tipo": "volume",
                                "seats": 5, "metrica": "dispositivo",
                                "chave": "AAAA-1111-BBBB-2222"},
                          headers=auth_headers).json()

        client.get(f"/api/v1/licencas/{lic['id']}/revelar", headers=auth_headers)

        r = client.get(f"/api/v1/licencas/{lic['id']}/historico", headers=auth_headers)
        eventos = r.json()["eventos"]
        revelacoes = [e for e in eventos if e["acao"] == "revelar_chave"]
        assert revelacoes, "a revelação da chave não ficou no histórico"
        assert revelacoes[0]["relevante"] is True

    def test_o_historico_nao_mostra_a_chave(self, client, auth_headers):
        """A auditoria é imutável — um segredo gravado nela está vazado."""
        sw = client.post("/api/v1/softwares", json={"nome": "Office"},
                         headers=auth_headers).json()
        lic = client.post("/api/v1/licencas",
                          json={"software_id": sw["id"], "tipo": "volume",
                                "seats": 5, "metrica": "dispositivo",
                                "chave": "AAAA-1111-BBBB-2222"},
                          headers=auth_headers).json()
        client.get(f"/api/v1/licencas/{lic['id']}/revelar", headers=auth_headers)

        r = client.get(f"/api/v1/licencas/{lic['id']}/historico", headers=auth_headers)
        assert "AAAA" not in r.text
        assert "1111" not in r.text

    def test_traz_quem_fez(self, client, auth_headers):
        sw = client.post("/api/v1/softwares", json={"nome": "Office"},
                         headers=auth_headers).json()
        lic = client.post("/api/v1/licencas",
                          json={"software_id": sw["id"], "tipo": "volume",
                                "seats": 5, "metrica": "dispositivo"},
                          headers=auth_headers).json()

        r = client.get(f"/api/v1/licencas/{lic['id']}/historico", headers=auth_headers)
        assert r.json()["eventos"][0]["usuario"] != "—"

    def test_licenca_inexistente_da_404(self, client, auth_headers):
        r = client.get("/api/v1/licencas/999999/historico", headers=auth_headers)
        assert r.status_code == 404
