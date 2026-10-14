"""Notificações do dia — avisos de empréstimo no sino da barra superior.

O caso principal: **no dia da devolução**, quem tem o equipamento emprestado
recebe o aviso. Também avisa atrasos e devoluções próximas.

Cada usuário vê o da sua planta; o administrador vê todas.
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


def _ativo(client, auth_headers, patrimonio, modelo="Latitude 5420"):
    return client.post(
        "/api/v1/ativos",
        json={"dominio": "ti", "patrimonio": patrimonio, "numero_serie": f"NS-{patrimonio}", "modelo": modelo, "tipo_item": "ativo"},
        headers=auth_headers,
    ).json()["id"]


def _emprestar(client, auth_headers, ativo_id, chamado, dias):
    r = client.post(
        f"/api/v1/ativos/{ativo_id}/emprestimo",
        json={"numero_chamado": chamado, "devolucao_prevista": (date.today() + timedelta(days=dias)).isoformat()},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text


def _notificacoes(client, headers):
    return client.get("/api/v1/notificacoes", headers=headers).json()


class TestNotificacoesDeEmprestimo:
    def test_sem_pendencias_nao_notifica(self, client, auth_headers):
        r = _notificacoes(client, auth_headers)
        assert r["total"] == 0
        assert r["itens"] == []

    def test_avisa_no_dia_da_devolucao(self, client, auth_headers):
        """O pedido central: no dia, a pessoa é avisada para pegar o notebook."""
        _emprestar(client, auth_headers, _ativo(client, auth_headers, "NT-HOJE"), "CH-42", 0)

        r = _notificacoes(client, auth_headers)
        assert r["total"] == 1
        assert r["urgentes"] == 1
        item = r["itens"][0]
        assert item["tipo"] == "emprestimo_hoje"
        assert item["nivel"] == "urgente"
        assert item["titulo"] == "Devolução é HOJE"
        assert "NT-HOJE" in item["detalhe"]
        assert "CH-42" in item["detalhe"]
        assert item["dias"] == 0

    def test_avisa_devolucao_proxima(self, client, auth_headers):
        _emprestar(client, auth_headers, _ativo(client, auth_headers, "NT-3D"), "CH-3D", 3)

        itens = _notificacoes(client, auth_headers)["itens"]
        item = next(i for i in itens if "NT-3D" in i["detalhe"])
        assert item["tipo"] == "emprestimo_proximo"
        assert item["nivel"] == "info"
        assert item["dias"] == 3

    def test_nao_avisa_o_que_esta_longe(self, client, auth_headers):
        """Fora da janela de antecedência não polui o sino."""
        _emprestar(client, auth_headers, _ativo(client, auth_headers, "NT-LONGE"), "CH-L", 20)
        itens = _notificacoes(client, auth_headers)["itens"]
        assert all("NT-LONGE" not in i["detalhe"] for i in itens)

    def test_atrasado_aparece_primeiro(self, client, auth_headers, monkeypatch):
        """Atraso vem antes de tudo — é o mais crítico."""
        _emprestar(client, auth_headers, _ativo(client, auth_headers, "NT-ATR"), "CH-ATR", 0)
        _emprestar(client, auth_headers, _ativo(client, auth_headers, "NT-PROX"), "CH-P", 2)

        # "Avança o relógio" 5 dias: o que vencia hoje vira atraso de 5.
        import app.routers.notificacoes as notif

        class HojeFalso(date):
            @classmethod
            def today(cls):
                return date.today() + timedelta(days=5)

        monkeypatch.setattr(notif, "date", HojeFalso)

        itens = _notificacoes(client, auth_headers)["itens"]
        assert itens[0]["tipo"] == "emprestimo_atrasado"
        assert itens[0]["nivel"] == "erro"
        assert "atrasada há 5 dia" in itens[0]["titulo"]
        assert "NT-ATR" in itens[0]["detalhe"]

    def test_ordenacao_por_urgencia(self, client, auth_headers):
        _emprestar(client, auth_headers, _ativo(client, auth_headers, "ORD-PROX"), "CH-P", 2)
        _emprestar(client, auth_headers, _ativo(client, auth_headers, "ORD-HOJE"), "CH-H", 0)

        tipos = [i["tipo"] for i in _notificacoes(client, auth_headers)["itens"]]
        assert tipos == ["emprestimo_hoje", "emprestimo_proximo"]

    def test_devolvido_sai_da_notificacao(self, client, auth_headers):
        aid = _ativo(client, auth_headers, "NT-DEV")
        _emprestar(client, auth_headers, aid, "CH-D", 0)
        assert _notificacoes(client, auth_headers)["total"] == 1

        client.post(f"/api/v1/ativos/{aid}/devolucao", headers=auth_headers)
        assert _notificacoes(client, auth_headers)["total"] == 0

    def test_notificacao_traz_o_ativo_para_abrir(self, client, auth_headers):
        aid = _ativo(client, auth_headers, "NT-LINK")
        _emprestar(client, auth_headers, aid, "CH-L", 0)

        item = _notificacoes(client, auth_headers)["itens"][0]
        assert item["ativo_id"] == aid
        assert item["patrimonio"] == "NT-LINK"


class TestNotificacoesPorPlanta:
    def _planta(self, client, auth_headers, nome, sigla):
        return client.post(
            "/api/v1/admin/plantas", json={"nome": nome, "sigla": sigla}, headers=auth_headers
        ).json()["id"]

    def _leitor(self, client, auth_headers, email, planta_id):
        client.post(
            "/api/v1/usuarios",
            json={"nome": f"Leitor {email}", "email": email, "papel": "leitor",
                  "senha": "senha123", "planta_id": planta_id},
            headers=auth_headers,
        )
        login = client.post("/api/v1/auth/login", data={"username": email, "password": "senha123"})
        return {"Authorization": f"Bearer {login.json()['access_token']}"}

    def test_leitor_nao_ve_emprestimo_de_outra_planta(self, client, auth_headers):
        a = self._planta(client, auth_headers, "Campinas", "CPS")
        b = self._planta(client, auth_headers, "Recife", "REC")

        for pid, pat, ch in ((a, "NPS-A", "CH-A"), (b, "NPS-B", "CH-B")):
            h = {**auth_headers, "X-Planta-Id": str(pid)}
            ativo = _ativo(client, h, pat)
            _emprestar(client, h, ativo, ch, 0)

        h_leitor = self._leitor(client, auth_headers, "notif.a@teste.com", a)
        itens = _notificacoes(client, h_leitor)["itens"]
        detalhes = " ".join(i["detalhe"] for i in itens)

        assert "NPS-A" in detalhes
        assert "NPS-B" not in detalhes, "vazou notificação de outra planta"

    def test_admin_ve_de_todas_as_plantas(self, client, auth_headers):
        a = self._planta(client, auth_headers, "Campinas", "CPS")
        b = self._planta(client, auth_headers, "Recife", "REC")
        for pid, pat, ch in ((a, "NPA-A", "CH-A"), (b, "NPA-B", "CH-B")):
            h = {**auth_headers, "X-Planta-Id": str(pid)}
            _emprestar(client, h, _ativo(client, h, pat), ch, 0)

        detalhes = " ".join(i["detalhe"] for i in _notificacoes(client, auth_headers)["itens"])
        assert "NPA-A" in detalhes and "NPA-B" in detalhes

    def test_usuario_sem_planta_nao_quebra_o_sino(self, client, auth_headers):
        """Sem planta, lista vazia — o sino não pode virar erro vermelho."""
        client.post(
            "/api/v1/usuarios",
            json={"nome": "Sem Planta", "email": "semplanta.notif@teste.com", "papel": "leitor",
                  "senha": "senha123", "planta_id": None},
            headers=auth_headers,
        )
        login = client.post("/api/v1/auth/login", data={"username": "semplanta.notif@teste.com", "password": "senha123"})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}

        r = client.get("/api/v1/notificacoes", headers=h)
        assert r.status_code == 200
        assert r.json() == {"total": 0, "urgentes": 0, "itens": []}
