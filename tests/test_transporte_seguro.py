"""Acesso HTTP no Compose e modos de conexão da autenticação LDAP."""
import ssl
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, text

from app.config import settings
from app.database import _adicionar_colunas_faltantes
from app.models import ConfiguracaoSistema
from app.services import ldap_service


def test_http_serve_frontend_e_api_em_producao(client, monkeypatch):
    monkeypatch.setattr(settings, "env", "production")
    for caminho in ("/", "/health"):
        resposta = client.get(caminho, follow_redirects=False)
        assert resposta.status_code == 200
        assert "strict-transport-security" not in resposta.headers
    assert client.get("/api/v1/ativos", follow_redirects=False).status_code == 401


@pytest.mark.parametrize("inseguro", [
    {"ldap_tls": False}, {"ldap_ignorar_certificado": True},
    {"ldap_servidor": "ldap://dc01.empresa.test"}, {"ldap_porta": None},
])
def test_admin_nao_pode_salvar_transporte_sem_autorizacao_ou_incompativel(client, auth_headers, inseguro):
    caminho = "/api/v1/admin/config"
    assert client.put(caminho, json=inseguro, headers=auth_headers).status_code == 422
    assert client.put(caminho, json={"ldap_tls": True, "ldap_ignorar_certificado": False},
                      headers=auth_headers).status_code == 200


def test_admin_pode_selecionar_ldap_sem_tls_e_voltar_para_ldaps(client, auth_headers):
    caminho = "/api/v1/admin/config"
    resposta = client.put(caminho, json={
        "ldap_servidor": "ldap://dc01.empresa.test",
        "ldap_tls": False,
        "ldap_permitir_sem_tls": True,
    }, headers=auth_headers)
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["ldap_porta"] == 389
    cfg = client.get(caminho, headers=auth_headers).json()
    assert cfg["ldap_tls"] is False and cfg["ldap_permitir_sem_tls"] is True
    assert client.put(caminho, json={"ldap_servidor": "ldaps://dc01.empresa.test"},
                      headers=auth_headers).status_code == 422
    assert client.put(caminho, json={"ldap_ignorar_certificado": True},
                      headers=auth_headers).status_code == 422

    resposta = client.put(caminho, json={"ldap_servidor": "dc01.empresa.test", "ldap_tls": True},
                          headers=auth_headers)
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["ldap_permitir_sem_tls"] is False
    assert resposta.json()["ldap_porta"] == 636


def test_diagnostico_ldap_com_nul_e_exibido_e_gravado(client, auth_headers, monkeypatch):
    caminho = "/api/v1/admin/config"
    cfg = client.put(caminho, json={
        "ldap_servidor": "dc01.empresa.test",
        "ldap_bind_dn": "svc@empresa.test",
        "ldap_porta": 389,
        "ldap_tls": False,
        "ldap_permitir_sem_tls": True,
    }, headers=auth_headers)
    assert cfg.status_code == 200
    conexao = Mock(result={"message": "AcceptSecurityContext error, data 52e\x00"})
    conexao.bind.return_value = False
    monkeypatch.setattr(ldap_service, "Connection", Mock(return_value=conexao))

    resposta = client.post(f"{caminho}/testar-ldap", headers=auth_headers)
    mensagem = "Falha ao autenticar a conta de serviço: AcceptSecurityContext error, data 52e"
    assert resposta.status_code == 200, resposta.text
    assert resposta.json() == {"ok": False, "mensagem": mensagem}
    assert client.get(caminho, headers=auth_headers).json()["ldap_ultimo_teste_msg"] == mensagem


def configuracao_ldap(**mudancas):
    dados = {
        "ldap_servidor": "dc01.empresa.test",
        "ldap_porta": 636,
        "ldap_ativo": True,
        "ldap_tls": True,
        "ldap_permitir_sem_tls": False,
        "ldap_ignorar_certificado": False,
        "ldap_bind_dn": "svc@empresa.test",
        "ldap_base_dn": "DC=empresa,DC=test",
        "ldap_filtro_usuario": "(sAMAccountName={usuario})",
    }
    return ConfiguracaoSistema(**(dados | mudancas))


def test_atualizacao_do_banco_nao_autoriza_ldap_legado_sem_tls():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE configuracoes (id INTEGER PRIMARY KEY, ldap_tls BOOLEAN NOT NULL)"))
        conn.execute(text("INSERT INTO configuracoes (id, ldap_tls) VALUES (1, FALSE)"))
    assert "configuracoes.ldap_permitir_sem_tls" in _adicionar_colunas_faltantes(engine)
    with engine.connect() as conn:
        assert tuple(conn.execute(text("SELECT ldap_tls, ldap_permitir_sem_tls FROM configuracoes")).one()) == (0, 0)
    engine.dispose()


@pytest.mark.parametrize("inseguro", [
    {"ldap_tls": False}, {"ldap_ignorar_certificado": True}, {"ldap_servidor": "ldap://dc01.empresa.test"},
])
def test_ldap_legado_inseguro_falha_antes_de_conectar(monkeypatch, inseguro):
    connection = Mock()
    monkeypatch.setattr(ldap_service, "Connection", connection)
    cfg = configuracao_ldap(**inseguro)
    assert ldap_service.testar_conexao(cfg)[0] is False
    assert ldap_service.autenticar(cfg, "teste", "credencial-simulada").ok is False
    assert ldap_service.buscar_usuario(cfg, "teste")[0] is False
    connection.assert_not_called()


@pytest.mark.parametrize(("tls", "porta"), [(True, 636), (False, 389)])
def test_binds_usam_o_transporte_salvo_e_desabilitam_referencias(monkeypatch, tmp_path, tls, porta):
    caminho_ca = tmp_path / "ca.pem"
    caminho_ca.touch()
    monkeypatch.setattr(settings, "ldap_ca_file", str(caminho_ca))
    entrada = Mock(entry_dn="CN=Usuário,DC=empresa,DC=test")
    servico = Mock(entries=[entrada])
    usuario = Mock()
    connection = Mock(side_effect=[servico, usuario])
    monkeypatch.setattr(ldap_service, "Connection", connection)
    monkeypatch.setattr(ldap_service, "_atributo", lambda *_: None)
    monkeypatch.setattr(ldap_service, "_grupos_do_usuario", lambda *_: [])
    cfg = configuracao_ldap(ldap_tls=tls, ldap_porta=porta, ldap_permitir_sem_tls=not tls)
    assert ldap_service.autenticar(cfg, "teste", "credencial-simulada").ok
    assert connection.call_count == 2
    for chamada in connection.call_args_list:
        servidor = chamada.args[0]
        assert servidor.ssl is tls
        assert servidor.port == porta
        if tls:
            assert servidor.tls.validate == ssl.CERT_REQUIRED
            assert servidor.tls.ca_certs_file == str(caminho_ca)
        else:
            assert servidor.tls is None
        assert chamada.kwargs["auto_referrals"] is False


@pytest.mark.parametrize("sam", ["20110030", "outra-conta"])
def test_ldap_so_aceita_upn_alternativo_da_conta_vinculada(monkeypatch, sam):
    email = "colaborador@empresa.test"
    entrada = Mock(entry_dn="CN=Colaborador,DC=empresa,DC=test")
    servico = Mock(entries=[entrada])
    servico.search.side_effect = lambda base, filtro, **kwargs: filtro == f"(userPrincipalName={email})"
    connection = Mock(side_effect=[servico, Mock()])
    monkeypatch.setattr(ldap_service, "Connection", connection)
    monkeypatch.setattr(ldap_service, "_atributo",
                        lambda _, nome: {"sAMAccountName": sam, "userPrincipalName": email}.get(nome))
    monkeypatch.setattr(ldap_service, "_grupos_do_usuario", lambda *_: [])
    cfg = configuracao_ldap(ldap_filtro_usuario="(userPrincipalName={usuario})")

    resultado = ldap_service.autenticar(cfg, "20110030", "credencial-simulada", email_alternativo=email)

    assert resultado.ok is (sam == "20110030")
    assert connection.call_count == (2 if resultado.ok else 1)
