"""Testes de QR Code com assinatura HMAC-SHA256."""
from __future__ import annotations


def test_generate_and_validate(client, auth_headers):
    ativo_id = client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": "TI-QR"}, headers=auth_headers).json()["id"]
    gen = client.post(f"/api/v1/qrcode/generate/{ativo_id}", headers=auth_headers)
    assert gen.status_code == 200
    payload = gen.json()["qr_payload"]
    assert payload.startswith("TIATIVO:")

    val = client.post("/api/v1/qrcode/validate", json={"payload": payload}, headers=auth_headers)
    assert val.status_code == 200
    body = val.json()
    assert body["valid"] is True
    assert body["ativo_id"] == ativo_id


def test_validate_invalid(client, auth_headers):
    val = client.post("/api/v1/qrcode/validate", json={"payload": "lixo"}, headers=auth_headers)
    assert val.json()["valid"] is False


def test_validate_tampered_hmac(client, auth_headers):
    ativo_id = client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": "TI-QR2"}, headers=auth_headers).json()["id"]
    payload = client.post(f"/api/v1/qrcode/generate/{ativo_id}", headers=auth_headers).json()["qr_payload"]
    # Altera o id mantendo a assinatura original → HMAC deve falhar.
    tampered = payload.replace(f":{ativo_id}:", ":9999:", 1)
    val = client.post("/api/v1/qrcode/validate", json={"payload": tampered}, headers=auth_headers)
    assert val.json()["valid"] is False
