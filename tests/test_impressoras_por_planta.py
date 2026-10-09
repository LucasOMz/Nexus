"""Impressora por planta.

Requisito: cada planta cadastra e gerencia a **sua** impressora; o perfil TI tem
acesso a esse cadastro, mas só enxerga/altera a impressora da própria planta.
A etiqueta (template) continua padronizada pelo administrador.
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


def _planta(client, auth, nome, sigla):
    r = client.post("/api/v1/admin/plantas", json={"nome": nome, "sigla": sigla}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


def _usuario(client, auth, email, planta_id, papel):
    r = client.post(
        "/api/v1/usuarios",
        json={
            "nome": f"User {email}", "email": email, "papel": papel, "senha": "senha123",
            "planta_id": planta_id,
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _token(client, email):
    r = client.post("/api/v1/auth/login", data={"username": email, "password": "senha123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _impressora(client, headers, nome, **extra):
    r = client.post(
        "/api/v1/admin/dispositivos",
        json={
            "nome": nome, "tipo": "compartilhamento",
            "compartilhamento": f"\\\\SRV\\{nome}", "formato": "zpl", "ativo": True,
            "padrao": True, **extra,
        },
        headers=headers,
    )
    return r


class TestCadastroDaImpressoraPorPlanta:
    def test_ti_cadastra_impressora_da_sua_planta(self, client, auth_headers):
        a = _planta(client, auth_headers, "Campinas", "CPS")
        _usuario(client, auth_headers, "ti.cps@teste.com", a["id"], "ti")
        h = _token(client, "ti.cps@teste.com")

        r = _impressora(client, h, "SATO-CPS")
        assert r.status_code == 201, r.text
        assert r.json()["planta_id"] == a["id"]

    def test_leitor_nao_gerencia_impressora(self, client, auth_headers):
        a = _planta(client, auth_headers, "Campinas", "CPS")
        _usuario(client, auth_headers, "leitor@teste.com", a["id"], "leitor")
        h = _token(client, "leitor@teste.com")

        r = _impressora(client, h, "NAO-PODE")
        assert r.status_code == 403
        assert "perfil TI" in r.json()["detail"]

    def test_cada_planta_tem_a_sua_impressora(self, client, auth_headers):
        a = _planta(client, auth_headers, "Campinas", "CPS")
        b = _planta(client, auth_headers, "Recife", "REC")
        _usuario(client, auth_headers, "ti.a@teste.com", a["id"], "ti")
        _usuario(client, auth_headers, "ti.b@teste.com", b["id"], "ti")
        ha, hb = _token(client, "ti.a@teste.com"), _token(client, "ti.b@teste.com")

        assert _impressora(client, ha, "SATO-CPS").status_code == 201
        assert _impressora(client, hb, "SATO-REC").status_code == 201

        nomes_a = [d["nome"] for d in client.get("/api/v1/admin/dispositivos", headers=ha).json()]
        nomes_b = [d["nome"] for d in client.get("/api/v1/admin/dispositivos", headers=hb).json()]

        assert nomes_a == ["SATO-CPS"]
        assert nomes_b == ["SATO-REC"]

    def test_admin_ve_todas_as_impressoras(self, client, auth_headers):
        a = _planta(client, auth_headers, "Campinas", "CPS")
        b = _planta(client, auth_headers, "Recife", "REC")
        _usuario(client, auth_headers, "ti.x@teste.com", a["id"], "ti")
        _usuario(client, auth_headers, "ti.y@teste.com", b["id"], "ti")
        _impressora(client, _token(client, "ti.x@teste.com"), "SATO-CPS")
        _impressora(client, _token(client, "ti.y@teste.com"), "SATO-REC")

        nomes = {d["nome"] for d in client.get("/api/v1/admin/dispositivos", headers=auth_headers).json()}
        assert {"SATO-CPS", "SATO-REC"} <= nomes

        # E pode focar numa planta pelo cabeçalho (seletor do topo).
        so_a = client.get("/api/v1/admin/dispositivos", headers={**auth_headers, "X-Planta-Id": str(a["id"])}).json()
        assert [d["nome"] for d in so_a] == ["SATO-CPS"]


class TestIsolamentoDaImpressora:
    def test_ti_nao_altera_impressora_de_outra_planta(self, client, auth_headers):
        a = _planta(client, auth_headers, "Campinas", "CPS")
        b = _planta(client, auth_headers, "Recife", "REC")
        _usuario(client, auth_headers, "ti.p@teste.com", a["id"], "ti")
        _usuario(client, auth_headers, "ti.q@teste.com", b["id"], "ti")
        ha, hb = _token(client, "ti.p@teste.com"), _token(client, "ti.q@teste.com")

        id_b = _impressora(client, hb, "SATO-REC").json()["id"]

        r = client.put(
            f"/api/v1/admin/dispositivos/{id_b}",
            json={"nome": "Invadida", "tipo": "compartilhamento", "formato": "zpl", "ativo": True},
            headers=ha,
        )
        assert r.status_code == 403
        assert "outra planta" in r.json()["detail"]

    def test_ti_nao_exclui_impressora_de_outra_planta(self, client, auth_headers):
        a = _planta(client, auth_headers, "Campinas", "CPS")
        b = _planta(client, auth_headers, "Recife", "REC")
        _usuario(client, auth_headers, "ti.m@teste.com", a["id"], "ti")
        _usuario(client, auth_headers, "ti.n@teste.com", b["id"], "ti")
        ha, hb = _token(client, "ti.m@teste.com"), _token(client, "ti.n@teste.com")

        id_b = _impressora(client, hb, "SATO-REC").json()["id"]
        assert client.delete(f"/api/v1/admin/dispositivos/{id_b}", headers=ha).status_code == 403

    def test_ti_altera_a_propria_impressora(self, client, auth_headers):
        a = _planta(client, auth_headers, "Campinas", "CPS")
        _usuario(client, auth_headers, "ti.z@teste.com", a["id"], "ti")
        h = _token(client, "ti.z@teste.com")

        criada = _impressora(client, h, "SATO-CPS").json()
        r = client.put(
            f"/api/v1/admin/dispositivos/{criada['id']}",
            json={"nome": "SATO-CPS v2", "tipo": "compartilhamento",
                  "compartilhamento": "\\\\DTAT7777\\SATO", "formato": "zpl", "ativo": True},
            headers=h,
        )
        assert r.status_code == 200, r.text
        assert r.json()["nome"] == "SATO-CPS v2"
        assert r.json()["planta_id"] == a["id"]

    def test_padrao_e_por_planta(self, client, auth_headers):
        """Marcar padrão numa planta não desmarca a padrão da outra."""
        a = _planta(client, auth_headers, "Campinas", "CPS")
        b = _planta(client, auth_headers, "Recife", "REC")
        _usuario(client, auth_headers, "ti.s@teste.com", a["id"], "ti")
        _usuario(client, auth_headers, "ti.t@teste.com", b["id"], "ti")
        ha, hb = _token(client, "ti.s@teste.com"), _token(client, "ti.t@teste.com")

        _impressora(client, ha, "SATO-CPS")
        _impressora(client, hb, "SATO-REC")

        padroes = [d for d in client.get("/api/v1/admin/dispositivos", headers=auth_headers).json() if d["padrao"]]
        assert len(padroes) == 2  # uma de cada planta


class TestSeletorDeImpressao:
    def test_operador_ve_so_a_impressora_da_planta(self, client, auth_headers):
        a = _planta(client, auth_headers, "Campinas", "CPS")
        b = _planta(client, auth_headers, "Recife", "REC")
        _usuario(client, auth_headers, "ti.u@teste.com", a["id"], "ti")
        _usuario(client, auth_headers, "ti.v@teste.com", b["id"], "ti")
        _impressora(client, _token(client, "ti.u@teste.com"), "SATO-CPS")
        _impressora(client, _token(client, "ti.v@teste.com"), "SATO-REC")

        ha = _token(client, "ti.u@teste.com")
        lista = client.get("/api/v1/print/dispositivos", headers=ha).json()
        assert [d["nome"] for d in lista] == ["SATO-CPS"]
        assert lista[0]["planta_sigla"] == "CPS"

    def test_nao_imprime_em_impressora_de_outra_planta(self, client, auth_headers):
        """Escolher a impressora de outra planta é recusado com mensagem clara."""
        a = _planta(client, auth_headers, "Campinas", "CPS")
        b = _planta(client, auth_headers, "Recife", "REC")
        _usuario(client, auth_headers, "ti.w@teste.com", a["id"], "ti")
        ub = _usuario(client, auth_headers, "ti.k@teste.com", b["id"], "ti")
        ha, hb = _token(client, "ti.w@teste.com"), _token(client, "ti.k@teste.com")

        id_b = _impressora(client, hb, "SATO-REC").json()["id"]

        # Ativo da planta A, impressora da planta B.
        ativo = client.post(
            "/api/v1/ativos",
            json={"dominio": "ti", "patrimonio": "CPS-IMP", "tipo_item": "ativo"},
            headers=ha,
        ).json()

        r = client.post(
            "/api/v1/print",
            json={"ativo_id": ativo["id"], "formato": "zpl", "dispositivo_id": id_b},
            headers=ha,
        )
        assert r.status_code == 400
        assert "outra planta" in r.json()["detail"]
        assert ub["planta_id"] == b["id"]


class TestAdministradorEscolheAPlanta:
    """O administrador cadastra/edita impressora para QUALQUER planta.

    Antes, estando na visão consolidada, o sistema caía sempre na primeira
    planta — não havia como cadastrar para outra.
    """

    def test_admin_cadastra_para_a_planta_escolhida(self, client, auth_headers):
        a = _planta(client, auth_headers, "Campinas", "CPS")
        b = _planta(client, auth_headers, "Recife", "REC")

        # Escolhe explicitamente a SEGUNDA planta (a que não seria o padrão).
        r = _impressora(client, auth_headers, "SATO-REC", planta_id=b["id"])
        assert r.status_code == 201, r.text
        assert r.json()["planta_id"] == b["id"]
        assert r.json()["planta_sigla"] == "REC"
        assert a["id"] != b["id"]

    def test_admin_cadastra_uma_impressora_por_planta(self, client, auth_headers):
        a = _planta(client, auth_headers, "Campinas", "CPS")
        b = _planta(client, auth_headers, "Recife", "REC")

        assert _impressora(client, auth_headers, "SATO-CPS", planta_id=a["id"]).status_code == 201
        assert _impressora(client, auth_headers, "SATO-REC", planta_id=b["id"]).status_code == 201

        por_planta = {}
        for d in client.get("/api/v1/admin/dispositivos", headers=auth_headers).json():
            por_planta.setdefault(d["planta_sigla"], []).append(d["nome"])

        assert por_planta["CPS"] == ["SATO-CPS"]
        assert por_planta["REC"] == ["SATO-REC"]

    def test_admin_move_impressora_de_planta(self, client, auth_headers):
        a = _planta(client, auth_headers, "Campinas", "CPS")
        b = _planta(client, auth_headers, "Recife", "REC")
        criada = _impressora(client, auth_headers, "SATO-X", planta_id=a["id"]).json()

        r = client.put(
            f"/api/v1/admin/dispositivos/{criada['id']}",
            json={"nome": "SATO-X", "tipo": "compartilhamento", "compartilhamento": "\\\\S\\SATO",
                  "formato": "zpl", "ativo": True, "planta_id": b["id"]},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["planta_id"] == b["id"]

    def test_planta_inexistente_e_recusada(self, client, auth_headers):
        r = _impressora(client, auth_headers, "SATO-Z", planta_id=99999)
        assert r.status_code == 404
        assert "não encontrada" in r.json()["detail"]

    def test_ti_nao_consegue_mover_para_outra_planta(self, client, auth_headers):
        """O técnico não burla o isolamento mandando planta_id no corpo."""
        a = _planta(client, auth_headers, "Campinas", "CPS")
        b = _planta(client, auth_headers, "Recife", "REC")
        id_b = _impressora(client, auth_headers, "SATO-REC", planta_id=b["id"]).json()["id"]
        _usuario(client, auth_headers, "ti.iso@teste.com", a["id"], "ti")
        h = _token(client, "ti.iso@teste.com")

        # Tenta editar a impressora da outra planta já informando a planta dele.
        r = client.put(
            f"/api/v1/admin/dispositivos/{id_b}",
            json={"nome": "Invadida", "tipo": "compartilhamento", "formato": "zpl",
                  "ativo": True, "planta_id": a["id"]},
            headers=h,
        )
        assert r.status_code == 403

    def test_planta_do_ti_vence_o_campo_do_formulario(self, client, auth_headers):
        """TI mandando planta_id de outra planta: grava na dele."""
        a = _planta(client, auth_headers, "Campinas", "CPS")
        b = _planta(client, auth_headers, "Recife", "REC")
        _usuario(client, auth_headers, "ti.forca@teste.com", a["id"], "ti")
        h = _token(client, "ti.forca@teste.com")

        r = _impressora(client, h, "SATO-FORCADA", planta_id=b["id"])
        assert r.status_code == 201, r.text
        assert r.json()["planta_id"] == a["id"]


class TestEtiquetaContinuaGlobal:
    def test_ti_nao_gerencia_templates(self, client, auth_headers):
        """A etiqueta é padronizada pelo administrador — o TI não altera."""
        a = _planta(client, auth_headers, "Campinas", "CPS")
        _usuario(client, auth_headers, "ti.tpl@teste.com", a["id"], "ti")
        h = _token(client, "ti.tpl@teste.com")

        r = client.post(
            "/api/v1/admin/etiquetas",
            json={"nome": "Pirata", "largura_mm": 100, "altura_mm": 50, "dpi": 203, "campos": []},
            headers=h,
        )
        assert r.status_code == 403
