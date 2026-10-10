"""Reprodução: criar usuário pelo Admin e entrar com ele.

Escrito para investigar o relato de "senha incorreta" ao criar usuário novo.
Tenta o caminho EXATO do frontend, inclusive o payload com permissões.
"""
from __future__ import annotations

from app.core.security import hash_password
from app.models.core import Usuario
from app.models.enums import PapelUsuario


def _admin(client):
    from tests.conftest import TestingSession

    db = TestingSession()
    u = Usuario(nome="Admin Rep", email="adminrep@teste.com",
                senha_hash=hash_password("SenhaAdmin123"),
                papel=PapelUsuario.ADMIN, origem="local", ativo=True,
                senha_temporaria=False, mfa_obrigatorio=False)
    db.add(u)
    db.commit()
    db.refresh(u)
    db.close()

    r = client.post("/api/v1/auth/login",
                    data={"username": "adminrep@teste.com", "password": "SenhaAdmin123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _payload(nome, email, senha, **extra):
    """Igual ao que o formulário do Admin monta."""
    p = {
        "nome": nome,
        "email": email,
        "papel": "ti",
        "departamento_id": None,
        "planta_id": None,
        "ativo": True,
        "login_ad": None,
        "permissoes": {
            "inventarios": ["ti", "impressora"],
            "modulos": ["ativos", "produtos"],
            "pode_escrever": True,
            "pode_excluir": False,
        },
    }
    p.update(extra)
    if senha is not None:
        p["senha"] = senha
    return p


class TestCriarEEntrar:
    def test_criar_com_senha_e_entrar(self, client):
        h = _admin(client)

        r = client.post("/api/v1/usuarios",
                        json=_payload("Novo Um", "novo1@teste.com", "Senha12345"), headers=h)
        assert r.status_code == 201, f"CRIACAO FALHOU: {r.status_code} {r.text}"

        login = client.post("/api/v1/auth/login",
                            data={"username": "novo1@teste.com", "password": "Senha12345"})
        assert login.status_code == 200, f"LOGIN FALHOU: {login.status_code} {login.text}"
        assert login.json()["acao_requerida"] == "trocar_senha"

    def test_senha_curta_na_criacao(self, client):
        """O formulário aceita 6 caracteres; o schema também?"""
        h = _admin(client)
        r = client.post("/api/v1/usuarios",
                        json=_payload("Novo Dois", "novo2@teste.com", "abc123"), headers=h)
        assert r.status_code == 201, f"{r.status_code} {r.text}"

        login = client.post("/api/v1/auth/login",
                            data={"username": "novo2@teste.com", "password": "abc123"})
        assert login.status_code == 200, f"LOGIN FALHOU: {login.status_code} {login.text}"

    def test_trocar_a_senha_no_primeiro_acesso(self, client):
        h = _admin(client)
        client.post("/api/v1/usuarios",
                    json=_payload("Novo Tres", "novo3@teste.com", "Senha12345"), headers=h)

        login = client.post("/api/v1/auth/login",
                            data={"username": "novo3@teste.com", "password": "Senha12345"})
        token = login.json()["access_token"]

        troca = client.post("/api/v1/auth/trocar-senha", json={
            "senha_atual": "Senha12345",
            "senha_nova": "MinhaSenha2026",
            "confirmacao": "MinhaSenha2026",
        }, headers={"Authorization": f"Bearer {token}"})
        assert troca.status_code == 200, f"TROCA FALHOU: {troca.status_code} {troca.text}"

        depois = client.post("/api/v1/auth/login",
                             data={"username": "novo3@teste.com", "password": "MinhaSenha2026"})
        assert depois.status_code == 200, f"{depois.status_code} {depois.text}"

    def test_conta_de_rede_nao_entra_com_senha_local(self, client):
        """Se o formulário mandar login_ad junto, a senha digitada é ignorada.

        Este é o caminho que produz "senha incorreta" sem que nada esteja
        quebrado: a conta virou de REDE, e quem autentica é o diretório.
        """
        h = _admin(client)
        r = client.post("/api/v1/usuarios",
                        json=_payload("Rede Um", "rede1@teste.com", "Senha12345",
                                      login_ad="rede.um"), headers=h)
        assert r.status_code == 201, r.text

        login = client.post("/api/v1/auth/login",
                            data={"username": "rede1@teste.com", "password": "Senha12345"})
        # Sem AD configurado no teste, a autenticação de rede falha.
        assert login.status_code == 401

    def test_senha_do_novo_usuario_e_a_que_o_admin_digitou(self, client):
        """Confere direto no banco: o hash guardado corresponde à senha?"""
        from app.core.security import verify_password
        from tests.conftest import TestingSession

        h = _admin(client)
        client.post("/api/v1/usuarios",
                    json=_payload("Novo Quatro", "novo4@teste.com", "Senha12345"), headers=h)

        db = TestingSession()
        u = db.query(Usuario).filter(Usuario.email == "novo4@teste.com").first()
        assert u is not None
        assert u.origem == "local", "virou conta de rede sem querer"
        assert verify_password("Senha12345", u.senha_hash), "o hash não corresponde à senha digitada"
        assert u.senha_temporaria is True
        db.close()
