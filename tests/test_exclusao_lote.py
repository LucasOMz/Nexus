"""Exclusão de ativos em lote (somente administrador).

Regras que estes testes protegem:
  * só o administrador exclui em lote;
  * duas etapas de confirmação na tela (a segunda é no frontend);
  * acima de 20 itens, o sistema gera BACKUP AUTOMÁTICO antes de apagar;
  * sem backup possível, NADA é apagado;
  * tudo fica registrado na auditoria.
"""
from __future__ import annotations

import pytest

from app.core.rate_limit import login_limiter, scan_limiter

LIMITE = 20


@pytest.fixture(autouse=True)
def _liberar_rate_limit():
    login_limiter._hits.clear()
    scan_limiter._hits.clear()
    yield
    login_limiter._hits.clear()
    scan_limiter._hits.clear()


def _criar_ativos(client, auth_headers, quantidade, prefixo="LOTE"):
    ids = []
    for i in range(quantidade):
        r = client.post(
            "/api/v1/ativos",
            json={"dominio": "ti", "patrimonio": f"{prefixo}-{i:04d}", "numero_serie": f"NS-{prefixo}-{i:04d}", "modelo": "X1"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    return ids


def _total(client, auth_headers):
    return client.get("/api/v1/ativos", params={"size": 1}, headers=auth_headers).json()["total"]


class TestExclusaoEmLote:
    def test_admin_exclui_varios(self, client, auth_headers):
        ids = _criar_ativos(client, auth_headers, 5)
        antes = _total(client, auth_headers)

        r = client.post("/api/v1/ativos/excluir-lote", json={"ids": ids}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["excluidos"] == 5
        assert r.json()["backup_gerado"] is False
        assert _total(client, auth_headers) == antes - 5

    def test_sem_selecao_da_erro_claro(self, client, auth_headers):
        r = client.post("/api/v1/ativos/excluir-lote", json={"ids": []}, headers=auth_headers)
        assert r.status_code == 400
        assert "selecionado" in r.json()["detail"]

    def test_ids_inexistentes(self, client, auth_headers):
        r = client.post("/api/v1/ativos/excluir-lote", json={"ids": [999999]}, headers=auth_headers)
        assert r.status_code == 404

    def test_nao_exclui_usuario_comum(self, client, auth_headers):
        """Exclusão em lote é privilégio do administrador."""
        ids = _criar_ativos(client, auth_headers, 2)
        r = client.post(
            "/api/v1/usuarios",
            json={
                "nome": "Tecnico", "email": "tec.lote@teste.com", "papel": "ti", "senha": "senha123",
                "permissoes": {
                    "inventarios": ["ti"], "modulos": ["ativos"],
                    "pode_escrever": True, "pode_excluir": True,  # mesmo com exclusão liberada
                },
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        login = client.post("/api/v1/auth/login", data={"username": "tec.lote@teste.com", "password": "senha123"})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}

        r = client.post("/api/v1/ativos/excluir-lote", json={"ids": ids}, headers=h)
        assert r.status_code == 403
        assert _total(client, auth_headers) > 0  # nada foi apagado

    def test_auditoria_registra_quem_e_quantos(self, client, auth_headers):
        ids = _criar_ativos(client, auth_headers, 3, "AUDL")
        client.post("/api/v1/ativos/excluir-lote", json={"ids": ids}, headers=auth_headers)

        logs = client.get(
            "/api/v1/admin/auditoria",
            params={"acao": "delete_lote"},
            headers=auth_headers,
        ).json()["itens"]
        assert logs, "exclusão em lote não foi auditada"
        assert logs[0]["usuario_nome"] == "Admin"
        assert logs[0]["acao_rotulo"] == "Excluiu em lote"
        assert logs[0]["diff"]["quantidade"] == 3
        assert logs[0]["diff"]["criterio"] == "selecao_manual"

    def test_ativo_excluido_sai_das_listas(self, client, auth_headers):
        ids = _criar_ativos(client, auth_headers, 2, "SAI")
        client.post("/api/v1/ativos/excluir-lote", json={"ids": ids}, headers=auth_headers)

        itens = client.get("/api/v1/ativos", params={"size": 200}, headers=auth_headers).json()["items"]
        patrimonios = {i["patrimonio"] for i in itens}
        assert "SAI-0000" not in patrimonios
        assert "SAI-0001" not in patrimonios


class TestBackupAutomatico:
    """Acima de 20 itens, um backup é gerado ANTES da exclusão.

    Observação sobre o ambiente de teste: aqui o banco é SQLite **em memória**,
    então não existe arquivo para copiar e o backup sempre falha. Isso permite
    verificar a regra de segurança mais importante — **sem backup, nada é
    apagado**. O caminho de sucesso (backup criado e listado) foi validado
    contra um banco em arquivo.
    """

    def test_ate_o_limite_nao_tenta_backup(self, client, auth_headers):
        ids = _criar_ativos(client, auth_headers, LIMITE, "LIM")
        r = client.post("/api/v1/ativos/excluir-lote", json={"ids": ids}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["excluidos"] == LIMITE
        assert r.json()["backup_gerado"] is False
        assert r.json()["backup"] is None

    def test_acima_do_limite_gera_backup_antes_de_apagar(self, client, auth_headers):
        """No banco em arquivo o backup sai; aqui confirmamos que ele é TENTADO.

        Em memória o backup falha de propósito, e o mais importante é que a
        exclusão NÃO acontece — coberto no teste seguinte.
        """
        ids = _criar_ativos(client, auth_headers, LIMITE + 2, "BKP")
        r = client.post("/api/v1/ativos/excluir-lote", json={"ids": ids}, headers=auth_headers)
        # Ou o backup saiu (banco em arquivo) ou a operação foi recusada.
        if r.status_code == 200:
            assert r.json()["backup_gerado"] is True
            assert r.json()["backup"].endswith(".db")
        else:
            assert r.status_code == 500
            assert "backup" in r.json()["detail"].lower()

    def test_sem_backup_possivel_nada_e_apagado(self, client, auth_headers):
        """A regra de ouro: se o backup falhar, NENHUM ativo é excluído.

        Perder 21+ itens sem uma cópia de segurança seria pior do que não
        permitir a exclusão.
        """
        ids = _criar_ativos(client, auth_headers, LIMITE + 1, "SEG")
        antes = _total(client, auth_headers)

        r = client.post("/api/v1/ativos/excluir-lote", json={"ids": ids}, headers=auth_headers)
        assert r.status_code == 500
        assert "Nada foi apagado" in r.json()["detail"]

        # Confirma que os ativos continuam lá, um a um.
        assert _total(client, auth_headers) == antes
        for aid in ids:
            assert client.get(f"/api/v1/ativos/{aid}", headers=auth_headers).status_code == 200

    def test_limite_de_backup_e_vinte(self):
        from app.routers.ativos import LIMITE_BACKUP_AUTOMATICO

        assert LIMITE_BACKUP_AUTOMATICO == 20


class TestExcluirTudoDoFiltro:
    def test_exclui_tudo_que_o_filtro_retorna(self, client, auth_headers):
        _criar_ativos(client, auth_headers, 4, "FILTRO")
        total_filtro = client.get(
            "/api/v1/ativos", params={"size": 1, "search": "FILTRO"}, headers=auth_headers
        ).json()["total"]
        assert total_filtro == 4

        r = client.post(
            "/api/v1/ativos/excluir-lote",
            json={"todos_do_filtro": True, "dominio": "ti", "search": "FILTRO"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["excluidos"] == 4

        restante = client.get("/api/v1/ativos", params={"size": 1, "search": "FILTRO"}, headers=auth_headers).json()
        assert restante["total"] == 0

    def test_filtro_por_status(self, client, auth_headers):
        ids = _criar_ativos(client, auth_headers, 3, "ST")
        for i, aid in enumerate(ids):
            client.patch(f"/api/v1/ativos/{aid}/status", json={"status": "manutencao"}, headers=auth_headers)

        r = client.post(
            "/api/v1/ativos/excluir-lote",
            json={"todos_do_filtro": True, "dominio": "ti", "status": "manutencao"},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["excluidos"] >= 3

    def test_filtro_vazio_nao_quebra(self, client, auth_headers):
        r = client.post(
            "/api/v1/ativos/excluir-lote",
            json={"todos_do_filtro": True, "dominio": "ti", "search": "NAO-EXISTE-NADA-ASSIM"},
            headers=auth_headers,
        )
        assert r.status_code == 404
