"""Favoritos da barra lateral — gravados no BANCO, por usuário.

O ajuste precisa acompanhar a pessoa: ela marca os módulos que usa no
computador da sala e, ao entrar em outra máquina, a barra vem do mesmo jeito.
Guardar no navegador não atendia isso.
"""
from __future__ import annotations

import pytest

from app.core.rate_limit import login_limiter, scan_limiter


@pytest.fixture(autouse=True)
def _liberar_rate_limit():
    login_limiter._hits.clear()
    scan_limiter._hits.clear()
    yield
    login_limiter._hits.clear()
    scan_limiter._hits.clear()


def _login(client, email, senha="senha123"):
    r = client.post("/api/v1/auth/login", data={"username": email, "password": senha})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _novo_usuario(client, auth_headers, email, papel="leitor"):
    client.post("/api/v1/usuarios",
                json={"nome": f"User {email}", "email": email, "papel": papel, "senha": "senha123"},
                headers=auth_headers)
    return _login(client, email)


class TestFavoritosNoBanco:
    def test_comeca_vazio(self, client, auth_headers):
        assert client.get("/api/v1/auth/me", headers=auth_headers).json()["barra_favoritos"] == []

    def test_salva_e_le_de_volta(self, client, auth_headers):
        r = client.put("/api/v1/auth/preferencias",
                       json={"barra_favoritos": ["ativos", "calendario"]},
                       headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["barra_favoritos"] == ["ativos", "calendario"]
        assert client.get("/api/v1/auth/me", headers=auth_headers).json()["barra_favoritos"] == \
            ["ativos", "calendario"]

    def test_favoritos_vem_no_login(self, client, auth_headers):
        """É o que faz a barra já subir certa, sem uma chamada extra.

        Usa um usuário criado no teste: o `auth_headers` do conftest é um token
        pronto (id 1), não um login com senha.
        """
        h = _novo_usuario(client, auth_headers, "login.fav@teste.com")
        client.put("/api/v1/auth/preferencias",
                   json={"barra_favoritos": ["manutencoes"]}, headers=h)

        corpo = client.post("/api/v1/auth/login",
                            data={"username": "login.fav@teste.com", "password": "senha123"}).json()
        assert corpo["user"]["barra_favoritos"] == ["manutencoes"]

    def test_ordem_e_preservada(self, client, auth_headers):
        """A ordem define quais ficam mais acima na barra."""
        ordem = ["calendario", "ativos", "manutencoes"]
        client.put("/api/v1/auth/preferencias", json={"barra_favoritos": ordem}, headers=auth_headers)
        assert client.get("/api/v1/auth/me", headers=auth_headers).json()["barra_favoritos"] == ordem

    def test_limpar_deixa_vazio(self, client, auth_headers):
        client.put("/api/v1/auth/preferencias",
                   json={"barra_favoritos": ["ativos"]}, headers=auth_headers)
        client.put("/api/v1/auth/preferencias", json={"barra_favoritos": []}, headers=auth_headers)
        assert client.get("/api/v1/auth/me", headers=auth_headers).json()["barra_favoritos"] == []

    def test_sobrevive_ao_novo_login(self, client, auth_headers):
        """O caso central: entrar de OUTRO computador traz a mesma barra."""
        h = _novo_usuario(client, auth_headers, "outro.pc@teste.com")
        client.put("/api/v1/auth/preferencias",
                   json={"barra_favoritos": ["relatorios"]}, headers=h)

        # Novo login, como se fosse outra máquina.
        novo = _login(client, "outro.pc@teste.com")
        assert client.get("/api/v1/auth/me", headers=novo).json()["barra_favoritos"] == ["relatorios"]


class TestFavoritosSaoPessoais:
    def test_cada_usuario_tem_os_seus(self, client, auth_headers):
        h_ana = _novo_usuario(client, auth_headers, "ana.fav@teste.com")
        h_bia = _novo_usuario(client, auth_headers, "bia.fav@teste.com")

        client.put("/api/v1/auth/preferencias",
                   json={"barra_favoritos": ["ativos", "produtos"]}, headers=h_ana)
        client.put("/api/v1/auth/preferencias",
                   json={"barra_favoritos": ["calendario"]}, headers=h_bia)

        assert client.get("/api/v1/auth/me", headers=h_ana).json()["barra_favoritos"] == \
            ["ativos", "produtos"]
        assert client.get("/api/v1/auth/me", headers=h_bia).json()["barra_favoritos"] == \
            ["calendario"]

    def test_o_admin_tambem_tem_os_dele(self, client, auth_headers):
        """As preferências do administrador não mudam por causa de outros."""
        h_ana = _novo_usuario(client, auth_headers, "carla.fav@teste.com")

        client.put("/api/v1/auth/preferencias",
                   json={"barra_favoritos": ["ativos"]}, headers=auth_headers)
        client.put("/api/v1/auth/preferencias",
                   json={"barra_favoritos": ["calendario", "relatorios"]}, headers=h_ana)

        assert client.get("/api/v1/auth/me", headers=auth_headers).json()["barra_favoritos"] == \
            ["ativos"]

    def test_nao_da_para_alterar_a_de_outro(self, client, auth_headers):
        """O alvo é sempre quem está logado — não há id no corpo."""
        h_ana = _novo_usuario(client, auth_headers, "duda.fav@teste.com")

        # Mesmo tentando mandar um id, o endpoint ignora: salva em quem chamou.
        r = client.put("/api/v1/auth/preferencias",
                       json={"barra_favoritos": ["ativos"], "usuario_id": 1}, headers=h_ana)
        assert r.status_code == 422, "campo extra deveria ser recusado"

        assert client.get("/api/v1/auth/me", headers=h_ana).json()["barra_favoritos"] == []
        assert client.get("/api/v1/auth/me", headers=auth_headers).json()["barra_favoritos"] == []

    def test_exige_login(self, client):
        r = client.put("/api/v1/auth/preferencias", json={"barra_favoritos": ["ativos"]})
        assert r.status_code == 401


class TestLimitesDoCampo:
    def test_lista_gigante_e_cortada(self, client, auth_headers):
        """É preferência de tela, não campo livre para crescer sem limite."""
        r = client.put("/api/v1/auth/preferencias",
                       json={"barra_favoritos": [f"mod{i}" for i in range(500)]},
                       headers=auth_headers)
        assert r.status_code == 200
        assert len(r.json()["barra_favoritos"]) == 80

    def test_nome_muito_longo_e_cortado(self, client, auth_headers):
        r = client.put("/api/v1/auth/preferencias",
                       json={"barra_favoritos": ["x" * 300]}, headers=auth_headers)
        assert len(r.json()["barra_favoritos"][0]) == 40

    def test_vazios_sao_descartados(self, client, auth_headers):
        r = client.put("/api/v1/auth/preferencias",
                       json={"barra_favoritos": ["ativos", "   ", "", "produtos"]},
                       headers=auth_headers)
        assert r.json()["barra_favoritos"] == ["ativos", "produtos"]

    def test_tipo_errado_e_recusado(self, client, auth_headers):
        r = client.put("/api/v1/auth/preferencias",
                       json={"barra_favoritos": "ativos"}, headers=auth_headers)
        assert r.status_code == 422

    def test_json_quebrado_no_banco_nao_derruba(self, client, auth_headers):
        """Um valor inválido gravado à mão não pode quebrar o login."""
        from app.database import get_db

        sessao = next(client.app.dependency_overrides[get_db]())
        from app.models.core import Usuario
        u = sessao.get(Usuario, 1)
        u.barra_favoritos = "{isso nao e json"
        sessao.commit()

        r = client.get("/api/v1/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["barra_favoritos"] == []


class TestOrdemDaGaveta:
    """A ordem da lista inteira, separada dos favoritos.

    Antes havia só um campo. Como a gaveta lista TODOS os módulos, reordenar um
    item não favoritado perdia a posição ao reabrir — o usuário reordenava e
    encontrava tudo diferente de novo.
    """

    def test_ordem_fica_em_campo_proprio(self, client, auth_headers):
        r = client.put("/api/v1/auth/preferencias",
                       json={"barra_ordem": ["relatorios", "ativos", "manutencoes"]},
                       headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["barra_ordem"] == ["relatorios", "ativos", "manutencoes"]

    def test_ordem_nao_apaga_os_favoritos(self, client, auth_headers):
        client.put("/api/v1/auth/preferencias",
                   json={"barra_favoritos": ["ativos", "relatorios"]}, headers=auth_headers)
        r = client.put("/api/v1/auth/preferencias",
                       json={"barra_ordem": ["relatorios", "ativos"]}, headers=auth_headers).json()
        assert r["barra_favoritos"] == ["ativos", "relatorios"], "a ordem apagou os favoritos"

    def test_favoritar_nao_apaga_a_ordem(self, client, auth_headers):
        client.put("/api/v1/auth/preferencias",
                   json={"barra_ordem": ["relatorios", "ativos"]}, headers=auth_headers)
        r = client.put("/api/v1/auth/preferencias",
                       json={"barra_favoritos": ["ativos"]}, headers=auth_headers).json()
        assert r["barra_ordem"] == ["relatorios", "ativos"], "favoritar apagou a ordem"

    def test_as_duas_sobrevivem_ao_novo_login(self, client, auth_headers):
        h = _novo_usuario(client, auth_headers, "ordem.pc@teste.com")
        ordem = ["relatorios", "manutencoes", "ativos", "calendario"]
        client.put("/api/v1/auth/preferencias",
                   json={"barra_favoritos": ["ativos", "relatorios"], "barra_ordem": ordem}, headers=h)

        u = _login(client, "ordem.pc@teste.com")
        dados = client.get("/api/v1/auth/me", headers=u).json()
        assert dados["barra_ordem"] == ordem
        assert dados["barra_favoritos"] == ["ativos", "relatorios"]

    def test_ordem_completa_e_aceita(self, client, auth_headers):
        """A gaveta tem ~11 módulos — o limite precisa cobrir a lista toda."""
        ordem = [f"mod{i}" for i in range(70)]
        r = client.put("/api/v1/auth/preferencias", json={"barra_ordem": ordem}, headers=auth_headers)
        assert len(r.json()["barra_ordem"]) == 70

    def test_comeca_vazio(self, client, auth_headers):
        assert client.get("/api/v1/auth/me", headers=auth_headers).json()["barra_ordem"] == []

    def test_json_quebrado_na_ordem_nao_derruba(self, client, auth_headers):
        from app.database import get_db
        from app.models.core import Usuario

        sessao = next(client.app.dependency_overrides[get_db]())
        u = sessao.get(Usuario, 1)
        u.barra_ordem = "{quebrado"
        sessao.commit()

        r = client.get("/api/v1/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["barra_ordem"] == []
