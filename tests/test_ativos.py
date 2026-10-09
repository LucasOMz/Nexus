"""Testes de ativos e extensões (TI/Impressora), status e atribuição."""
from __future__ import annotations


def test_create_ativo_ti(client, auth_headers):
    payload = {
        "dominio": "ti",
        "patrimonio": "TI-0001",
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
        "patrimonio": "IMP-0001",
        "modelo": "HP LaserJet",
        "impressora": {"tipo_impressao": "laser", "colorida": False, "contador_paginas": 1000},
    }
    res = client.post("/api/v1/ativos", json=payload, headers=auth_headers)
    assert res.status_code == 201, res.text
    assert res.json()["impressora"]["contador_paginas"] == 1000


def test_list_ativos(client, auth_headers):
    client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": "TI-100"}, headers=auth_headers)
    res = client.get("/api/v1/ativos", params={"dominio": "ti"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["total"] == 1


def test_patrimonio_duplicado(client, auth_headers):
    payload = {"dominio": "ti", "patrimonio": "TI-DUP"}
    assert client.post("/api/v1/ativos", json=payload, headers=auth_headers).status_code == 201
    assert client.post("/api/v1/ativos", json=payload, headers=auth_headers).status_code == 409


def test_change_status(client, auth_headers):
    ativo_id = client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": "TI-S"}, headers=auth_headers).json()["id"]
    res = client.patch(f"/api/v1/ativos/{ativo_id}/status", json={"status": "em_uso"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "em_uso"


def test_atribuir_gera_termo(client, auth_headers):
    ativo_id = client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": "TI-A", "modelo": "Notebook"}, headers=auth_headers).json()["id"]
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
