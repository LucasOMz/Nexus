"""Isolamento visto pelo USUARIO COMUM, nao pelo admin.

## O buraco que estes testes cobrem

Os testes anteriores usavam o admin com `X-Planta-Id` no header. Esse
caminho funciona. Mas um usuario comum **nao manda header** — o servidor usa
`user.planta_id` direto.

Se o usuario for criado sem planta, ou com a planta errada, ele ve tudo. E
era exatamente isso que nao estava sendo testado.
"""
from __future__ import annotations


def _planta(client, auth_headers, nome: str) -> int:
    r = client.post(
        "/api/v1/admin/plantas",
        headers=auth_headers,
        json={"nome": nome, "sigla": (nome[:2] + str(len(nome)))[:6].upper(), "ativa": True},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _usuario(client, auth_headers, email: str, planta_id: int | None) -> int:
    corpo = {"nome": email.split("@")[0], "email": email, "senha": "senha12345", "papel": "leitor"}
    if planta_id is not None:
        corpo["planta_id"] = planta_id
    r = client.post("/api/v1/usuarios", headers=auth_headers, json=corpo)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _login(client, email: str, senha: str = "senha12345") -> dict:
    r = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": senha},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class TestUsuarioComum:
    def test_usuario_ve_so_a_planta_dele(self, client, auth_headers):
        """O caso que o usuario reportou: trocou de planta e continuou vendo tudo."""
        a = _planta(client, auth_headers, "Um")
        b = _planta(client, auth_headers, "Dois")

        # Um cadastro em cada planta.
        client.post(
            "/api/v1/departamentos",
            headers={**auth_headers, "X-Planta-Id": str(a)},
            json={"nome": "So da Um"},
        )
        client.post(
            "/api/v1/departamentos",
            headers={**auth_headers, "X-Planta-Id": str(b)},
            json={"nome": "So da Dois"},
        )

        # Usuario preso na planta B.
        _usuario(client, auth_headers, "usuario_b@teste.com", b)
        headers_b = _login(client, "usuario_b@teste.com")

        r = client.get("/api/v1/departamentos", headers=headers_b)
        assert r.status_code == 200, r.text
        nomes = [x["nome"] for x in r.json()]

        assert "So da Dois" in nomes, nomes
        assert "So da Um" not in nomes, f"vazou cadastro de outra planta: {nomes}"

    def test_usuario_criado_sem_planta_ve_tudo(self, client, auth_headers):
        """Documenta o buraco: sem planta, o filtro nao existe.

        Nao e o comportamento desejado — e o que acontece hoje. Se este teste
        comecar a falhar porque o usuario sem planta passou a ser barrado,
        otimo: atualize-o.
        """
        a = _planta(client, auth_headers, "Tres")
        client.post(
            "/api/v1/departamentos",
            headers={**auth_headers, "X-Planta-Id": str(a)},
            json={"nome": "Da Tres"},
        )

        _usuario(client, auth_headers, "sem_planta@teste.com", None)
        headers = _login(client, "sem_planta@teste.com")

        nomes = [x["nome"] for x in client.get("/api/v1/departamentos", headers=headers).json()]
        assert "Da Tres" in nomes, "usuario sem planta deveria ver tudo"

    def test_legado_nao_aparece_para_o_usuario_comum(self, client, auth_headers):
        """Cadastro com planta nula NAO aparece para quem tem planta.

        E o caso reportado: trocar de conta e continuar vendo cadastro de
        outra planta. A causa era o nulo tratado como "de todos".
        """
        b = _planta(client, auth_headers, "Quatro")
        client.post("/api/v1/departamentos", headers=auth_headers, json={"nome": "Legado Comum"})

        _usuario(client, auth_headers, "comum@teste.com", b)
        headers = _login(client, "comum@teste.com")

        nomes = [x["nome"] for x in client.get("/api/v1/departamentos", headers=headers).json()]
        assert "Legado Comum" not in nomes
