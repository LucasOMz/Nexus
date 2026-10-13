"""T6 — listagem de atribuições, nas duas visões.

## O que faltava

O backend criava e liberava atribuição, mas **não listava**. A aba da tela
só mostrava contagem, sem ter de onde tirar os dados.

## Por que DUAS visões

```
/licencas/{id}/atribuicoes   → quem usa esta licença
/atribuicoes?ativo_id=…      → o que esta máquina tem
```

A segunda responde a pergunta do dia a dia: *"posso formatar este
computador?"*. Sem ela, a resposta exigiria abrir licença por licença — o
caminho contrário ao de quem está com a máquina na mão.
"""
from __future__ import annotations

import pytest

from app.core import segredos


@pytest.fixture(autouse=True)
def _com_chave_mestra(monkeypatch):
    monkeypatch.setenv(segredos.VARIAVEL, "chave-mestra-de-teste")
    yield


@pytest.fixture
def cenario(client, auth_headers):
    """Uma licença com 3 seats e um ativo para atribuir."""
    sw = client.post("/api/v1/softwares",
                     json={"nome": "Office", "padroes": "office*"},
                     headers=auth_headers).json()
    lic = client.post("/api/v1/licencas",
                      json={"software_id": sw["id"], "tipo": "volume",
                            "seats": 3, "metrica": "dispositivo"},
                      headers=auth_headers).json()
    ativos = client.get("/api/v1/ativos?size=3", headers=auth_headers).json().get("items", [])
    return {"software": sw, "licenca": lic, "ativos": ativos}


class TestListarDaLicenca:
    def test_lista_vazia(self, client, auth_headers, cenario):
        r = client.get(f"/api/v1/licencas/{cenario['licenca']['id']}/atribuicoes",
                       headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == []

    def test_lista_o_que_foi_atribuido(self, client, auth_headers, cenario):
        if not cenario["ativos"]:
            pytest.skip("sem ativos para atribuir")

        ativo = cenario["ativos"][0]
        client.post(f"/api/v1/licencas/{cenario['licenca']['id']}/atribuicoes",
                    json={"ativo_id": ativo["id"]}, headers=auth_headers)

        r = client.get(f"/api/v1/licencas/{cenario['licenca']['id']}/atribuicoes",
                       headers=auth_headers)
        assert len(r.json()) == 1
        assert r.json()[0]["ativo_id"] == ativo["id"]

    def test_resolve_o_patrimonio(self, client, auth_headers, cenario):
        """A tela não deve precisar de uma segunda chamada por linha."""
        if not cenario["ativos"]:
            pytest.skip("sem ativos")

        ativo = cenario["ativos"][0]
        client.post(f"/api/v1/licencas/{cenario['licenca']['id']}/atribuicoes",
                    json={"ativo_id": ativo["id"]}, headers=auth_headers)

        r = client.get(f"/api/v1/licencas/{cenario['licenca']['id']}/atribuicoes",
                       headers=auth_headers)
        assert r.json()[0]["ativo_patrimonio"] == ativo["patrimonio"]

    def test_licenca_inexistente_da_404(self, client, auth_headers):
        r = client.get("/api/v1/licencas/999999/atribuicoes", headers=auth_headers)
        assert r.status_code == 404

    def test_a_liberada_sai_da_lista(self, client, auth_headers, cenario):
        if not cenario["ativos"]:
            pytest.skip("sem ativos")

        ativo = cenario["ativos"][0]
        a = client.post(f"/api/v1/licencas/{cenario['licenca']['id']}/atribuicoes",
                        json={"ativo_id": ativo["id"]}, headers=auth_headers).json()

        client.delete(f"/api/v1/licencas/{cenario['licenca']['id']}/atribuicoes/{a['id']}",
                      headers=auth_headers)

        r = client.get(f"/api/v1/licencas/{cenario['licenca']['id']}/atribuicoes",
                       headers=auth_headers)
        assert r.json() == [], "a atribuição liberada continuou na lista"


class TestVisaoInversa:
    def test_por_ativo(self, client, auth_headers, cenario):
        """A pergunta do dia a dia: o que esta máquina tem?"""
        if not cenario["ativos"]:
            pytest.skip("sem ativos")

        ativo = cenario["ativos"][0]
        client.post(f"/api/v1/licencas/{cenario['licenca']['id']}/atribuicoes",
                    json={"ativo_id": ativo["id"]}, headers=auth_headers)

        r = client.get(f"/api/v1/atribuicoes?ativo_id={ativo['id']}", headers=auth_headers)
        assert r.status_code == 200
        assert len(r.json()) >= 1
        assert all(x["ativo_id"] == ativo["id"] for x in r.json())

    def test_sem_filtro_devolve_tudo_da_planta(self, client, auth_headers, cenario):
        r = client.get("/api/v1/atribuicoes", headers=auth_headers)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_filtro_por_ativo_sem_resultado(self, client, auth_headers):
        r = client.get("/api/v1/atribuicoes?ativo_id=999999", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == []

    def test_filtro_por_usuario(self, client, auth_headers, cenario):
        r = client.get("/api/v1/atribuicoes?usuario_id=999999", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == []


class TestEscopoDePlanta:
    def test_nao_lista_atribuicao_de_outra_planta(self, client, auth_headers):
        """A atribuição não tem planta própria — herda a da licença.

        Sem conferir, daria para listar quem usa a licença de outra unidade
        sabendo o id.
        """
        from app.core.security import create_access_token, hash_password
        from app.database import get_db
        from app.main import app
        from app.models.core import Planta, Usuario
        from app.models.software import AtribuicaoLicenca, Licenca, Software

        db = next(app.dependency_overrides[get_db]())
        a = Planta(nome="Unidade A", sigla="UA")
        b = Planta(nome="Unidade B", sigla="UB")
        db.add_all([a, b])
        db.commit()
        db.refresh(a)
        db.refresh(b)

        sw = Software(nome="Office")
        db.add(sw)
        db.commit()
        db.refresh(sw)

        lic = Licenca(software_id=sw.id, tipo="volume", seats=5,
                      metrica="dispositivo", planta_id=b.id, chave_versao=1)
        db.add(lic)
        db.commit()
        db.refresh(lic)
        db.add(AtribuicaoLicenca(licenca_id=lic.id, ativo_id=1))
        db.commit()

        u = Usuario(nome="User A", email="ua@teste.com",
                    senha_hash=hash_password("x"), papel="ti", ativo=True,
                    planta_id=a.id)
        db.add(u)
        db.commit()
        db.refresh(u)
        h = {"Authorization": f"Bearer {create_access_token(u.id, u.papel.value, u.email)}"}

        r = client.get("/api/v1/atribuicoes", headers=h)
        assert r.status_code in (200, 403)
        if r.status_code == 200:
            assert r.json() == [], "listou atribuição de outra unidade"
