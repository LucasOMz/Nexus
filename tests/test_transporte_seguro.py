"""Transporte HTTPS de produção e autenticação LDAPS."""
import ssl
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import settings
from app.main import app
from app.models import ConfiguracaoSistema
from app.services import ldap_service


def test_https_obrigatorio_em_producao(client, monkeypatch):
    assert client.get("/health").status_code == 200
    monkeypatch.setattr(settings, "env", "production")
    resposta = client.post(
        "/api/v1/auth/login", headers={"X-Forwarded-Proto": "https"},
        data={"username": "admin@teste.com", "password": "credencial-simulada"},
    )
    assert resposta.status_code == 426
    assert resposta.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in resposta.headers

    https = client.get("https://testserver/health")
    assert https.status_code == 200, https.text
    assert https.headers["strict-transport-security"] == "max-age=31536000"


def test_https_encaminhado_so_funciona_com_ip_do_proxy_confiavel(monkeypatch):
    monkeypatch.setattr(settings, "env", "production")
    nginx_ip = "172.30.254.2"
    proxied_app = ProxyHeadersMiddleware(app, trusted_hosts=nginx_ip)
    headers = {"X-Forwarded-Proto": "https", "X-Forwarded-For": "203.0.113.9"}
    with TestClient(proxied_app, client=("172.30.254.3", 1234)) as externo:
        assert externo.get("/health", headers=headers).status_code == 426
    with TestClient(proxied_app, client=(nginx_ip, 1234)) as nginx:
        assert nginx.get("/health").status_code == 426
        resposta = nginx.get("/health", headers=headers)
        assert resposta.status_code == 200
        assert "strict-transport-security" in resposta.headers


@pytest.mark.parametrize("inseguro", [
    {"ldap_tls": False}, {"ldap_ignorar_certificado": True},
    {"ldap_servidor": "ldap://dc01.empresa.test"}, {"ldap_porta": None},
])
def test_admin_nao_pode_salvar_configuracao_insegura(client, auth_headers, inseguro):
    caminho = "/api/v1/admin/config"
    assert client.put(caminho, json=inseguro, headers=auth_headers).status_code == 422
    assert client.put(caminho, json={"ldap_tls": True, "ldap_ignorar_certificado": False},
                      headers=auth_headers).status_code == 200


def configuracao_ldap(**mudancas):
    dados = {
        "ldap_servidor": "dc01.empresa.test",
        "ldap_porta": 636,
        "ldap_ativo": True,
        "ldap_tls": True,
        "ldap_ignorar_certificado": False,
        "ldap_bind_dn": "svc@empresa.test",
        "ldap_base_dn": "DC=empresa,DC=test",
        "ldap_filtro_usuario": "(sAMAccountName={usuario})",
    }
    return ConfiguracaoSistema(**(dados | mudancas))


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


def test_binds_ldaps_exigem_certificado_e_desabilitam_referencias(monkeypatch, tmp_path):
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
    assert ldap_service.autenticar(configuracao_ldap(), "teste", "credencial-simulada").ok
    assert connection.call_count == 2
    for chamada in connection.call_args_list:
        servidor = chamada.args[0]
        assert servidor.ssl and servidor.port == 636
        assert servidor.tls.validate == ssl.CERT_REQUIRED
        assert servidor.tls.ca_certs_file == str(caminho_ca)
        assert chamada.kwargs["auto_referrals"] is False
