"""Acesso HTTP no Compose e autenticação LDAPS."""
import ssl
from unittest.mock import Mock

import pytest

from app.config import settings
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
