"""Fase 1 — autorização e isolamento entre plantas no módulo de software.

## Os dois furos que estes testes fecham

**1. Exclusão com permissão de escrita.** As rotas de `DELETE` usavam
`require_write`. Como o perfil TI padrão **escreve mas não exclui**, ele
conseguia apagar software, licença e atribuição.

**2. Escopo de planta só nas listas.** Detalhe, edição, exclusão e revelação
buscavam por id sem conferir a planta. Um usuário de uma unidade podia
**revelar a chave de licença de outra** — e a revelação ficava auditada, mas
sob o usuário errado.

O segundo é o mais grave: a auditoria registraria a pessoa certa lendo um
segredo que ela não deveria alcançar.
"""
from __future__ import annotations

import pytest

from app.core import segredos

CHAVE = "AAAA-1111-BBBB-2222"


@pytest.fixture(autouse=True)
def _com_chave_mestra(monkeypatch):
    monkeypatch.setenv(segredos.VARIAVEL, "chave-mestra-de-teste")
    yield


@pytest.fixture
def duas_plantas(client, auth_headers):
    """Duas plantas com um software e uma licença em cada."""
    from app.database import get_db
    from app.main import app
    from app.models.core import Planta

    db = next(app.dependency_overrides[get_db]())
    a = Planta(nome="Unidade A", sigla="UA")
    b = Planta(nome="Unidade B", sigla="UB")
    db.add_all([a, b])
    db.commit()
    db.refresh(a)
    db.refresh(b)

    feitos = {}
    for planta, sigla in ((a, "A"), (b, "B")):
        sw = client.post("/api/v1/softwares",
                         json={"nome": f"Software {sigla}", "planta_id": planta.id},
                         headers=auth_headers).json()
        lic = client.post("/api/v1/licencas",
                          json={"software_id": sw["id"], "tipo": "volume", "seats": 5,
                                "chave": f"{CHAVE[:-1]}{sigla}", "planta_id": planta.id},
                          headers=auth_headers).json()
        feitos[sigla] = {"planta": planta.id, "software": sw, "licenca": lic}
    return feitos


def _usuario_da_planta(client, auth_headers, planta_id, papel="ti"):
    """Cria um usuário comum preso a uma planta e devolve os headers dele."""
    from app.core.security import create_access_token, hash_password
    from app.database import get_db
    from app.main import app
    from app.models.core import Usuario

    db = next(app.dependency_overrides[get_db]())
    u = Usuario(nome=f"User {planta_id}", email=f"u{planta_id}@teste.com",
                senha_hash=hash_password("senha123"), papel=papel,
                ativo=True, planta_id=planta_id)
    db.add(u)
    db.commit()
    db.refresh(u)

    tok = create_access_token(u.id, u.papel.value, u.email)
    return {"Authorization": f"Bearer {tok}"}, u


class TestExclusaoExigePermissaoDeExclusao:
    """#3 do parecer."""

    def _rotas(self):
        from app.routers.software import router

        return {
            r.path: [d.dependency for d in r.dependencies] if r.dependencies else []
            for r in router.routes if "DELETE" in getattr(r, "methods", set())
        }

    def test_as_rotas_de_delete_nao_usam_require_write(self):
        from app.core.deps import require_delete, require_write

        for caminho, deps in self._rotas().items():
            assert require_write not in deps, (
                f"{caminho} usa require_write — o perfil TI padrão escreve, "
                "mas não exclui, e passaria por aqui"
            )
            assert require_delete in deps, f"{caminho} não exige require_delete"

    def test_sao_tres_rotas_de_exclusao(self):
        assert len(self._rotas()) == 3


class TestEscopoDePlanta:
    """#4 do parecer."""

    def test_o_detalhe_de_outra_planta_da_404(self, client, auth_headers, duas_plantas):
        headers_a, _ = _usuario_da_planta(client, auth_headers, duas_plantas["A"]["planta"])
        alvo = duas_plantas["B"]["software"]["id"]

        r = client.get(f"/api/v1/softwares/{alvo}", headers=headers_a)
        assert r.status_code == 404, "viu o software de outra unidade"

    def test_a_edicao_de_outra_planta_da_404(self, client, auth_headers, duas_plantas):
        headers_a, _ = _usuario_da_planta(client, auth_headers, duas_plantas["A"]["planta"])
        alvo = duas_plantas["B"]["software"]["id"]

        r = client.put(f"/api/v1/softwares/{alvo}",
                       json={"nome": "Invadido"}, headers=headers_a)
        assert r.status_code == 404

    def test_a_exclusao_de_outra_planta_nao_acontece(self, client, auth_headers, duas_plantas):
        """Duas camadas podem barrar, e a propriedade é a mesma: não apaga.

        O perfil `ti` tem `pode_excluir: False`, então o `require_delete`
        responde **403 antes** de o escopo de planta ser consultado. Com um
        usuário que pode excluir, quem barraria seria o `_no_escopo`, com 404.

        O teste verifica o que importa — **o registro continua existindo** —
        em vez de fixar qual camada respondeu primeiro.
        """
        headers_a, _ = _usuario_da_planta(client, auth_headers, duas_plantas["A"]["planta"])
        alvo = duas_plantas["B"]["software"]["id"]

        r = client.delete(f"/api/v1/softwares/{alvo}", headers=headers_a)
        assert r.status_code != 204, "apagou software de outra unidade"

        # E o registro tem que estar lá, visto pelo administrador.
        assert client.get(f"/api/v1/softwares/{alvo}", headers=auth_headers).status_code == 200

    def test_revelar_a_chave_de_outra_planta_nao_acontece(self, client, auth_headers, duas_plantas):
        """O furo mais grave: a auditoria registraria a pessoa certa lendo um
        segredo que ela não deveria alcançar."""
        headers_a, _ = _usuario_da_planta(client, auth_headers, duas_plantas["A"]["planta"])
        alvo = duas_plantas["B"]["licenca"]["id"]

        r = client.get(f"/api/v1/licencas/{alvo}/revelar", headers=headers_a)
        assert r.status_code != 200, "revelou a chave de outra unidade"
        # O que não pode, em hipótese alguma, é a chave aparecer.
        assert "AAAA" not in r.text
        assert "1111" not in r.text

    def test_a_propria_planta_funciona(self, client, auth_headers, duas_plantas):
        """O escopo não pode bloquear o acesso legítimo."""
        headers_a, _ = _usuario_da_planta(client, auth_headers, duas_plantas["A"]["planta"])

        r = client.get(f"/api/v1/softwares/{duas_plantas['A']['software']['id']}",
                       headers=headers_a)
        # 200 (achou) ou 403 (sem o módulo) — nunca 404, que diria "não existe".
        assert r.status_code != 404, "não achou o próprio software"

    def test_404_e_nao_403(self, client, auth_headers, duas_plantas):
        """Um 403 confirmaria que o registro existe — já é informação sobre
        outra unidade."""
        headers_a, _ = _usuario_da_planta(client, auth_headers, duas_plantas["A"]["planta"])
        alvo = duas_plantas["B"]["software"]["id"]
        r = client.get(f"/api/v1/softwares/{alvo}", headers=headers_a)
        assert r.status_code != 403

    def test_administrador_ve_tudo(self, client, auth_headers, duas_plantas):
        for sigla in ("A", "B"):
            r = client.get(f"/api/v1/softwares/{duas_plantas[sigla]['software']['id']}",
                           headers=auth_headers)
            assert r.status_code == 200, f"admin não viu a planta {sigla}"


class TestLicencaCorporativa:
    """`planta_id` nulo significa **corporativo**, e precisa valer em toda parte.

    Escondendo a licença corporativa de quem filtra por planta, o gestor de
    uma unidade não veria o que a empresa já comprou — e compraria de novo.
    """

    def test_licenca_corporativa_aparece_em_toda_planta(self, client, auth_headers, duas_plantas):
        sw = client.post("/api/v1/softwares",
                         json={"nome": "Volume Corporativo"}, headers=auth_headers).json()
        lic = client.post("/api/v1/licencas",
                          json={"software_id": sw["id"], "tipo": "volume", "seats": 100,
                                "chave": "CORP-9999-8888-7777"},
                          headers=auth_headers).json()
        assert lic["planta_id"] is None, "deveria ser corporativa"

        headers_a, _ = _usuario_da_planta(client, auth_headers, duas_plantas["A"]["planta"])
        r = client.get(f"/api/v1/licencas/{lic['id']}", headers=headers_a)
        assert r.status_code != 404, "a licença corporativa sumiu para a unidade"


class TestPlantaDoCorpo:
    """O `planta_id` do corpo era gravado sem validação."""

    def test_usuario_comum_nao_cria_em_outra_planta(self, client, auth_headers, duas_plantas):
        headers_a, _ = _usuario_da_planta(client, auth_headers, duas_plantas["A"]["planta"])
        alvo = duas_plantas["B"]["planta"]

        r = client.post("/api/v1/softwares",
                        json={"nome": "Invasor", "planta_id": alvo}, headers=headers_a)
        # Ou recusa, ou grava na planta DELE — nunca na alheia.
        if r.status_code == 201:
            assert r.json()["planta_id"] != alvo, (
                "criou um registro na planta de outra unidade"
            )
