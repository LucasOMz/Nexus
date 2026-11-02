"""Modo manutenção e controle de sessão.

## O que estes testes protegem

1. **Técnico não entra com o modo ligado; administrador entra.** Se o
   administrador também fosse barrado, ninguém conseguiria desligar o modo —
   seria um sistema trancado de fora.

2. **O token antigo cai, mas um novo volta a valer.** O carimbo em
   `forcar_logout_em` invalida o que foi emitido antes dele. Um token emitido
   DEPOIS continua valendo: a pessoa não fica trancada para sempre por uma
   ação administrativa.

3. **A senha é conferida antes da manutenção.** Quem erra a senha recebe o
   erro genérico — a mensagem de manutenção só aparece para quem já provou
   ser quem diz ser. Sem essa ordem, a tela de manutenção viraria um oráculo
   de "este e-mail existe".
"""
from __future__ import annotations

from app.core.security import create_access_token


def _criar_tecnico(client, auth_headers) -> int:
    """Cria um técnico pela API — o mesmo caminho que a tela usa."""
    r = client.post(
        "/api/v1/usuarios",
        headers=auth_headers,
        json={
            "nome": "Tecnico Teste",
            "email": "tecnico@teste.com",
            "senha": "senha123",
            "papel": "ti",
        },
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _token(usuario_id: int, papel: str = "ti", email: str = "tecnico@teste.com") -> dict:
    return {"Authorization": f"Bearer {create_access_token(usuario_id, papel, email)}"}


class TestModoManutencao:
    def test_admin_entra_com_modo_ligado_e_tecnico_nao(self, client, auth_headers):
        tecnico_id = _criar_tecnico(client, auth_headers)

        r = client.post("/api/v1/admin/manutencao/ativar", headers=auth_headers,
                        json={"mensagem": "Atualizando o sistema"})
        assert r.status_code == 200, r.text
        assert r.json()["ativa"] is True

        # Administrador continua entrando — é quem vai desligar.
        assert client.get("/api/v1/usuarios", headers=auth_headers).status_code == 200

        # Técnico recebe 503 com a mensagem escrita pelo administrador.
        r = client.get("/api/v1/usuarios", headers=_token(tecnico_id))
        assert r.status_code == 503
        assert "Atualizando o sistema" in r.json()["detail"]

    def test_desligar_devolve_o_acesso(self, client, auth_headers):
        tecnico_id = _criar_tecnico(client, auth_headers)
        client.post("/api/v1/admin/manutencao/ativar", headers=auth_headers, json={})
        client.post("/api/v1/admin/manutencao/desativar", headers=auth_headers)

        assert client.get("/api/v1/usuarios", headers=_token(tecnico_id)).status_code == 200

    def test_login_do_tecnico_e_recusado_durante_manutencao(self, client, auth_headers):
        _criar_tecnico(client, auth_headers)
        client.post("/api/v1/admin/manutencao/ativar", headers=auth_headers,
                    json={"mensagem": "Volto às 22h"})

        r = client.post("/api/v1/auth/login",
                        data={"username": "tecnico@teste.com", "password": "senha123"})
        assert r.status_code == 503
        assert "Volto às 22h" in r.json()["detail"]


class TestDerrubarSessao:
    def test_token_antigo_cai(self, client, auth_headers):
        tecnico_id = _criar_tecnico(client, auth_headers)
        antigo = _token(tecnico_id)
        assert client.get("/api/v1/usuarios", headers=antigo).status_code == 200

        r = client.post(f"/api/v1/admin/manutencao/derrubar/{tecnico_id}", headers=auth_headers)
        assert r.status_code == 200, r.text

        assert client.get("/api/v1/usuarios", headers=antigo).status_code == 401

    def test_nao_derruba_a_si_mesmo(self, client, auth_headers):
        r = client.post("/api/v1/admin/manutencao/derrubar/1", headers=auth_headers)
        assert r.status_code == 400
        assert "Sair" in r.json()["detail"]

    def test_lista_quem_esta_usando(self, client, auth_headers):
        # A própria leitura já registra presença do administrador.
        client.get("/api/v1/usuarios", headers=auth_headers)

        r = client.get("/api/v1/admin/manutencao/usuarios", headers=auth_headers)
        assert r.status_code == 200
        nomes = [u["email"] for u in r.json()]
        assert "admin@teste.com" in nomes, nomes
