"""Empréstimo de ativos e o calendário de devoluções.

Regras: o empréstimo exige número de chamado e devolução prevista; a tela de
status não pode "emprestar" sem esses dados; a devolução encerra o registro e
libera o ativo; o calendário mostra a agenda por período.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.core.rate_limit import login_limiter, scan_limiter


@pytest.fixture(autouse=True)
def _liberar_rate_limit():
    login_limiter._hits.clear()
    scan_limiter._hits.clear()
    yield
    login_limiter._hits.clear()
    scan_limiter._hits.clear()


def _ativo(client, auth_headers, patrimonio="EMP-001"):
    return client.post(
        "/api/v1/ativos",
        json={"dominio": "ti", "patrimonio": patrimonio, "numero_serie": f"NS-{patrimonio}", "modelo": "Latitude", "tipo_item": "ativo"},
        headers=auth_headers,
    ).json()["id"]


def _daqui(dias):
    return (date.today() + timedelta(days=dias)).isoformat()


def _emprestar(client, auth_headers, ativo_id, chamado="CH-2026-0001", dias=10):
    return client.post(
        f"/api/v1/ativos/{ativo_id}/emprestimo",
        json={"numero_chamado": chamado, "devolucao_prevista": _daqui(dias)},
        headers=auth_headers,
    )


class TestEmprestimo:
    def test_empresta_com_chamado_e_data(self, client, auth_headers):
        aid = _ativo(client, auth_headers)
        r = _emprestar(client, auth_headers, aid, "CH-2026-0042", 10)

        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["status"] == "emprestado"
        assert corpo["numero_chamado"] == "CH-2026-0042"
        assert corpo["emprestado_em"] == date.today().isoformat()
        assert corpo["devolucao_prevista"] == _daqui(10)
        assert corpo["emprestimo_atrasado"] is False

    def test_chamado_e_obrigatorio(self, client, auth_headers):
        aid = _ativo(client, auth_headers)
        r = client.post(
            f"/api/v1/ativos/{aid}/emprestimo",
            json={"numero_chamado": "", "devolucao_prevista": _daqui(5)},
            headers=auth_headers,
        )
        assert r.status_code == 422  # campo obrigatório

    def test_chamado_so_com_espacos_e_recusado(self, client, auth_headers):
        aid = _ativo(client, auth_headers)
        r = client.post(
            f"/api/v1/ativos/{aid}/emprestimo",
            json={"numero_chamado": "   ", "devolucao_prevista": _daqui(5)},
            headers=auth_headers,
        )
        assert r.status_code == 400
        assert "chamado" in r.json()["detail"].lower()

    def test_data_no_passado_e_recusada(self, client, auth_headers):
        aid = _ativo(client, auth_headers)
        r = _emprestar(client, auth_headers, aid, dias=-1)
        assert r.status_code == 400
        assert "anterior a hoje" in r.json()["detail"]

    def test_nao_empresta_duas_vezes(self, client, auth_headers):
        aid = _ativo(client, auth_headers)
        _emprestar(client, auth_headers, aid, "CH-A", 5)
        r = _emprestar(client, auth_headers, aid, "CH-B", 5)

        assert r.status_code == 400
        assert "CH-A" in r.json()["detail"]  # diz qual chamado está aberto

    def test_ativo_descartado_nao_empresta(self, client, auth_headers):
        aid = _ativo(client, auth_headers)
        client.patch(f"/api/v1/ativos/{aid}/status", json={"status": "descartado"}, headers=auth_headers)
        r = _emprestar(client, auth_headers, aid)
        assert r.status_code == 400

    def test_trocar_status_nao_empresta_sem_chamado(self, client, auth_headers):
        """O atalho de status não pode burlar o chamado obrigatório."""
        aid = _ativo(client, auth_headers)
        r = client.patch(f"/api/v1/ativos/{aid}/status", json={"status": "emprestado"}, headers=auth_headers)

        assert r.status_code == 400
        assert "Emprestar" in r.json()["detail"]
        # E o ativo continua no status anterior.
        assert client.get(f"/api/v1/ativos/{aid}", headers=auth_headers).json()["status"] == "estoque"

    def test_emprestimo_e_auditado(self, client, auth_headers):
        aid = _ativo(client, auth_headers)
        _emprestar(client, auth_headers, aid, "CH-AUD", 5)

        logs = client.get("/api/v1/admin/auditoria", params={"acao": "emprestimo"}, headers=auth_headers).json()["itens"]
        assert logs, "empréstimo não foi auditado"
        assert logs[0]["usuario_nome"] == "Admin"
        assert logs[0]["diff"]["numero_chamado"] == "CH-AUD"


class TestDevolucao:
    def test_devolucao_limpa_o_emprestimo(self, client, auth_headers):
        aid = _ativo(client, auth_headers)
        _emprestar(client, auth_headers, aid, "CH-DEV", 5)

        r = client.post(f"/api/v1/ativos/{aid}/devolucao", headers=auth_headers)
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["status"] == "estoque"
        assert corpo["numero_chamado"] is None
        assert corpo["emprestado_em"] is None
        assert corpo["devolucao_prevista"] is None

    def test_devolver_o_que_nao_esta_emprestado(self, client, auth_headers):
        aid = _ativo(client, auth_headers)
        r = client.post(f"/api/v1/ativos/{aid}/devolucao", headers=auth_headers)
        assert r.status_code == 400
        assert "não está emprestado" in r.json()["detail"]

    def test_pode_emprestar_de_novo_apos_devolver(self, client, auth_headers):
        aid = _ativo(client, auth_headers)
        _emprestar(client, auth_headers, aid, "CH-1", 5)
        client.post(f"/api/v1/ativos/{aid}/devolucao", headers=auth_headers)

        assert _emprestar(client, auth_headers, aid, "CH-2", 5).status_code == 200

    def test_trocar_status_encerra_o_emprestimo(self, client, auth_headers):
        """Mudar o status por outro caminho não deixa empréstimo pendurado."""
        aid = _ativo(client, auth_headers)
        _emprestar(client, auth_headers, aid, "CH-X", 5)

        client.patch(f"/api/v1/ativos/{aid}/status", json={"status": "manutencao"}, headers=auth_headers)
        ativo = client.get(f"/api/v1/ativos/{aid}", headers=auth_headers).json()
        assert ativo["numero_chamado"] is None
        assert ativo["devolucao_prevista"] is None

    def test_devolucao_em_atraso_e_registrada(self, client, auth_headers):
        aid = _ativo(client, auth_headers)
        _emprestar(client, auth_headers, aid, "CH-ATR", 1)
        client.post(f"/api/v1/ativos/{aid}/devolucao", headers=auth_headers)

        logs = client.get("/api/v1/admin/auditoria", params={"acao": "devolucao"}, headers=auth_headers).json()["itens"]
        assert logs and logs[0]["diff"]["numero_chamado"] == "CH-ATR"


class TestCalendario:
    def test_lista_emprestimos_do_periodo(self, client, auth_headers):
        aid = _ativo(client, auth_headers, "CAL-001")
        _emprestar(client, auth_headers, aid, "CH-CAL", 15)

        r = client.get(
            "/api/v1/calendario/emprestimos",
            params={"inicio": _daqui(0), "fim": _daqui(30)},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["total"] >= 1
        item = next(i for i in corpo["itens"] if i["patrimonio"] == "CAL-001")
        assert item["numero_chamado"] == "CH-CAL"
        assert item["devolucao_prevista"] == _daqui(15)
        assert item["dias_restantes"] == 15
        assert item["atrasado"] is False

    def test_periodo_anterior_ao_emprestimo_nao_mostra_nada(self, client, auth_headers):
        """Um empréstimo de hoje não pode aparecer num período que já passou.

        (Um empréstimo longo APARECE em todos os meses que ele cobre — é o
        comportamento desejado e está no teste seguinte.)
        """
        aid = _ativo(client, auth_headers, "CAL-002")
        _emprestar(client, auth_headers, aid, "CH-FORA", 5)

        r = client.get(
            "/api/v1/calendario/emprestimos",
            params={"inicio": _daqui(-60), "fim": _daqui(-30)},
            headers=auth_headers,
        ).json()
        assert all(i["patrimonio"] != "CAL-002" for i in r["itens"])

    def test_emprestimo_que_atravessa_o_periodo_aparece(self, client, auth_headers):
        """Um empréstimo longo precisa aparecer em qualquer mês que ele cobrir."""
        aid = _ativo(client, auth_headers, "CAL-003")
        _emprestar(client, auth_headers, aid, "CH-LONGO", 90)

        for inicio, fim in ((_daqui(0), _daqui(30)), (_daqui(30), _daqui(60)), (_daqui(60), _daqui(95))):
            r = client.get(
                "/api/v1/calendario/emprestimos",
                params={"inicio": inicio, "fim": fim},
                headers=auth_headers,
            ).json()
            assert any(i["patrimonio"] == "CAL-003" for i in r["itens"]), f"sumiu em {inicio}..{fim}"

    def test_resumo_conta_emprestados_e_atrasados(self, client, auth_headers):
        antes = client.get("/api/v1/calendario/resumo", headers=auth_headers).json()
        aid = _ativo(client, auth_headers, "CAL-004")
        _emprestar(client, auth_headers, aid, "CH-RES", 8)

        depois = client.get("/api/v1/calendario/resumo", headers=auth_headers).json()
        assert depois["emprestados"] == antes["emprestados"] + 1
        assert depois["chamados_abertos"] >= 1

    def test_busca_por_chamado(self, client, auth_headers):
        aid = _ativo(client, auth_headers, "CAL-005")
        _emprestar(client, auth_headers, aid, "CH-BUSCA-99", 5)

        r = client.get("/api/v1/calendario/busca", params={"chamado": "BUSCA-99"}, headers=auth_headers).json()
        assert any(i["patrimonio"] == "CAL-005" for i in r)

    def test_devolvido_sai_do_calendario(self, client, auth_headers):
        aid = _ativo(client, auth_headers, "CAL-006")
        _emprestar(client, auth_headers, aid, "CH-SAI", 5)
        client.post(f"/api/v1/ativos/{aid}/devolucao", headers=auth_headers)

        r = client.get(
            "/api/v1/calendario/emprestimos",
            params={"inicio": _daqui(0), "fim": _daqui(30)},
            headers=auth_headers,
        ).json()
        assert all(i["patrimonio"] != "CAL-006" for i in r["itens"])


class TestCalendarioPorPlanta:
    """O calendário é visível para TODOS, mas cada um vê só a sua planta."""

    def _planta(self, client, auth_headers, nome, sigla):
        return client.post(
            "/api/v1/admin/plantas", json={"nome": nome, "sigla": sigla}, headers=auth_headers
        ).json()["id"]

    def _leitor(self, client, auth_headers, email, planta_id):
        r = client.post(
            "/api/v1/usuarios",
            json={"nome": f"Leitor {email}", "email": email, "papel": "leitor",
                  "senha": "senha123", "planta_id": planta_id},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        login = client.post("/api/v1/auth/login", data={"username": email, "password": "senha123"})
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def _emprestar_na_planta(self, client, auth_headers, planta_id, patrimonio, chamado):
        h = {**auth_headers, "X-Planta-Id": str(planta_id)}
        ativo = client.post(
            "/api/v1/ativos",
            json={"dominio": "ti", "patrimonio": patrimonio, "numero_serie": f"NS-{patrimonio}", "tipo_item": "ativo"},
            headers=h,
        ).json()
        r = client.post(
            f"/api/v1/ativos/{ativo['id']}/emprestimo",
            json={"numero_chamado": chamado, "devolucao_prevista": _daqui(7)},
            headers=h,
        )
        assert r.status_code == 200, r.text

    def test_perfil_leitor_tem_o_modulo_calendario(self, client, auth_headers):
        """Todos os perfis enxergam o calendário por padrão."""
        from app.core.permissoes import permissoes_padrao

        for papel in ("admin", "ti", "auditor", "leitor"):
            assert "calendario" in permissoes_padrao(papel)["modulos"], papel

    def test_leitor_ve_apenas_a_propria_planta(self, client, auth_headers):
        a = self._planta(client, auth_headers, "Campinas", "CPS")
        b = self._planta(client, auth_headers, "Recife", "REC")
        self._emprestar_na_planta(client, auth_headers, a, "VIS-A", "CH-A")
        self._emprestar_na_planta(client, auth_headers, b, "VIS-B", "CH-B")

        h = self._leitor(client, auth_headers, "leitor.vis@teste.com", a)
        itens = client.get("/api/v1/calendario/emprestimos", headers=h).json()["itens"]
        patrimonios = {i["patrimonio"] for i in itens}

        assert "VIS-A" in patrimonios
        assert "VIS-B" not in patrimonios, "vazou equipamento de outra planta"

    def test_admin_ve_todas_as_plantas(self, client, auth_headers):
        a = self._planta(client, auth_headers, "Campinas", "CPS")
        b = self._planta(client, auth_headers, "Recife", "REC")
        self._emprestar_na_planta(client, auth_headers, a, "TOD-A", "CH-A")
        self._emprestar_na_planta(client, auth_headers, b, "TOD-B", "CH-B")

        patrimonios = {i["patrimonio"] for i in client.get("/api/v1/calendario/emprestimos", headers=auth_headers).json()["itens"]}
        assert {"TOD-A", "TOD-B"} <= patrimonios

    def test_resumo_tambem_respeita_a_planta(self, client, auth_headers):
        a = self._planta(client, auth_headers, "Campinas", "CPS")
        b = self._planta(client, auth_headers, "Recife", "REC")
        self._emprestar_na_planta(client, auth_headers, a, "RES-A", "CH-A")
        self._emprestar_na_planta(client, auth_headers, b, "RES-B", "CH-B")

        h = self._leitor(client, auth_headers, "leitor.res@teste.com", a)
        resumo = client.get("/api/v1/calendario/resumo", headers=h).json()
        total_admin = client.get("/api/v1/calendario/resumo", headers=auth_headers).json()["emprestados"]

        assert resumo["emprestados"] < total_admin, "o leitor não pode ver o total geral"

    def test_busca_por_chamado_respeita_a_planta(self, client, auth_headers):
        a = self._planta(client, auth_headers, "Campinas", "CPS")
        b = self._planta(client, auth_headers, "Recife", "REC")
        self._emprestar_na_planta(client, auth_headers, b, "BUS-B", "CH-SEGREDO")

        h = self._leitor(client, auth_headers, "leitor.bus@teste.com", a)
        achados = client.get("/api/v1/calendario/busca", params={"chamado": "CH-SEGREDO"}, headers=h).json()
        assert achados == [], "não pode achar empréstimo de outra planta"

    def test_usuario_comum_sem_planta_recebe_explicacao(self, client, auth_headers):
        """Sem planta não há o que mostrar — e o sistema diz o porquê."""
        r = client.post(
            "/api/v1/usuarios",
            json={"nome": "Sem Planta", "email": "sem.planta@teste.com", "papel": "leitor",
                  "senha": "senha123", "planta_id": None},
            headers=auth_headers,
        )
        assert r.status_code == 201
        login = client.post("/api/v1/auth/login", data={"username": "sem.planta@teste.com", "password": "senha123"})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}

        r = client.get("/api/v1/calendario/emprestimos", headers=h)
        assert r.status_code == 400
        assert "planta" in r.json()["detail"].lower()
