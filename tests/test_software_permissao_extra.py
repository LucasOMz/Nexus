"""Fase 1 (#14) — a permissão de revelar precisa de fluxo administrativo.

## O que estava partido

O backend consultava `permissoes_extra` para decidir quem pode revelar a
chave de licença — e **nada escrevia esse campo**:

- o schema `Permissoes` tinha `extra="forbid"` e só aceitava inventários,
  módulos, escrita e exclusão;
- enviar `permissoes_extra` pela API dava **422**.

Na prática: **só administrador revelava chave.** Seguro por padrão, mas a
permissão era inalcançável — uma trava que ninguém tinha a chave.

E o botão na tela aparecia para todos, falhando com 403 só depois do clique.
"""
from __future__ import annotations

import pytest

from app.core import segredos

CHAVE = "ZZZZ-1234-YYYY-5678"


@pytest.fixture(autouse=True)
def _com_chave_mestra(monkeypatch):
    monkeypatch.setenv(segredos.VARIAVEL, "chave-mestra-de-teste")
    yield


class TestSchemaAceita:
    def test_o_campo_existe(self):
        """Sem ele, `extra="forbid"` recusava o envio com 422."""
        from app.schemas.common import Permissoes

        assert "permissoes_extra" in Permissoes.model_fields

    def test_aceita_a_permissao(self):
        from app.schemas.common import Permissoes

        p = Permissoes(permissoes_extra=["licencas.ver_chave"])
        assert p.permissoes_extra == ["licencas.ver_chave"]

    def test_o_padrao_e_vazio(self):
        """Ninguém ganha a permissão por omissão."""
        from app.schemas.common import Permissoes

        assert Permissoes().permissoes_extra == []


class TestPermissoesEfetivas:
    def test_repassa_o_campo(self):
        """Sem isto, o valor gravado ficaria invisível para quem consulta
        `permissoes_efetivas` — e a permissão não teria efeito."""
        from app.core.permissoes import permissoes_efetivas

        class U:
            papel = "ti"
            permissoes = {"permissoes_extra": ["licencas.ver_chave"]}

        assert permissoes_efetivas(U())["permissoes_extra"] == ["licencas.ver_chave"]

    def test_sem_customizacao_e_vazio(self):
        from app.core.permissoes import permissoes_efetivas

        class U:
            papel = "ti"
            permissoes = None

        assert permissoes_efetivas(U())["permissoes_extra"] == []

    def test_o_papel_nao_concede_por_padrao(self):
        """Nem o perfil TI ganha revelar chave sem pedir."""
        from app.core.permissoes import permissoes_efetivas

        class U:
            papel = "ti"
            permissoes = {}

        assert permissoes_efetivas(U())["permissoes_extra"] == []


class TestFluxoCompleto:
    def _usuario(self, client, permissoes=None, papel="ti"):
        from app.core.security import create_access_token, hash_password
        from app.database import get_db
        from app.main import app
        from app.models.core import Planta, Usuario

        db = next(app.dependency_overrides[get_db]())
        planta = db.query(Planta).first()
        u = Usuario(nome="Operador", email=f"perm{id(permissoes)}@teste.com",
                    senha_hash=hash_password("senha123"), papel=papel, ativo=True,
                    planta_id=planta.id if planta else None,
                    permissoes=permissoes)
        db.add(u)
        db.commit()
        db.refresh(u)
        return {"Authorization": f"Bearer {create_access_token(u.id, u.papel.value, u.email)}"}

    def _licenca(self, client, auth_headers):
        sw = client.post("/api/v1/softwares", json={"nome": "Office"},
                         headers=auth_headers).json()
        return client.post("/api/v1/licencas",
                           json={"software_id": sw["id"], "tipo": "volume", "metrica": "dispositivo",
                                 "seats": 5, "chave": CHAVE},
                           headers=auth_headers).json()

    def test_admin_revela(self, client, auth_headers):
        lic = self._licenca(client, auth_headers)
        r = client.get(f"/api/v1/licencas/{lic['id']}/revelar", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["chave"] == CHAVE

    def test_sem_permissao_da_403(self, client, auth_headers):
        lic = self._licenca(client, auth_headers)
        h = self._usuario(client)
        r = client.get(f"/api/v1/licencas/{lic['id']}/revelar", headers=h)
        assert r.status_code == 403, "revelou sem ter a permissão"
        assert "ZZZZ" not in r.text

    def test_com_permissao_revela(self, client, auth_headers):
        """O caminho que antes era impossível: o administrador concede, e a
        pessoa passa a poder."""
        lic = self._licenca(client, auth_headers)
        h = self._usuario(client, {"permissoes_extra": ["licencas.ver_chave"]})

        r = client.get(f"/api/v1/licencas/{lic['id']}/revelar", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["chave"] == CHAVE

    def test_a_mensagem_diz_onde_pedir(self, client, auth_headers):
        """"Sem permissão" sem dizer onde conseguir é um beco sem saída."""
        lic = self._licenca(client, auth_headers)
        h = self._usuario(client)
        r = client.get(f"/api/v1/licencas/{lic['id']}/revelar", headers=h)
        assert "Administração" in r.text or "administrador" in r.text.lower()

    def test_a_concessao_chega_no_me(self, client, auth_headers):
        """A tela precisa saber — é o que permite esconder o botão."""
        h = self._usuario(client, {"permissoes_extra": ["licencas.ver_chave"]})
        d = client.get("/api/v1/auth/me", headers=h).json()
        efetivas = d.get("permissoes_efetivas") or {}
        assert "licencas.ver_chave" in (efetivas.get("permissoes_extra") or [])
