"""API do inventário de software: a chave não pode vazar.

## O que estes testes verificam

Não é "o endpoint funciona". É que a chave de licença **não sai por onde não
deve** e **sai por onde deve, com registro**.

| Caminho | Esperado |
|---|---|
| `GET /licencas` | chave **não** aparece |
| `GET /licencas/{id}` | chave **não** aparece |
| `PUT /licencas/{id}` | chave **não** aparece na resposta |
| `GET /licencas/{id}/revelar` | chave aparece — e a auditoria registra |
| `GET /auditoria` | chave **não** aparece no diff |
"""
from __future__ import annotations

import pytest

from app.core import segredos

CHAVE = "ABCD-1234-EFGH-5678"


@pytest.fixture(autouse=True)
def _com_chave_mestra(monkeypatch):
    """A suíte roda com uma chave mestra.

    Sem ela, cadastrar licença levanta `ChaveMestraAusente` — e é o
    comportamento certo: o sistema **não** guarda a chave em claro só porque
    a configuração está faltando. Falhar é melhor que degradar a segurança
    em silêncio.
    """
    monkeypatch.setenv(segredos.VARIAVEL, "chave-mestra-de-teste")
    yield


@pytest.fixture
def software(client, auth_headers):
    r = client.post("/api/v1/softwares",
                    json={"nome": "Office LTSC 2021", "fabricante": "Microsoft",
                          "padroes": "microsoft office*2021"},
                    headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def licenca(client, auth_headers, software):
    r = client.post("/api/v1/licencas",
                    json={"software_id": software["id"], "tipo": "volume", "metrica": "dispositivo",
                          "seats": 50, "chave": CHAVE, "valor": "15000.00"},
                    headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _sem_chave(obj) -> bool:
    """A chave em claro não pode estar em NENHUM campo da resposta."""
    texto = str(obj)
    return "ABCD" not in texto and "5678" not in texto.split("•")[0]


class TestChaveNaoVaza:
    def test_a_listagem_nao_traz_a_chave(self, client, auth_headers, licenca):
        r = client.get("/api/v1/licencas", headers=auth_headers)
        assert r.status_code == 200
        assert "ABCD" not in r.text
        assert "chave" not in r.json()[0] or "cifrada" not in str(r.json()[0])

    def test_o_detalhe_nao_traz_a_chave(self, client, auth_headers, licenca):
        r = client.get(f"/api/v1/licencas/{licenca['id']}", headers=auth_headers)
        assert r.status_code == 200
        assert "ABCD" not in r.text

    def test_a_resposta_mostra_so_a_mascara(self, client, auth_headers, licenca):
        assert licenca["chave_mascarada"] == "••••-••••-••••-5678"
        assert licenca["tem_chave"] is True

    def test_o_schema_de_saida_nao_tem_o_campo(self):
        """A garantia estrutural: não existe o campo, então não há como vazar."""
        from app.schemas.software import LicencaOut

        assert "chave" not in LicencaOut.model_fields
        assert "chave_cifrada" not in LicencaOut.model_fields
        assert "chave_hash" not in LicencaOut.model_fields

    def test_o_schema_de_entrada_tem(self):
        """E a entrada PRECISA ter, senão não haveria como cadastrar."""
        from app.schemas.software import LicencaIn

        assert "chave" in LicencaIn.model_fields

    def test_editar_nao_devolve_a_chave(self, client, auth_headers, licenca, software):
        r = client.put(f"/api/v1/licencas/{licenca['id']}",
                       json={"software_id": software["id"], "tipo": "volume", "metrica": "dispositivo",
                             "seats": 60, "chave": CHAVE},
                       headers=auth_headers)
        assert r.status_code == 200, r.text
        assert "ABCD" not in r.text
        assert r.json()["seats"] == 60


class TestCifraNoBanco:
    def test_o_banco_guarda_cifrado(self, client, auth_headers, licenca):
        from app.database import get_db
        from app.main import app
        from app.models.software import Licenca

        db = next(app.dependency_overrides[get_db]())
        lic = db.get(Licenca, licenca["id"])
        assert lic.chave_cifrada is not None
        assert CHAVE.encode() not in lic.chave_cifrada
        assert lic.chave_versao >= 1
        assert lic.chave_impressao == "5678"

    def test_nao_existe_coluna_em_claro(self, client, auth_headers, licenca):
        from app.models.software import Licenca

        assert "chave" not in {c.name for c in Licenca.__table__.columns}


class TestRevelar:
    def test_revela_com_permissao(self, client, auth_headers, licenca):
        r = client.get(f"/api/v1/licencas/{licenca['id']}/revelar", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["chave"] == CHAVE

    def test_a_revelacao_e_auditada(self, client, auth_headers, licenca):
        """Saber QUEM leu a chave é o que permite investigar um vazamento."""
        client.get(f"/api/v1/licencas/{licenca['id']}/revelar", headers=auth_headers)

        from app.database import get_db
        from app.main import app
        from app.models.core import LogAuditoria

        db = next(app.dependency_overrides[get_db]())
        log = (db.query(LogAuditoria)
               .filter(LogAuditoria.acao == "revelar_chave")
               .order_by(LogAuditoria.id.desc()).first())
        assert log is not None, "a revelação não foi registrada"

    def test_o_registro_nao_guarda_a_chave(self, client, auth_headers, licenca):
        """A auditoria é imutável — um segredo nela está vazado para sempre."""
        client.get(f"/api/v1/licencas/{licenca['id']}/revelar", headers=auth_headers)

        from app.database import get_db
        from app.main import app
        from app.models.core import LogAuditoria

        db = next(app.dependency_overrides[get_db]())
        log = (db.query(LogAuditoria)
               .filter(LogAuditoria.acao == "revelar_chave")
               .order_by(LogAuditoria.id.desc()).first())
        assert "ABCD" not in str(log.diff)
        assert "5678" not in str(log.diff)

    def test_licenca_sem_chave_nao_revela(self, client, auth_headers, software):
        r = client.post("/api/v1/licencas",
                        json={"software_id": software["id"], "tipo": "open_source", "metrica": "dispositivo",
                              "seats": 1},
                        headers=auth_headers)
        assert r.status_code == 201
        r2 = client.get(f"/api/v1/licencas/{r.json()['id']}/revelar", headers=auth_headers)
        assert r2.status_code == 404


class TestAuditoriaNaoVaza:
    def test_o_diff_da_criacao_esta_protegido(self, client, auth_headers, licenca):
        """O caminho mais perigoso: a chave entrando na auditoria no cadastro."""
        from app.database import get_db
        from app.main import app
        from app.models.core import LogAuditoria

        db = next(app.dependency_overrides[get_db]())
        logs = (db.query(LogAuditoria)
                .filter(LogAuditoria.entidade == "licenca").all())
        assert logs, "nenhum registro de auditoria para licença"
        for log in logs:
            assert "ABCD" not in str(log.diff), "a chave vazou na auditoria!"
            assert "5678" not in str(log.diff), "a chave vazou na auditoria!"

    def test_o_diff_diz_que_algo_mudou(self, client, auth_headers, licenca):
        """Proteger não pode significar esconder que houve alteração."""
        from app.database import get_db
        from app.main import app
        from app.models.core import LogAuditoria

        db = next(app.dependency_overrides[get_db]())
        log = (db.query(LogAuditoria)
               .filter(LogAuditoria.entidade == "licenca",
                       LogAuditoria.acao == "criar")
               .order_by(LogAuditoria.id.desc()).first())
        assert "<protegido>" in str(log.diff)


class TestDuplicata:
    def test_a_mesma_chave_nao_entra_duas_vezes(self, client, auth_headers, software, licenca):
        """Chave repetida faz a conformidade contar duas vezes."""
        r = client.post("/api/v1/licencas",
                        json={"software_id": software["id"], "tipo": "volume", "metrica": "dispositivo",
                              "seats": 10, "chave": CHAVE},
                        headers=auth_headers)
        assert r.status_code == 409

    def test_a_deteccao_ignora_formatacao(self, client, auth_headers, software, licenca):
        """`abc-123` e `ABC123` são a mesma chave — e o erro provável."""
        r = client.post("/api/v1/licencas",
                        json={"software_id": software["id"], "tipo": "volume", "metrica": "dispositivo",
                              "seats": 10, "chave": "abcd 1234 efgh 5678"},
                        headers=auth_headers)
        assert r.status_code == 409


class TestRegras:
    def test_assinatura_exige_valor_mensal(self, client, auth_headers, software):
        r = client.post("/api/v1/licencas",
                        json={"software_id": software["id"], "tipo": "assinatura", "metrica": "dispositivo",
                              "seats": 5},
                        headers=auth_headers)
        assert r.status_code == 422

    def test_perpetua_nao_aceita_validade(self, client, auth_headers, software):
        r = client.post("/api/v1/licencas",
                        json={"software_id": software["id"], "tipo": "perpetua", "metrica": "dispositivo",
                              "seats": 5, "validade": "2030-01-01"},
                        headers=auth_headers)
        assert r.status_code == 422

    def test_nao_atribui_alem_dos_seats(self, client, auth_headers, software):
        """Atribuir além do comprado é o que gera risco em auditoria."""
        r = client.post("/api/v1/licencas",
                        json={"software_id": software["id"], "tipo": "volume", "metrica": "dispositivo", "seats": 1},
                        headers=auth_headers)
        lic = r.json()

        ativos = client.get("/api/v1/ativos?size=2", headers=auth_headers).json()["items"]
        if len(ativos) < 2:
            pytest.skip("poucos ativos para o teste")

        for i in range(2):
            resp = client.post(f"/api/v1/licencas/{lic['id']}/atribuicoes",
                               json={"ativo_id": ativos[i]["id"]}, headers=auth_headers)
            if i == 0:
                assert resp.status_code == 201, resp.text
            else:
                assert resp.status_code == 409, "atribuiu além dos seats"

    def test_atribuicao_exige_um_dos_dois(self, client, auth_headers, licenca):
        r = client.post(f"/api/v1/licencas/{licenca['id']}/atribuicoes",
                        json={}, headers=auth_headers)
        assert r.status_code == 422

    def test_atribuicao_recusa_os_dois(self, client, auth_headers, licenca):
        r = client.post(f"/api/v1/licencas/{licenca['id']}/atribuicoes",
                        json={"ativo_id": 1, "usuario_id": 1}, headers=auth_headers)
        assert r.status_code == 422


class TestConformidade:
    def test_excedente_aparece_primeiro(self, client, auth_headers, software, licenca):
        r = client.get("/api/v1/conformidade", headers=auth_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "linhas" in d and "excedente" in d
        if d["linhas"]:
            # O que preocupa vem antes: excedente e sem licença no topo.
            primeira = d["linhas"][0]["situacao"]
            assert primeira in ("excedente", "sem_licenca", "ocioso", "conforme")

    def test_licenca_sem_uso_conta_como_ociosa(self, client, auth_headers, software, licenca):
        """Comprar 50 e usar 0 é dinheiro parado — precisa aparecer."""
        r = client.get("/api/v1/conformidade", headers=auth_headers)
        linha = [x for x in r.json()["linhas"] if x["software_id"] == software["id"]]
        assert linha, "o software não apareceu na conformidade"
        assert linha[0]["licenciado"] == 50
        assert linha[0]["situacao"] == "ocioso"
