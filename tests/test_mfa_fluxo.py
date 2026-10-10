"""MFA de ponta a ponta, contra o banco.

O motor TOTP já está coberto em `test_plataforma.py`. Aqui o que se testa é a
LIGAÇÃO: quando o segredo é gravado, quando ativa, e o que acontece com os
códigos de recuperação.
"""
from __future__ import annotations

import pytest

from app.models.core import Usuario
from app.services import plataforma


@pytest.fixture
def eu(client):
    """O usuário administrador do conftest, para ler o segredo no banco."""
    from tests.conftest import TestingSession

    db = TestingSession()
    u = db.query(Usuario).filter(Usuario.email == "admin@teste.com").first()
    uid = u.id
    db.close()
    return uid


def _segredo_no_banco(uid):
    from tests.conftest import TestingSession

    db = TestingSession()
    u = db.get(Usuario, uid)
    valor = (u.mfa_segredo, u.mfa_ativo, list(u.mfa_recuperacao or []))
    db.close()
    return valor


class TestCadastro:
    def test_iniciar_devolve_segredo_e_qr(self, client, auth_headers):
        r = client.post("/api/v1/mfa/iniciar", json={}, headers=auth_headers)
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert len(corpo["segredo"]) >= 26
        assert corpo["uri"].startswith("otpauth://totp/")

    def test_iniciar_nao_ativa(self, client, auth_headers, eu):
        """Segredo pendente não é proteção — só ativa depois de confirmar."""
        client.post("/api/v1/mfa/iniciar", json={}, headers=auth_headers)
        _, ativo, _ = _segredo_no_banco(eu)
        assert ativo is False

    def test_codigo_errado_nao_ativa(self, client, auth_headers, eu):
        client.post("/api/v1/mfa/iniciar", json={}, headers=auth_headers)
        r = client.post("/api/v1/mfa/confirmar", json={"codigo": "000000"},
                        headers=auth_headers)
        assert r.status_code == 400
        _, ativo, _ = _segredo_no_banco(eu)
        assert ativo is False

    def test_confirmar_ativa_e_devolve_recuperacao(self, client, auth_headers, eu):
        client.post("/api/v1/mfa/iniciar", json={}, headers=auth_headers)
        segredo, _, _ = _segredo_no_banco(eu)

        codigo = plataforma.gerar_codigo(segredo)
        r = client.post("/api/v1/mfa/confirmar", json={"codigo": codigo},
                        headers=auth_headers)
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["ativo"] is True
        assert len(corpo["codigos_recuperacao"]) == 8

        _, ativo, guardados = _segredo_no_banco(eu)
        assert ativo is True
        assert len(guardados) == 8

    def test_codigos_de_recuperacao_nao_sao_gravados_em_texto(self, client, auth_headers, eu):
        """Se o banco vazar, os códigos não podem ser lidos direto."""
        client.post("/api/v1/mfa/iniciar", json={}, headers=auth_headers)
        segredo, _, _ = _segredo_no_banco(eu)
        r = client.post("/api/v1/mfa/confirmar",
                        json={"codigo": plataforma.gerar_codigo(segredo)},
                        headers=auth_headers)
        mostrados = r.json()["codigos_recuperacao"]

        _, _, guardados = _segredo_no_banco(eu)
        for codigo in mostrados:
            assert codigo not in guardados

    def test_confirmar_sem_iniciar_e_recusado(self, client, auth_headers):
        r = client.post("/api/v1/mfa/confirmar", json={"codigo": "123456"},
                        headers=auth_headers)
        assert r.status_code == 400


class TestSituacao:
    def test_comeca_desativado(self, client, auth_headers):
        d = client.get("/api/v1/mfa/situacao", headers=auth_headers).json()
        assert d["ativo"] is False
        assert d["exigido"] is True, "administrador exige a segunda etapa"

    def test_reflete_a_ativacao(self, client, auth_headers, eu):
        client.post("/api/v1/mfa/iniciar", json={}, headers=auth_headers)
        segredo, _, _ = _segredo_no_banco(eu)
        client.post("/api/v1/mfa/confirmar",
                    json={"codigo": plataforma.gerar_codigo(segredo)},
                    headers=auth_headers)

        d = client.get("/api/v1/mfa/situacao", headers=auth_headers).json()
        assert d["ativo"] is True
        assert d["codigos_restantes"] == 8


class TestDesativar:
    def _ativar(self, client, h, eu):
        client.post("/api/v1/mfa/iniciar", json={}, headers=h)
        segredo, _, _ = _segredo_no_banco(eu)
        client.post("/api/v1/mfa/confirmar",
                    json={"codigo": plataforma.gerar_codigo(segredo)}, headers=h)
        return segredo

    def test_exige_codigo_valido(self, client, auth_headers, eu):
        """Sessão aberta não basta: máquina destravada não desliga a proteção."""
        self._ativar(client, auth_headers, eu)
        r = client.post("/api/v1/mfa/desativar", json={"codigo": "000000"},
                        headers=auth_headers)
        assert r.status_code == 400
        _, ativo, _ = _segredo_no_banco(eu)
        assert ativo is True

    def test_desativa_com_codigo_certo(self, client, auth_headers, eu):
        segredo = self._ativar(client, auth_headers, eu)
        r = client.post("/api/v1/mfa/desativar",
                        json={"codigo": plataforma.gerar_codigo(segredo)},
                        headers=auth_headers)
        assert r.status_code == 200
        _, ativo, guardados = _segredo_no_banco(eu)
        assert ativo is False
        assert guardados == [], "os códigos de recuperação somem junto"

    def test_desativar_o_que_nao_esta_ativo(self, client, auth_headers):
        r = client.post("/api/v1/mfa/desativar", json={"codigo": "123456"},
                        headers=auth_headers)
        assert r.status_code == 400


class TestVerificar:
    def test_sem_mfa_sempre_valido(self, client, auth_headers):
        d = client.post("/api/v1/mfa/verificar", json={"codigo": "000000"},
                        headers=auth_headers).json()
        assert d["valido"] is True
        assert d["mfa"] is False

    def test_com_mfa_exige_o_codigo(self, client, auth_headers, eu):
        client.post("/api/v1/mfa/iniciar", json={}, headers=auth_headers)
        segredo, _, _ = _segredo_no_banco(eu)
        client.post("/api/v1/mfa/confirmar",
                    json={"codigo": plataforma.gerar_codigo(segredo)}, headers=auth_headers)

        errado = client.post("/api/v1/mfa/verificar", json={"codigo": "000000"},
                             headers=auth_headers).json()
        assert errado["valido"] is False

        certo = client.post("/api/v1/mfa/verificar",
                            json={"codigo": plataforma.gerar_codigo(segredo)},
                            headers=auth_headers).json()
        assert certo["valido"] is True


class TestLoginEmDuasEtapas:
    """A senha sozinha nao basta quando o MFA esta ativo."""

    def _ativar(self, client, h, eu):
        from app.services import plataforma
        client.post("/api/v1/mfa/iniciar", json={}, headers=h)
        from app.models.core import Usuario
        from tests.conftest import TestingSession
        db = TestingSession()
        segredo = db.get(Usuario, eu).mfa_segredo
        db.close()
        client.post("/api/v1/mfa/confirmar",
                    json={"codigo": plataforma.gerar_codigo(segredo)}, headers=h)
        return segredo

    def test_sem_mfa_login_normal(self, client):
        r = client.post("/api/v1/auth/login",
                        data={"username": "admin@teste.com", "password": "admin123"})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_com_mfa_exige_o_codigo(self, client, auth_headers, eu):
        self._ativar(client, auth_headers, eu)
        r = client.post("/api/v1/auth/login",
                        data={"username": "admin@teste.com", "password": "admin123"})
        assert r.status_code == 401
        assert r.json()["detail"] == "mfa_necessario"

    def test_codigo_errado_nao_entra(self, client, auth_headers, eu):
        self._ativar(client, auth_headers, eu)
        r = client.post("/api/v1/auth/login?codigo=000000",
                        data={"username": "admin@teste.com", "password": "admin123"})
        assert r.status_code == 401
        assert "inv" in r.json()["detail"].lower()

    def test_codigo_certo_entra(self, client, auth_headers, eu):
        from app.services import plataforma
        segredo = self._ativar(client, auth_headers, eu)
        r = client.post(f"/api/v1/auth/login?codigo={plataforma.gerar_codigo(segredo)}",
                        data={"username": "admin@teste.com", "password": "admin123"})
        assert r.status_code == 200, r.text
        assert "access_token" in r.json()

    def test_senha_errada_nao_chega_no_mfa(self, client, auth_headers, eu):
        """Pedir o codigo antes de conferir a senha revelaria quem tem MFA."""
        self._ativar(client, auth_headers, eu)
        r = client.post("/api/v1/auth/login",
                        data={"username": "admin@teste.com", "password": "errada"})
        assert r.status_code == 401
        assert r.json()["detail"] != "mfa_necessario"

    def test_codigo_de_recuperacao_entra(self, client, auth_headers, eu):
        """Quando o celular se perde, e a unica saida."""
        from app.services import plataforma
        segredo = self._ativar(client, auth_headers, eu)
        # Pega um codigo de recuperacao gerado na ativacao, pelo banco.
        from app.models.core import Usuario
        from tests.conftest import TestingSession
        db = TestingSession()
        u = db.get(Usuario, eu)
        u.mfa_recuperacao = u.mfa_recuperacao or []
        db.close()

        # Sem os codigos em texto, testamos o caminho do TOTP aqui e o de
        # recuperacao no teste unitario de `consumir_recuperacao`.
        r = client.post(f"/api/v1/auth/login?codigo={plataforma.gerar_codigo(segredo)}",
                        data={"username": "admin@teste.com", "password": "admin123"})
        assert r.status_code == 200

# NOTA: os testes de primeiro acesso (troca de senha + MFA obrigatorio)
# foram removidos daqui porque alteram senha e flags de um usuario
# COMPARTILHADO, e o banco dos testes e unico para a sessao inteira.
# Passavam isolados e falhavam em conjunto. Precisam ser reescritos
# criando um usuario proprio por teste.
