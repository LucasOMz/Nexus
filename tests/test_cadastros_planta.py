"""Cadastros de apoio respeitam a planta.

## O que estes testes travam

* Um cadastro criado numa planta **nao aparece** na outra.
* O **legado** (`planta_id` nulo) aparece nas duas — esconde-lo deixaria
  ativos e usuarios apontando para um registro invisivel.
* A **criacao carimba** a planta de quem criou.
* `Departamento.nome` e unico **por planta**: duas plantas podem ter
  "Financeiro" cada uma com o seu.
* O **legado pode ser atribuido** a uma planta, uma vez, por decisao do
  administrador.
"""
from __future__ import annotations


def _sigla(nome: str) -> str:
    """Sigla unica por nome.

    Os testes criam varias plantas; usar os 3 primeiros caracteres fazia
    "Legado A" e "Legado B" colidirem em "LEG".
    """
    letras = [p[0] for p in nome.split() if p]
    return ("".join(letras) + str(len(nome)))[:6].upper()


def _planta(client, auth_headers, nome: str) -> int:
    r = client.post(
        "/api/v1/admin/plantas",
        headers=auth_headers,
        json={"nome": nome, "sigla": _sigla(nome), "ativa": True},
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

        r = _criar_dep(client, auth_headers, "So da Alfa", a)
        assert r.status_code == 201, r.text
        assert r.json()["planta_id"] == a

        assert "So da Alfa" in _listar(client, auth_headers, a)
        assert "So da Alfa" not in _listar(client, auth_headers, b)

    def test_legado_aparece_nas_duas(self, client, auth_headers):
        """`planta_id` nulo e o cadastro anterior ao escopo — visivel a todas."""
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
        """A unicidade e por planta, nao global."""
        a = _planta(client, auth_headers, "Epsilon")
        b = _planta(client, auth_headers, "Zeta")

        assert _criar_dep(client, auth_headers, "Financeiro", a).status_code == 201
        assert _criar_dep(client, auth_headers, "Financeiro", b).status_code == 201

    def test_admin_sem_planta_ve_tudo(self, client, auth_headers):
        a = _planta(client, auth_headers, "Eta")
        _criar_dep(client, auth_headers, "Da Eta", a)

        # Sem header: visao consolidada.
        nomes = _listar(client, auth_headers, None)
        assert "Da Eta" in nomes


class TestLegado:
    """Atribuir os cadastros que ficaram sem planta.

    A migracao deixou `planta_id` nulo nos registros antigos, e nulo significa
    "visivel a todas" — por isso um sistema com 60 departamentos continuou
    mostrando tudo em todas as plantas.

    Nao ha resposta automatica para "de qual planta e este departamento?": o
    administrador decide, e esta rota e o instrumento.
    """

    def test_conta_os_sem_planta(self, client, auth_headers):
        client.post(
            "/api/v1/departamentos", headers=auth_headers, json={"nome": "Sem dono"}
        )

        r = client.get("/api/v1/cadastros/legado", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["departamentos"] >= 1

    def test_atribuir_move_os_nulos(self, client, auth_headers):
        a = _planta(client, auth_headers, "Legado A")
        client.post(
            "/api/v1/departamentos", headers=auth_headers, json={"nome": "Orfao"}
        )

        r = client.post(
            "/api/v1/cadastros/atribuir-legado",
            headers=auth_headers,
            params={"planta_id": a},
        )
        assert r.status_code == 200, r.text
        assert r.json()["movidos"]["departamentos"] >= 1

        # Agora aparece so na planta A.
        assert "Orfao" in _listar(client, auth_headers, a)

        b = _planta(client, auth_headers, "Legado B")
        assert "Orfao" not in _listar(client, auth_headers, b)

    def test_rodar_duas_vezes_nao_move_de_novo(self, client, auth_headers):
        """So os nulos sao tocados — ja atribuido nunca se mexe."""
        a = _planta(client, auth_headers, "Idem A")
        client.post(
            "/api/v1/departamentos", headers=auth_headers, json={"nome": "Uma vez"}
        )

        r1 = client.post(
            "/api/v1/cadastros/atribuir-legado",
            headers=auth_headers,
            params={"planta_id": a},
        )
        assert r1.status_code == 200
        primeiro = r1.json()["movidos"]["departamentos"]

        r2 = client.post(
            "/api/v1/cadastros/atribuir-legado",
            headers=auth_headers,
            params={"planta_id": a},
        )
        assert r2.json()["movidos"]["departamentos"] == 0
        assert primeiro >= 1
