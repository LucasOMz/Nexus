"""Testes de ativos e extensões (TI/Impressora), status e atribuição."""
from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.core.security import create_access_token
from app.models.core import ConfiguracaoSistema, Movimentacao, Usuario
from app.routers import auth
from app.services import ldap_service
from tests.conftest import TestingSession


def test_create_ativo_ti(client, auth_headers):
    payload = {
        "dominio": "ti",
        "patrimonio": "TI-0001", "numero_serie": "NS-TI-0001",
        "modelo": "Latitude 5440",
        "ti": {"hostname": "pc-001", "ram_gb": 16, "mac_address": "AA:BB:CC:DD:EE:FF"},
    }
    res = client.post("/api/v1/ativos", json=payload, headers=auth_headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["dominio"] == "ti"
    assert body["ti"]["hostname"] == "pc-001"
    assert body["ti"]["ram_gb"] == 16


def test_create_ativo_impressora(client, auth_headers):
    payload = {
        "dominio": "impressora",
        "patrimonio": "IMP-0001", "numero_serie": "NS-IMP-0001",
        "modelo": "HP LaserJet",
        "impressora": {"tipo_impressao": "laser", "colorida": False, "contador_paginas": 1000},
    }
    res = client.post("/api/v1/ativos", json=payload, headers=auth_headers)
    assert res.status_code == 201, res.text
    assert res.json()["impressora"]["contador_paginas"] == 1000


def test_list_ativos(client, auth_headers):
    client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": "TI-100", "numero_serie": "NS-TI-100"}, headers=auth_headers)
    res = client.get("/api/v1/ativos", params={"dominio": "ti"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["total"] == 1


def test_patrimonio_duplicado(client, auth_headers):
    payload = {"dominio": "ti", "patrimonio": "TI-DUP", "numero_serie": "NS-TI-DUP"}
    assert client.post("/api/v1/ativos", json=payload, headers=auth_headers).status_code == 201
    assert client.post("/api/v1/ativos", json=payload, headers=auth_headers).status_code == 409


def test_change_status(client, auth_headers):
    ativo_id = client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": "TI-S", "numero_serie": "NS-TI-S"}, headers=auth_headers).json()["id"]
    res = client.patch(f"/api/v1/ativos/{ativo_id}/status", json={"status": "em_uso"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "em_uso"


def test_atribuir_gera_termo(client, auth_headers):
    ativo_id = client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": "TI-A", "numero_serie": "NS-TI-A", "modelo": "Notebook"}, headers=auth_headers).json()["id"]
    # Cria um colaborador (leitor) para receber o ativo.
    usr = client.post("/api/v1/usuarios", json={"nome": "Colab", "email": "c@teste.com", "papel": "leitor", "senha": "123456"}, headers=auth_headers)
    assert usr.status_code == 201, usr.text
    usr_id = usr.json()["id"]

    res = client.post(f"/api/v1/ativos/{ativo_id}/atribuir", json={"usuario_id": usr_id}, headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "em_uso"

    termos = client.get(f"/api/v1/ativos/{ativo_id}/termos", headers=auth_headers).json()
    assert len(termos) == 1
    assert len(termos[0]["hash_sha256"]) == 64


def test_atribuir_colaborador_ad_sem_cadastro_e_sem_liberar_login(client, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "media_dir", str(tmp_path))
    identidades = {"login": "joao.silva", "nome": "João da Silva", "email": "joao@empresa.com", "dn": "CN=João"}
    buscas = []

    def localizar(_, login):
        buscas.append(login)
        return True, "Encontrado.", identidades

    monkeypatch.setattr(ldap_service, "buscar_usuario", localizar)
    with TestingSession() as db:
        cfg = db.get(ConfiguracaoSistema, 1) or ConfiguracaoSistema(id=1)
        cfg.ldap_ativo = True
        cfg.ldap_servidor = "dc.empresa.local"
        cfg.ldap_base_dn = "DC=empresa,DC=local"
        db.add(cfg)
        db.add(Usuario(id=50, nome="Leitor", email="leitor@empresa.com", senha_hash="x",
                       papel="leitor", planta_id=1, permissoes={"modulos": ["ativos"], "inventarios": ["ti"]}))
        db.commit()
    ativo = client.post("/api/v1/ativos", json={
        "dominio": "ti", "patrimonio": "TI-AD", "numero_serie": "NS-AD",
    }, headers=auth_headers).json()
    rota = f"/api/v1/ativos/{ativo['id']}"
    leitor = {"Authorization": f"Bearer {create_access_token(50, 'leitor')}"}
    pedido = {"login_ad": "joao.silva"}
    assert client.get(rota + "/atribuicao-ad", headers=auth_headers).json() == {"disponivel": True}
    assert client.post(rota + "/atribuicao-ad", json=pedido, headers=leitor).status_code == 403
    assert buscas == []
    consulta = client.post(rota + "/atribuicao-ad", json=pedido, headers=auth_headers)
    assert consulta.json() == {campo: identidades[campo] for campo in ("login", "nome", "email")}
    with TestingSession() as db:
        assert db.scalar(select(Usuario).where(Usuario.login_ad == "joao.silva")) is None
    assert client.post(rota + "/atribuir", json={**pedido, "usuario_id": 1}, headers=auth_headers).status_code == 422
    for _ in range(2):
        atribuicao = client.post(rota + "/atribuir", json=pedido, headers=auth_headers)
        assert atribuicao.status_code == 200, atribuicao.text
    with TestingSession() as db:
        pessoa, = db.scalars(select(Usuario).where(Usuario.login_ad == "joao.silva")).all()
        assert pessoa.origem == "ad" and not pessoa.ativo and pessoa.papel == "leitor"
        assert db.scalars(select(Movimentacao.destino_usuario_id).where(
            Movimentacao.ativo_id == ativo["id"], Movimentacao.tipo == "atribuicao",
        )).all() == [pessoa.id, pessoa.id]
    termos = client.get(rota + "/termos", headers=auth_headers).json()
    assert len(termos) == 2 and len(list(tmp_path.glob("termos/*.pdf"))) == 2
    monkeypatch.setattr(auth, "autenticar", lambda *_: ldap_service.ResultadoLDAP(True, "Autenticado"))
    login = client.post("/api/v1/auth/login", data={"username": "joao.silva", "password": "senha-de-rede"})
    assert login.status_code == 403 and login.json()["detail"] == "Usuário inativo"


def test_ad_desligado_preserva_a_atribuicao_a_colaborador_local(client, auth_headers):
    ativo = client.post("/api/v1/ativos", json={
        "dominio": "ti", "patrimonio": "TI-OFF", "numero_serie": "NS-OFF",
    }, headers=auth_headers).json()
    rota = f"/api/v1/ativos/{ativo['id']}"
    assert client.get(rota + "/atribuicao-ad", headers=auth_headers).json() == {"disponivel": False}
    assert client.post(rota + "/atribuir", json={"login_ad": "joao.silva"}, headers=auth_headers).status_code == 409
