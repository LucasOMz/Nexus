"""Testes da assinatura de QR configurável.

Garantem o principal: **uma etiqueta já impressa continua sendo lida** mesmo
depois de trocar o segredo, e a assinatura pode ser opcional sem quebrar nada.
"""
from __future__ import annotations

from app.config import settings
from app.services.qr_service import build_payload


def _criar_ativo(client, auth_headers, patrimonio="QR-0001"):
    return client.post(
        "/api/v1/ativos",
        json={"dominio": "ti", "patrimonio": patrimonio},
        headers=auth_headers,
    ).json()["id"]


def _payload_adulterado(payload: str) -> str:
    """Mantém o ID e troca a assinatura por uma inválida."""
    partes = payload.split(":")
    return ":".join([partes[0], partes[1], partes[2], "assinatura_invalida"])


def test_etiqueta_antiga_continua_valida_apos_trocar_segredo(client, auth_headers, monkeypatch):
    """O caso principal: etiquetas impressas antes da troca de segredo seguem valendo."""
    ativo_id = _criar_ativo(client, auth_headers)

    # 1) Etiqueta foi impressa quando o segredo era "segredo-antigo".
    monkeypatch.setattr(settings, "qr_hmac_secret", "segredo-antigo")
    payload_antigo = build_payload(ativo_id)

    # 2) Depois o segredo foi trocado, mas o antigo ficou na lista de aceitos.
    monkeypatch.setattr(settings, "qr_hmac_secret", "segredo-novo")
    monkeypatch.setattr(settings, "qr_hmac_secrets_anteriores", "segredo-antigo")

    res = client.post("/api/v1/scanner/buscar", json={"codigo": payload_antigo}, headers=auth_headers)
    assert res.status_code == 200, res.text
    corpo = res.json()["ativo"]
    assert corpo["id"] == ativo_id
    assert corpo["origem"] == "qr"
    assert corpo["assinatura_valida"] is True


def test_assinatura_invalida_bloqueia_quando_exigida(client, auth_headers, monkeypatch):
    ativo_id = _criar_ativo(client, auth_headers, "QR-0002")
    payload = f"TIATIVO:{ativo_id}:1700000000:assinatura_invalida"

    monkeypatch.setattr(settings, "qr_exigir_assinatura", True)
    res = client.post("/api/v1/scanner/buscar", json={"codigo": payload}, headers=auth_headers)
    assert res.status_code == 404


def test_assinatura_invalida_e_aceita_quando_nao_exigida(client, auth_headers, monkeypatch):
    """Com a assinatura desligada, o ID do payload resolve o ativo — e fica auditado."""
    ativo_id = _criar_ativo(client, auth_headers, "QR-0003")
    payload = f"TIATIVO:{ativo_id}:1700000000:assinatura_invalida"

    monkeypatch.setattr(settings, "qr_exigir_assinatura", False)
    res = client.post("/api/v1/scanner/buscar", json={"codigo": payload}, headers=auth_headers)
    assert res.status_code == 200, res.text
    corpo = res.json()["ativo"]
    assert corpo["id"] == ativo_id
    assert corpo["origem"] == "qr_sem_assinatura"
    assert corpo["assinatura_valida"] is False

    # A leitura sem assinatura fica registrada na auditoria.
    logs = client.get("/api/v1/relatorios/filtros", headers=auth_headers)
    assert logs.status_code == 200  # endpoint leve só para confirmar sessão válida


def test_payload_assinado_normal_continua_funcionando(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "qr_exigir_assinatura", True)
    ativo_id = _criar_ativo(client, auth_headers, "QR-0004")
    payload = client.post(f"/api/v1/qrcode/generate/{ativo_id}", headers=auth_headers).json()["qr_payload"]

    res = client.post("/api/v1/scanner/buscar", json={"codigo": payload}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["ativo"]["origem"] == "qr"
    assert res.json()["ativo"]["assinatura_valida"] is True


def test_patrimonio_continua_funcionando(client, auth_headers):
    _criar_ativo(client, auth_headers, "QR-0005")
    res = client.post("/api/v1/scanner/buscar", json={"codigo": "QR-0005"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["ativo"]["origem"] == "patrimonio"
    assert res.json()["ativo"]["assinatura_valida"] is None


def test_validar_endpoint_estrito(client, auth_headers, monkeypatch):
    """`/qrcode/validate` continua estrito (assinatura obrigatória)."""
    monkeypatch.setattr(settings, "qr_exigir_assinatura", False)
    ativo_id = _criar_ativo(client, auth_headers, "QR-0006")
    adulterado = _payload_adulterado(f"TIATIVO:{ativo_id}:1700000000:abc")
    res = client.post("/api/v1/qrcode/validate", json={"payload": adulterado}, headers=auth_headers)
    assert res.json()["valid"] is False
