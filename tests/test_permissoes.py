"""Testes do sistema de permissões e do acesso restrito por módulo."""
from __future__ import annotations


def _criar_usuario(client, auth_headers, **perm):
    payload = {
        "nome": "Operador",
        "email": "operador@teste.com",
        "papel": "leitor",
        "senha": "senha123",
        "permissoes": {
            "inventarios": ["ti"],
            "modulos": ["ativos", "relatorios"],
            "pode_escrever": False,
            "pode_excluir": False,
            **perm,
        },
    }
    res = client.post("/api/v1/usuarios", json=payload, headers=auth_headers)
    assert res.status_code == 201, res.text
    return res.json()


def _token_do_usuario(client, email="operador@teste.com", senha="senha123"):
    res = client.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_permissoes_efetivas_do_usuario(client, auth_headers):
    u = _criar_usuario(client, auth_headers)
    p = u["permissoes_efetivas"]
    assert p["modulos"] == ["ativos", "relatorios"]
    assert p["inventarios"] == ["ti"]
    assert p["pode_escrever"] is False


def test_usuario_bloqueado_em_modulo_sem_permissao(client, auth_headers):
    _criar_usuario(client, auth_headers)
    h = _token_do_usuario(client)

    # Permitido: módulos liberados.
    assert client.get("/api/v1/ativos", params={"dominio": "ti"}, headers=h).status_code == 200
    assert client.get("/api/v1/dashboard/stats", params={"dominio": "ti"}, headers=h).status_code == 200

    # Bloqueado: módulos não liberados.
    assert client.get("/api/v1/produtos", params={"dominio": "ti"}, headers=h).status_code == 403
    assert client.get("/api/v1/manutencoes", headers=h).status_code == 403
    assert client.get("/api/v1/admin/metadados", headers=h).status_code == 403


def test_usuario_sem_escrita_nao_cria_ativo(client, auth_headers):
    _criar_usuario(client, auth_headers)
    h = _token_do_usuario(client)
    res = client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": "X-1"}, headers=h)
    assert res.status_code == 403


def test_admin_tem_acesso_total(client, auth_headers):
    assert client.get("/api/v1/produtos", params={"dominio": "ti"}, headers=auth_headers).status_code == 200
    assert client.get("/api/v1/relatorios/inventario", params={"dominio": "ti"}, headers=auth_headers).status_code == 200
    assert client.get("/api/v1/admin/metadados", headers=auth_headers).status_code == 200
