"""Troca de senha de usuário local pelo painel do administrador.

## O bug que estes testes cobrem

O administrador editava um usuário, digitava a nova senha, a tela dizia
"Usuário salvo" — e a senha **nunca chegava ao servidor**. O campo era lido
no formulário e só anexado ao corpo no **cadastro novo**; no `PUT`, o
payload ia sem ele.

Quem tentasse entrar recebia "senha incorreta", sem nada estar quebrado no
servidor: o hash antigo simplesmente continuava lá.

## O que fica travado

* `PUT /usuarios/{id}` com `senha` **grava** — e o login seguinte funciona.
* `PUT` sem `senha` **preserva** a atual — editar o nome não derruba ninguém.
* Senha curta é recusada, em vez de virar um hash de algo inválido.
"""
from __future__ import annotations


def _criar(client, auth_headers, email: str, senha: str) -> int:
    r = client.post(
        "/api/v1/usuarios",
        headers=auth_headers,
        json={"nome": "Teste", "email": email, "senha": senha, "papel": "leitor"},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _login(client, email: str, senha: str):
    """O login é OAuth2: form data, não JSON.

    `username` leva o e-mail; o endpoint devolve 422 se vier JSON.
    """
    return client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": senha},
    )


class TestTrocaDeSenha:
    def test_troca_pelo_adm_permite_entrar_com_a_nova(self, client, auth_headers):
        """O caminho que estava quebrado: PUT com `senha` e depois login."""
        usuario_id = _criar(client, auth_headers, "senha1@teste.com", "antiga123")

        assert _login(client, "senha1@teste.com", "antiga123").status_code == 200

        r = client.put(
            f"/api/v1/usuarios/{usuario_id}",
            headers=auth_headers,
            json={"nome": "Teste", "senha": "nova4567"},
        )
        assert r.status_code == 200, r.text

        assert _login(client, "senha1@teste.com", "nova4567").status_code == 200
        assert _login(client, "senha1@teste.com", "antiga123").status_code == 401

    def test_editar_sem_senha_preserva_a_atual(self, client, auth_headers):
        """Mudar só o nome não pode derrubar o acesso de ninguém."""
        usuario_id = _criar(client, auth_headers, "senha2@teste.com", "mantida123")

        r = client.put(
            f"/api/v1/usuarios/{usuario_id}",
            headers=auth_headers,
            json={"nome": "Outro Nome"},
        )
        assert r.status_code == 200, r.text

        assert _login(client, "senha2@teste.com", "mantida123").status_code == 200

    def test_senha_curta_e_recusada(self, client, auth_headers):
        """`min_length=6` barra antes de gerar um hash inválido."""
        usuario_id = _criar(client, auth_headers, "senha3@teste.com", "valida123")

        r = client.put(
            f"/api/v1/usuarios/{usuario_id}",
            headers=auth_headers,
            json={"nome": "Teste", "senha": "123"},
        )
        assert r.status_code == 422, r.text

        # A senha antiga continua valendo.
        assert _login(client, "senha3@teste.com", "valida123").status_code == 200
