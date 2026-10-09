"""Acesso pelo AD: o diretório autentica, o sistema autoriza.

Mudança de modelo:
  * ANTES — quem estivesse num grupo do AD entrava (e podia ser criado sozinho).
  * AGORA — o AD só confirma a senha de rede. Quem entra é quem o
    **administrador cadastrou**, com a planta e o acesso que ele definir.

O AD também serve para **buscar o nome** da pessoa na tela de cadastro.
"""
from __future__ import annotations

import pytest

from app.core.rate_limit import login_limiter, scan_limiter
from app.services.ldap_service import ResultadoLDAP


@pytest.fixture(autouse=True)
def _liberar_rate_limit():
    login_limiter._hits.clear()
    scan_limiter._hits.clear()
    yield
    login_limiter._hits.clear()
    scan_limiter._hits.clear()


@pytest.fixture
def ad_ligado(client, auth_headers):
    """Liga o AD na configuração, apontando para um servidor fictício."""
    client.put("/api/v1/admin/config", json={
        "ldap_ativo": True,
        "ldap_servidor": "dc01.empresa.local",
        "ldap_base_dn": "DC=empresa,DC=local",
        "ldap_bind_dn": "svc@empresa.local",
        "ldap_bind_senha": "senha-servico",
    }, headers=auth_headers)
    return auth_headers


def _autentica(monkeypatch, ok=True, nome="João da Silva", login="joao.silva",
               email="joao.silva@empresa.com"):
    """Substitui a validação no AD por uma resposta fixa."""
    from app.routers import auth as auth_router

    def falso(cfg, usuario, senha):
        if not ok:
            return ResultadoLDAP(False, "Usuário ou senha inválidos.")
        return ResultadoLDAP(True, "Autenticado.", dn=f"CN={nome},DC=empresa,DC=local",
                             email=email, nome=nome, login=login, grupos=[])

    monkeypatch.setattr(auth_router, "autenticar", falso)


def _criar_usuario(client, auth_headers, **extra):
    dados = {
        "nome": "João da Silva", "email": "joao.silva@empresa.com",
        "papel": "leitor", "senha": "senha123",
    }
    dados.update(extra)
    return client.post("/api/v1/usuarios", json=dados, headers=auth_headers)


class TestRemocaoDoAcessoPorGrupo:
    """O grupo do AD não libera mais nada."""

    def test_config_nao_tem_mais_grupo_de_acesso(self, client, auth_headers):
        # Os campos de grupo continuam existindo no banco (compatibilidade),
        # mas a decisão de acesso não passa mais por eles.
        import inspect

        from app.routers.auth import login
        fonte = inspect.getsource(login)
        assert "ldap_grupo_acesso" not in fonte
        assert "ldap_provisionar" not in fonte
        assert "provisionar_usuario" not in fonte

    def test_nao_existe_mais_provisionamento_automatico(self):
        from app.routers import auth as auth_router
        assert not hasattr(auth_router, "_provisionar_usuario"), \
            "a criação automática de usuário deveria ter sido removida"

    def test_login_nao_verifica_grupo(self):
        import inspect

        from app.services.ldap_service import autenticar

        fonte = inspect.getsource(autenticar)
        assert "_grupo_confere(grupos, cfg.ldap_grupo_acesso)" not in fonte


class TestADNaoLiberaAcesso:
    """Senha de rede válida não basta: precisa estar cadastrado."""

    def test_usuario_de_rede_sem_cadastro_recebe_explicacao(self, client, ad_ligado, monkeypatch):
        _autentica(monkeypatch, ok=True, login="ninguem.cadastrado")

        r = client.post("/api/v1/auth/login",
                        data={"username": "ninguem.cadastrado", "password": "senha-de-rede"})
        assert r.status_code == 403
        assert "não tem acesso" in r.json()["detail"]
        assert "administrador" in r.json()["detail"].lower()

    def test_senha_errada_continua_generica(self, client, ad_ligado, monkeypatch):
        """Não pode revelar se a pessoa existe."""
        _autentica(monkeypatch, ok=False)

        r = client.post("/api/v1/auth/login",
                        data={"username": "joao.silva", "password": "errada"})
        assert r.status_code == 401

    def test_usuario_cadastrado_entra_com_senha_de_rede(self, client, ad_ligado, monkeypatch):
        """O fluxo pedido: cadastro feito pelo admin, login com a senha de rede."""
        _criar_usuario(client, ad_ligado, login_ad="joao.silva")
        _autentica(monkeypatch, ok=True, login="joao.silva")

        r = client.post("/api/v1/auth/login",
                        data={"username": "joao.silva", "password": "senha-de-rede"})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["nome"] == "João da Silva"

    def test_login_funciona_pelo_email_tambem(self, client, ad_ligado, monkeypatch):
        _criar_usuario(client, ad_ligado, login_ad="joao.silva")
        _autentica(monkeypatch, ok=True, login="joao.silva")

        r = client.post("/api/v1/auth/login",
                        data={"username": "joao.silva@empresa.com", "password": "senha-de-rede"})
        assert r.status_code == 200, r.text

    def test_nome_acompanha_o_diretorio(self, client, ad_ligado, monkeypatch):
        """O AD manda no nome; o sistema manda no resto."""
        _criar_usuario(client, ad_ligado, login_ad="joao.silva", nome="Nome Antigo")
        _autentica(monkeypatch, ok=True, login="joao.silva", nome="João da Silva Novo")

        client.post("/api/v1/auth/login",
                    data={"username": "joao.silva", "password": "senha-de-rede"})

        lista = client.get("/api/v1/usuarios", headers=ad_ligado).json()
        joao = next(u for u in lista if u.get("login_ad") == "joao.silva")
        assert joao["nome"] == "João da Silva Novo"

    def test_nome_novo_nao_muda_o_papel(self, client, ad_ligado, monkeypatch):
        """Promover a pessoa é decisão do administrador, não do diretório."""
        _criar_usuario(client, ad_ligado, login_ad="joao.silva", papel="leitor")
        _autentica(monkeypatch, ok=True, login="joao.silva")

        client.post("/api/v1/auth/login",
                    data={"username": "joao.silva", "password": "senha-de-rede"})

        lista = client.get("/api/v1/usuarios", headers=ad_ligado).json()
        joao = next(u for u in lista if u.get("login_ad") == "joao.silva")
        assert joao["papel"] == "leitor", "o AD não pode promover ninguém"


class TestCadastroDeContaDeRede:
    def test_conta_de_rede_nao_exige_senha(self, client, auth_headers):
        r = _criar_usuario(client, auth_headers, login_ad="maria.souza", senha=None)
        assert r.status_code == 201, r.text
        assert r.json()["login_ad"] == "maria.souza"
        assert r.json()["origem"] == "ad"

    def test_conta_local_sem_senha_e_recusada(self, client, auth_headers):
        r = _criar_usuario(client, auth_headers, senha=None)
        assert r.status_code == 400
        assert "senha" in r.json()["detail"].lower()

    def test_login_de_rede_nao_pode_repetir(self, client, auth_headers):
        _criar_usuario(client, auth_headers, login_ad="joao.silva")
        r = _criar_usuario(client, auth_headers, login_ad="JOAO.SILVA",
                           email="outro@empresa.com")
        assert r.status_code == 409
        assert "já está cadastrado" in r.json()["detail"]

    def test_conta_de_rede_nao_guarda_senha_util(self, client, auth_headers):
        """A senha local de uma conta de rede é aleatória e inútil."""
        # Envia senha JUNTO de propósito: ela não pode ser gravada.
        rid = _criar_usuario(client, auth_headers, login_ad="pedro@empresa.com",
                             senha="senha123").json()["id"]

        from app.database import get_db
        from app.models.core import Usuario

        sessao = next(client.app.dependency_overrides[get_db]())
        u = sessao.get(Usuario, rid)
        from app.core.security import verify_password
        assert not verify_password("senha123", u.senha_hash), (
            "a senha enviada não pode ser gravada numa conta de rede"
        )
        assert not verify_password("", u.senha_hash)

    def test_administrador_define_a_planta(self, client, auth_headers):
        pid = client.post("/api/v1/admin/plantas", json={"nome": "Bonito", "sigla": "BON"},
                          headers=auth_headers).json()["id"]
        r = _criar_usuario(client, auth_headers, login_ad="ana@empresa.com", planta_id=pid)
        assert r.json()["planta_id"] == pid


class TestBuscaNoAD:
    def test_busca_recusada_para_nao_admin(self, client, auth_headers):
        client.post("/api/v1/usuarios",
                    json={"nome": "Tec", "email": "tec.adbusca@teste.com", "papel": "ti",
                          "senha": "senha123"}, headers=auth_headers)
        login = client.post("/api/v1/auth/login",
                            data={"username": "tec.adbusca@teste.com", "password": "senha123"})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}

        r = client.post("/api/v1/admin/config/buscar-ad", json={"usuario": "joao"}, headers=h)
        assert r.status_code == 403

    def test_sem_servidor_configurado_avisa(self, client, auth_headers):
        r = client.post("/api/v1/admin/config/buscar-ad", json={"usuario": "joao"},
                        headers=auth_headers).json()
        assert r["ok"] is False
        assert "AD" in r["mensagem"] or "Autenticação" in r["mensagem"]

    def test_busca_devolve_nome_e_email(self, client, ad_ligado, monkeypatch):
        from app.services import ldap_service

        monkeypatch.setattr(ldap_service, "buscar_usuario", lambda cfg, login: (
            True, "Encontrado.",
            {"login": login, "nome": "João da Silva", "email": "joao.silva@empresa.com",
             "departamento": "TI", "cargo": "Analista", "dn": "CN=João,DC=empresa,DC=local"},
        ))

        r = client.post("/api/v1/admin/config/buscar-ad", json={"usuario": "joao.silva"},
                        headers=ad_ligado).json()
        assert r["ok"] is True
        assert r["dados"]["nome"] == "João da Silva"
        assert r["dados"]["email"] == "joao.silva@empresa.com"
        assert r["dados"]["departamento"] == "TI"

    def test_busca_avisa_se_ja_tem_cadastro(self, client, ad_ligado, monkeypatch):
        from app.services import ldap_service

        _criar_usuario(client, ad_ligado, login_ad="joao.silva")
        monkeypatch.setattr(ldap_service, "buscar_usuario", lambda cfg, login: (
            True, "Encontrado.",
            {"login": "joao.silva", "nome": "João da Silva", "email": "joao.silva@empresa.com"},
        ))

        r = client.post("/api/v1/admin/config/buscar-ad", json={"usuario": "joao.silva"},
                        headers=ad_ligado).json()
        assert r["ja_cadastrado"] is not None
        assert r["ja_cadastrado"]["nome"] == "João da Silva"

    def test_busca_nao_encontrado(self, client, ad_ligado, monkeypatch):
        from app.services import ldap_service

        monkeypatch.setattr(ldap_service, "buscar_usuario",
                            lambda cfg, login: (False, f"'{login}' não foi encontrado no diretório.", {}))

        r = client.post("/api/v1/admin/config/buscar-ad", json={"usuario": "fantasma"},
                        headers=ad_ligado).json()
        assert r["ok"] is False
        assert "não foi encontrado" in r["mensagem"]

    def test_busca_nao_autentica_ninguem(self, client, ad_ligado, monkeypatch):
        """A busca é só leitura: não cria usuário nem libera acesso."""
        from app.services import ldap_service

        monkeypatch.setattr(ldap_service, "buscar_usuario", lambda cfg, login: (
            True, "Encontrado.", {"login": login, "nome": "Fulano", "email": "fulano@empresa.com"},
        ))
        client.post("/api/v1/admin/config/buscar-ad", json={"usuario": "fulano"}, headers=ad_ligado)

        # Mesmo "encontrado" no AD, sem cadastro não entra.
        _autentica(monkeypatch, ok=True, login="fulano")
        r = client.post("/api/v1/auth/login",
                        data={"username": "fulano", "password": "senha-de-rede"})
        assert r.status_code == 403
