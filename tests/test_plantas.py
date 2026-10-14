"""Multi-planta: cadastro, vínculo com usuário e ISOLAMENTO dos dados.

O ponto central destes testes é provar que um usuário de uma planta **não
enxerga** os ativos de outra — é o requisito de negócio do recurso.
"""
from __future__ import annotations

import pytest

from app.core.rate_limit import login_limiter, scan_limiter


@pytest.fixture(autouse=True)
def _liberar_rate_limit():
    """Estes testes fazem muitos logins seguidos e esbarram no limitador.

    O limitador é em memória e compartilhado pela sessão de testes; zerar entre
    casos evita 429 que não tem relação com o que está sendo verificado.
    """
    login_limiter._hits.clear()
    scan_limiter._hits.clear()
    yield
    login_limiter._hits.clear()
    scan_limiter._hits.clear()


def _criar_planta(client, auth_headers, nome, sigla):
    r = client.post("/api/v1/admin/plantas", json={"nome": nome, "sigla": sigla}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _criar_usuario(client, auth_headers, email, planta_id, papel="ti"):
    r = client.post(
        "/api/v1/usuarios",
        json={
            "nome": f"Operador {email}",
            "email": email,
            "papel": papel,
            "senha": "senha123",
            "planta_id": planta_id,
            "permissoes": {
                "inventarios": ["ti"],
                "modulos": ["ativos"],
                "pode_escrever": True,
                "pode_excluir": False,
            },
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _token(client, email):
    r = client.post("/api/v1/auth/login", data={"username": email, "password": "senha123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestCadastroDePlantas:
    def test_cria_e_lista(self, client, auth_headers):
        criada = _criar_planta(client, auth_headers, "Unidade Campinas", "CPS")
        assert criada["sigla"] == "CPS"
        assert criada["ativa"] is True
        assert criada["total_ativos"] == 0

        lista = client.get("/api/v1/admin/plantas", headers=auth_headers).json()
        assert any(p["sigla"] == "CPS" for p in lista)

    def test_sigla_e_normalizada_e_unica(self, client, auth_headers):
        _criar_planta(client, auth_headers, "Campinas", "cps")
        # A sigla é gravada em maiúsculas e não pode repetir (ignorando caixa).
        r = client.post("/api/v1/admin/plantas", json={"nome": "Outra", "sigla": "CPS"}, headers=auth_headers)
        assert r.status_code == 409
        assert "CPS" in r.json()["detail"]

    def test_sigla_curta_demais_e_recusada(self, client, auth_headers):
        r = client.post("/api/v1/admin/plantas", json={"nome": "X", "sigla": "A"}, headers=auth_headers)
        assert r.status_code == 422

    def test_atualiza(self, client, auth_headers):
        p = _criar_planta(client, auth_headers, "Campinas", "CPS")
        r = client.put(
            f"/api/v1/admin/plantas/{p['id']}",
            json={"nome": "Campinas II", "sigla": "CPS", "ativa": False},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["nome"] == "Campinas II"
        assert r.json()["ativa"] is False

    def test_nao_exclui_planta_com_ativo(self, client, auth_headers):
        p = _criar_planta(client, auth_headers, "Campinas", "CPS")
        u = _criar_usuario(client, auth_headers, "cps@teste.com", p["id"])
        h = _token(client, "cps@teste.com")
        assert client.post(
            "/api/v1/ativos",
            json={"dominio": "ti", "patrimonio": "CPS-0001", "numero_serie": "NS-CPS-0001", "tipo_item": "ativo"},
            headers=h,
        ).status_code == 201
        assert u["planta_id"] == p["id"]

        r = client.delete(f"/api/v1/admin/plantas/{p['id']}", headers=auth_headers)
        assert r.status_code == 409
        assert "ativo" in r.json()["detail"]

    def test_planta_sem_dados_pode_ser_excluida(self, client, auth_headers):
        p = _criar_planta(client, auth_headers, "Temporária", "TMP")
        assert client.delete(f"/api/v1/admin/plantas/{p['id']}", headers=auth_headers).status_code == 204

    def test_usuario_comum_nao_cadastra_planta(self, client, auth_headers):
        p = _criar_planta(client, auth_headers, "Campinas", "CPS")
        _criar_usuario(client, auth_headers, "comum@teste.com", p["id"])
        h = _token(client, "comum@teste.com")
        r = client.post("/api/v1/admin/plantas", json={"nome": "Pirata", "sigla": "PIR"}, headers=h)
        assert r.status_code == 403


class TestIsolamentoEntrePlantas:
    """O requisito central: cada um só vê a sua planta."""

    def _cenario(self, client, auth_headers):
        a = _criar_planta(client, auth_headers, "Campinas", "CPS")
        b = _criar_planta(client, auth_headers, "Recife", "REC")
        _criar_usuario(client, auth_headers, "a@teste.com", a["id"])
        _criar_usuario(client, auth_headers, "b@teste.com", b["id"])
        ha, hb = _token(client, "a@teste.com"), _token(client, "b@teste.com")
        client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": "SO-A", "numero_serie": "NS-SO-A", "tipo_item": "ativo"}, headers=ha)
        client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": "SO-B", "numero_serie": "NS-SO-B", "tipo_item": "ativo"}, headers=hb)
        return a, b, ha, hb

    def test_cada_usuario_ve_apenas_a_sua_planta(self, client, auth_headers):
        _, _, ha, hb = self._cenario(client, auth_headers)

        pat_a = [i["patrimonio"] for i in client.get("/api/v1/ativos", headers=ha).json()["items"]]
        pat_b = [i["patrimonio"] for i in client.get("/api/v1/ativos", headers=hb).json()["items"]]

        assert "SO-A" in pat_a and "SO-B" not in pat_a
        assert "SO-B" in pat_b and "SO-A" not in pat_b

    def test_ativo_ganha_a_planta_de_quem_criou(self, client, auth_headers):
        a, _, ha, _ = self._cenario(client, auth_headers)
        item = client.get("/api/v1/ativos", headers=ha).json()["items"][0]
        assert item["planta_id"] == a["id"]
        assert item["planta_sigla"] == "CPS"

    def test_nao_acessa_ativo_de_outra_planta_pelo_id(self, client, auth_headers):
        _, _, ha, hb = self._cenario(client, auth_headers)
        id_b = client.get("/api/v1/ativos", headers=hb).json()["items"][0]["id"]

        r = client.get(f"/api/v1/ativos/{id_b}", headers=ha)
        # 404 (e não 403) de propósito: não revelamos que o ativo existe.
        assert r.status_code == 404

    def test_nao_edita_ativo_de_outra_planta(self, client, auth_headers):
        _, _, ha, hb = self._cenario(client, auth_headers)
        id_b = client.get("/api/v1/ativos", headers=hb).json()["items"][0]["id"]

        r = client.put(f"/api/v1/ativos/{id_b}", json={"modelo": "Invadido"}, headers=ha)
        assert r.status_code == 404

    def test_administrador_ve_todas(self, client, auth_headers):
        self._cenario(client, auth_headers)
        itens = client.get("/api/v1/ativos", headers=auth_headers).json()["items"]
        patrimonios = {i["patrimonio"] for i in itens}
        assert {"SO-A", "SO-B"} <= patrimonios

    def test_administrador_escolhe_a_planta_pelo_cabecalho(self, client, auth_headers):
        a, b, _, _ = self._cenario(client, auth_headers)

        h_a = {**auth_headers, "X-Planta-Id": str(a["id"])}
        somente_a = client.get("/api/v1/ativos", headers=h_a).json()["items"]
        assert [i["patrimonio"] for i in somente_a] == ["SO-A"]

        # Consolidado: as duas juntas.
        h_todas = {**auth_headers, "X-Planta-Id": "todas"}
        todas = client.get("/api/v1/ativos", headers=h_todas).json()["items"]
        assert {"SO-A", "SO-B"} <= {i["patrimonio"] for i in todas}
        assert b["id"] != a["id"]


class TestListaDePlantasDoUsuario:
    def test_minhas_para_admin_traz_todas_as_ativas(self, client, auth_headers):
        _criar_planta(client, auth_headers, "Campinas", "CPS")
        lista = client.get("/api/v1/plantas/minhas", headers=auth_headers).json()
        assert any(p["sigla"] == "CPS" for p in lista)

    def test_minhas_para_usuario_comum_traz_so_a_dele(self, client, auth_headers):
        a = _criar_planta(client, auth_headers, "Campinas", "CPS")
        _criar_planta(client, auth_headers, "Recife", "REC")
        _criar_usuario(client, auth_headers, "comum2@teste.com", a["id"])

        h = _token(client, "comum2@teste.com")
        lista = client.get("/api/v1/plantas/minhas", headers=h).json()
        assert [p["sigla"] for p in lista] == ["CPS"]

    def test_planta_inativa_sai_do_seletor(self, client, auth_headers):
        p = _criar_planta(client, auth_headers, "Campinas", "CPS")
        client.put(
            f"/api/v1/admin/plantas/{p['id']}",
            json={"nome": "Campinas", "sigla": "CPS", "ativa": False},
            headers=auth_headers,
        )
        lista = client.get("/api/v1/plantas/minhas", headers=auth_headers).json()
        assert all(x["sigla"] != "CPS" for x in lista)
