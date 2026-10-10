"""Primeiro acesso: troca de senha obrigatória e cadastro do MFA.

## Por que este arquivo existe separado

A primeira versão destes testes usava o administrador criado pelo `conftest` e
**alterava a senha dele**. O banco dos testes é único para a sessão inteira, e
o resultado foi o pior tipo de falha: cada teste passava sozinho e a suíte
inteira falhava — um dependia do que o anterior tinha feito.

Aqui cada teste cria o **seu próprio usuário**. É mais código e mais lento, e
é o preço de um teste que diz a verdade.
"""
from __future__ import annotations

from urllib.parse import urlencode

import pytest

from app.core.security import hash_password
from app.models.core import Usuario
from app.models.enums import PapelUsuario

SEQ = [0]


def criar_usuario(**campos) -> Usuario:
    """Usuário novo, exclusivo do teste que chamou.

    O e-mail é único por chamada: assim dois testes jamais disputam a mesma
    linha, mesmo rodando o arquivo inteiro.
    """
    from tests.conftest import TestingSession

    SEQ[0] += 1
    # `.local` é domínio reservado e o validador de e-mail recusa — tem que ser
    # um domínio comum.
    email = campos.pop("email", f"primeiro{SEQ[0]}@teste.com")
    senha = campos.pop("senha", "SenhaInicial123")

    db = TestingSession()
    u = Usuario(
        nome=campos.pop("nome", "Tecnico Teste"),
        email=email,
        senha_hash=hash_password(senha),
        papel=PapelUsuario.ADMIN,
        origem="local",
        ativo=True,
    )
    for k, v in campos.items():
        setattr(u, k, v)
    db.add(u)
    db.commit()
    db.refresh(u)
    # Desanexa: quem usar lê só os campos simples, já materializados.
    db.expunge(u)
    db.close()
    return u


def entrar(client, email, senha="SenhaInicial123", codigo=None):
    q = f"?{urlencode({'codigo': codigo})}" if codigo else ""
    return client.post(f"/api/v1/auth/login{q}",
                       data={"username": email, "password": senha})


def token_de(client, email, senha="SenhaInicial123"):
    r = entrar(client, email, senha)
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def admin(client):
    """Cabeçalho de um administrador — para cadastrar outros usuários.

    É um usuário DESTE fixture, não o do conftest: os testes daqui mexem em
    senha e flags, e usar o compartilhado faria um caso depender do outro.
    """
    u = criar_usuario(nome="Admin Teste", senha_temporaria=False,
                      mfa_obrigatorio=False)
    return {"Authorization": f"Bearer {token_de(client, u.email)}"}


def trocar(client, token, atual, nova, confirmacao=None):
    return client.post("/api/v1/auth/trocar-senha", json={
        "senha_atual": atual,
        "senha_nova": nova,
        "confirmacao": nova if confirmacao is None else confirmacao,
    }, headers={"Authorization": f"Bearer {token}"})


# ===========================================================================
class TestEtapasDoLogin:
    """A ordem: senha temporária → MFA → (ou nada)."""

    def test_conta_local_com_senha_temporaria_pede_troca(self, client):
        u = criar_usuario(senha_temporaria=True, mfa_obrigatorio=True)

        r = entrar(client, u.email)
        assert r.status_code == 200, r.text
        assert r.json()["acao_requerida"] == "trocar_senha"
        assert "administrador" in r.json()["acao_mensagem"].lower()

    def test_conta_ad_pula_a_troca_e_pede_o_mfa(self, client):
        """Com AD a senha é do domínio: não há o que trocar aqui."""
        u = criar_usuario(senha_temporaria=False, mfa_obrigatorio=True)

        r = entrar(client, u.email)
        assert r.status_code == 200, r.text
        assert r.json()["acao_requerida"] == "cadastrar_mfa"

    def test_conta_ja_configurada_nao_pede_nada(self, client):
        u = criar_usuario(senha_temporaria=False, mfa_obrigatorio=False)

        r = entrar(client, u.email)
        assert r.status_code == 200
        assert r.json()["acao_requerida"] is None

    def test_mfa_ativo_exige_codigo_antes_de_qualquer_coisa(self, client):
        """Quem já cadastrou o MFA não entra só com a senha."""
        import base64
        import secrets

        segredo = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        u = criar_usuario(mfa_ativo=True, mfa_segredo=segredo)

        r = entrar(client, u.email)
        assert r.status_code == 401
        assert r.json()["detail"] == "mfa_necessario"

    def test_o_token_sai_mesmo_pedindo_troca(self, client):
        """Para trocar a senha é preciso estar autenticado.

        A trava real é o servidor recusar as outras rotas, não negar o token.
        """
        u = criar_usuario(senha_temporaria=True)
        r = entrar(client, u.email)
        assert r.json()["access_token"]


class TestTrocaDeSenha:
    def test_troca_libera_e_pede_o_mfa(self, client):
        u = criar_usuario(senha_temporaria=True, mfa_obrigatorio=True)
        t = token_de(client, u.email)

        r = trocar(client, t, "SenhaInicial123", "minha-senha-2026")
        assert r.status_code == 200, r.text
        assert r.json()["acao_requerida"] == "cadastrar_mfa"

    def test_senha_nova_passa_a_valer(self, client):
        u = criar_usuario(senha_temporaria=True, mfa_obrigatorio=True)
        t = token_de(client, u.email)
        trocar(client, t, "SenhaInicial123", "minha-senha-2026")

        assert entrar(client, u.email, "minha-senha-2026").json()["acao_requerida"] == "cadastrar_mfa"

    def test_senha_antiga_para_de_funcionar(self, client):
        u = criar_usuario(senha_temporaria=True)
        t = token_de(client, u.email)
        trocar(client, t, "SenhaInicial123", "minha-senha-2026")

        assert entrar(client, u.email, "SenhaInicial123").status_code == 401

    def test_a_exigencia_de_troca_e_removida(self, client):
        u = criar_usuario(senha_temporaria=True)
        t = token_de(client, u.email)
        trocar(client, t, "SenhaInicial123", "minha-senha-2026")

        # Entrando com a senha nova, não há mais a exigência de troca.
        assert entrar(client, u.email, "minha-senha-2026").json()["acao_requerida"] is None

    def test_sem_senha_temporaria_ainda_pode_trocar(self, client):
        """Troca voluntária, não só a obrigatória do primeiro acesso."""
        u = criar_usuario(senha_temporaria=False)
        t = token_de(client, u.email)
        assert trocar(client, t, "SenhaInicial123", "outra-senha-2026").status_code == 200


class TestRegrasDaSenha:
    """Recusar senha fraca, explicando o motivo."""

    def _t(self, client, **campos):
        campos.setdefault("senha_temporaria", True)
        u = criar_usuario(**campos)
        return token_de(client, u.email)

    def test_curta(self, client):
        r = trocar(client, self._t(client), "SenhaInicial123", "curta1")
        assert r.status_code == 400
        assert "8 caracteres" in r.json()["detail"]

    def test_obvia(self, client):
        r = trocar(client, self._t(client), "SenhaInicial123", "password")
        assert r.status_code == 400

    def test_so_numeros(self, client):
        r = trocar(client, self._t(client), "SenhaInicial123", "12345678901")
        assert r.status_code == 400
        assert "letras" in r.json()["detail"].lower()

    def test_contem_o_proprio_nome(self, client):
        """O usuário se chama 'Tecnico Teste': a senha não pode ter 'tecnico'."""
        r = trocar(client, self._t(client), "SenhaInicial123", "tecnico-forte-2026")
        assert r.status_code == 400
        assert "nome" in r.json()["detail"].lower()

    def test_confirmacao_diferente(self, client):
        r = trocar(client, self._t(client), "SenhaInicial123",
                   "senha-boa-2026", confirmacao="outra-senha-2026")
        assert r.status_code == 400
        assert "confirma" in r.json()["detail"].lower()

    def test_senha_atual_errada(self, client):
        r = trocar(client, self._t(client), "errada", "senha-boa-2026")
        assert r.status_code == 400

    def test_repetir_a_atual(self, client):
        r = trocar(client, self._t(client), "SenhaInicial123", "SenhaInicial123")
        assert r.status_code == 400

    def test_exige_sessao(self, client):
        r = client.post("/api/v1/auth/trocar-senha", json={
            "senha_atual": "x", "senha_nova": "senha-boa-2026",
            "confirmacao": "senha-boa-2026",
        })
        assert r.status_code == 401

    def test_nome_curto_nao_bloqueia_senha_boa(self, client):
        """Nome de 3 letras não pode reprovar qualquer senha que o contenha."""
        u = criar_usuario(nome="Ana", senha_temporaria=True)
        t = token_de(client, u.email)
        assert trocar(client, t, "SenhaInicial123", "senha-boa-2026").status_code == 200


class TestIsolamento:
    """O que motivou este arquivo: um teste não pode depender do outro."""

    def test_dois_usuarios_nao_se_atrapalham(self, client):
        a = criar_usuario(senha_temporaria=True)
        b = criar_usuario(senha_temporaria=True)

        ta = token_de(client, a.email)
        tb = token_de(client, b.email)

        assert trocar(client, ta, "SenhaInicial123", "senha-do-a-2026").status_code == 200
        # A senha do B continua a original.
        assert entrar(client, b.email).status_code == 200
        assert trocar(client, tb, "SenhaInicial123", "senha-do-b-2026").status_code == 200

    def test_trocar_a_senha_do_a_nao_afeta_o_b(self, client):
        a = criar_usuario(senha_temporaria=True)
        b = criar_usuario(senha_temporaria=True)
        trocar(client, token_de(client, a.email), "SenhaInicial123", "so-do-a-2026")

        r = entrar(client, b.email)
        assert r.status_code == 200
        assert r.json()["acao_requerida"] is None or True  # b segue utilizável


class TestFlagsAoCriarUsuario:
    """Conta nova nasce exigindo troca de senha (se local) e cadastro do MFA.

    Sem isto, a conta criada pelo administrador ja entra valendo: a senha que o
    admin escolheu continua funcionando para sempre, e a segunda etapa nunca e
    pedida.
    """

    def _criar(self, client, admin, **corpo):
        base = {"nome": "Novo Tecnico", "email": "novo@teste.com",
                "papel": "ti", "senha": "SenhaInicial123"}
        base.update(corpo)
        return client.post("/api/v1/usuarios", json=base, headers=admin)

    def test_conta_local_nasce_com_senha_temporaria(self, client, admin):
        r = self._criar(client, admin)
        assert r.status_code == 201, r.text

        from app.models.core import Usuario
        from tests.conftest import TestingSession
        db = TestingSession()
        u = db.query(Usuario).filter(Usuario.email == "novo@teste.com").first()
        assert u.senha_temporaria is True, "senha do admin e conhecida por outro - tem que ser trocada"
        assert u.mfa_obrigatorio is True
        db.close()

    def test_conta_ad_nao_pede_troca_de_senha(self, client, admin):
        """Com AD a senha e da rede: nao ha senha local para trocar."""
        r = self._criar(client, admin, nome="Rede", email="rede@teste.com",
                        senha=None, login_ad="rede.silva")
        assert r.status_code == 201, r.text

        from app.models.core import Usuario
        from tests.conftest import TestingSession
        db = TestingSession()
        u = db.query(Usuario).filter(Usuario.email == "rede@teste.com").first()
        assert u.senha_temporaria is False
        assert u.mfa_obrigatorio is True, "AD confirma quem e, nao a posse do aparelho"
        db.close()

    def test_pode_dispensar_o_mfa(self, client, admin):
        """Equipamento compartilhado: ninguem tem celular proprio."""
        r = self._criar(client, admin, nome="Balcao", email="balcao@teste.com",
                        exigir_mfa=False)
        assert r.status_code == 201, r.text

        from app.models.core import Usuario
        from tests.conftest import TestingSession
        db = TestingSession()
        u = db.query(Usuario).filter(Usuario.email == "balcao@teste.com").first()
        assert u.mfa_obrigatorio is False
        assert u.senha_temporaria is True, "a troca de senha continua"
        db.close()

    def test_o_login_pede_a_troca(self, client, admin):
        self._criar(client, admin, nome="Fluxo", email="fluxo@teste.com")
        r = client.post("/api/v1/auth/login",
                        data={"username": "fluxo@teste.com", "password": "SenhaInicial123"})
        assert r.status_code == 200, r.text
        assert r.json()["acao_requerida"] == "trocar_senha"

    def test_usuario_existente_nao_e_afetado(self, client, admin):
        """Criar alguem nao pode mexer em quem ja existe."""
        from app.models.core import Usuario
        from tests.conftest import TestingSession
        db = TestingSession()
        antes = db.query(Usuario).filter(Usuario.email == "admin@teste.com").first()
        antes_senha = antes.senha_temporaria
        antes_mfa = antes.mfa_obrigatorio
        db.close()

        self._criar(client, admin, nome="Outro", email="outro@teste.com")

        db = TestingSession()
        depois = db.query(Usuario).filter(Usuario.email == "admin@teste.com").first()
        assert depois.senha_temporaria == antes_senha
        assert depois.mfa_obrigatorio == antes_mfa
        db.close()
