"""Cadastros de apoio respeitam a planta.

## O que estes testes travam

* Um cadastro criado numa planta **não aparece** na outra.
* O **legado** (`planta_id` nulo) aparece nas duas — escondê-lo deixaria
  ativos e usuários apontando para um registro invisível.
* A **criação carimba** a planta de quem criou.
* `Departamento.nome` é único **por planta**: duas plantas podem ter
  "Financeiro" cada uma com o seu.
"""
from __future__ import annotations


def _planta(client, auth_headers, nome: str) -> int:
    r = client.post(
        "/api/v1/admin/plantas",
        headers=auth_headers,
        json={"nome": nome, "sigla": nome[:3].upper(), "ativa": True},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _criar_dep(client, auth_headers, nome: str, planta_id: int | None = None):
    headers = dict(auth_headers)
    if planta_id is not None:
        headers["X-Planta-Id"] = str(planta_id)
    return client.post(
        "/api/v1/departamentos",
        headers=headers,
        json={"nome": nome},
    )


def _listar(client, auth_headers, planta_id: int | None = None) -> list[str]:
    headers = dict(auth_headers)
    if planta_id is not None:
        headers["X-Planta-Id"] = str(planta_id)
    r = client.get("/api/v1/departamentos", headers=headers)
    assert r.status_code == 200, r.text
    return [x["nome"] for x in r.json()]


class TestCadastroPorPlanta:
    def test_criado_numa_planta_nao_aparece_na_outra(self, client, auth_headers):
        a = _planta(client, auth_headers, "Alfa")
        b = _planta(client, auth_headers, "Beta")

        r = _criar_dep(client, auth_headers, "Só da Alfa", a)
        assert r.status_code == 201, r.text
        assert r.json()["planta_id"] == a

        assert "Só da Alfa" in _listar(client, auth_headers, a)
        assert "Só da Alfa" not in _listar(client, auth_headers, b)

    def test_legado_aparece_nas_duas(self, client, auth_headers):
        """`planta_id` nulo é o cadastro anterior ao escopo — visível a todas."""
        a = _planta(client, auth_headers, "Gama")
        b = _planta(client, auth_headers, "Delta")

        # Sem planta no header, o admin grava nulo.
        r = client.post(
            "/api/v1/departamentos",
            headers=auth_headers,
            json={"nome": "Legado"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["planta_id"] is None

        assert "Legado" in _listar(client, auth_headers, a)
        assert "Legado" in _listar(client, auth_headers, b)

    def test_mesmo_nome_em_plantas_diferentes(self, client, auth_headers):
        """A unicidade é por planta, não global."""
        a = _planta(client, auth_headers, "Épsilon")
        b = _planta(client, auth_headers, "Zeta")

        assert _criar_dep(client, auth_headers, "Financeiro", a).status_code == 201
        assert _criar_dep(client, auth_headers, "Financeiro", b).status_code == 201

    def test_admin_sem_planta_ve_tudo(self, client, auth_headers):
        a = _planta(client, auth_headers, "Eta")
        _criar_dep(client, auth_headers, "Da Eta", a)

        # Sem header: visão consolidada.
        nomes = _listar(client, auth_headers, None)
        assert "Da Eta" in nomes
