"""Testes do scanner (leitor físico / digitação manual) e do dashboard.

A resposta de `/scanner/buscar` é um envelope: `{tipo, ativo, zerado}`.
`tipo="ativo"` quando achou o equipamento; `tipo="zerado"` quando o QR lido é
uma etiqueta em branco ainda sem dono (aí `ativo` vem nulo).
"""
from __future__ import annotations


def _criar_ativo(client, auth_headers, patrimonio="TIAT0001", modelo="Latitude"):
    return client.post(
        "/api/v1/ativos",
        json={"dominio": "ti", "patrimonio": patrimonio, "modelo": modelo, "numero_serie": f"SN-{patrimonio}"},
        headers=auth_headers,
    ).json()["id"]


def test_buscar_por_patrimonio(client, auth_headers):
    ativo_id = _criar_ativo(client, auth_headers)
    res = client.post("/api/v1/scanner/buscar", json={"codigo": "TIAT0001"}, headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tipo"] == "ativo"
    assert body["ativo"]["id"] == ativo_id
    assert body["ativo"]["origem"] == "patrimonio"
    assert body["zerado"] is None


def test_buscar_por_numero_de_serie(client, auth_headers):
    _criar_ativo(client, auth_headers)
    res = client.post("/api/v1/scanner/buscar", json={"codigo": "SN-TIAT0001"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["ativo"]["origem"] in ("patrimonio", "serie")


def test_buscar_por_payload_qr(client, auth_headers):
    ativo_id = _criar_ativo(client, auth_headers)
    payload = client.post(f"/api/v1/qrcode/generate/{ativo_id}", headers=auth_headers).json()["qr_payload"]
    res = client.post("/api/v1/scanner/buscar", json={"codigo": payload}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["ativo"]["origem"] == "qr"


def test_buscar_codigo_inexistente(client, auth_headers):
    res = client.post("/api/v1/scanner/buscar", json={"codigo": "NAO-EXISTE"}, headers=auth_headers)
    assert res.status_code == 404


def test_dashboard_stats(client, auth_headers):
    _criar_ativo(client, auth_headers)
    res = client.get("/api/v1/dashboard/stats", params={"dominio": "ti"}, headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert "por_status" in body and "garantias" in body


def test_graficos(client, auth_headers):
    _criar_ativo(client, auth_headers)
    res = client.get("/api/v1/relatorios/graficos", params={"dominio": "ti"}, headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    for chave in ("status", "categoria", "garantias", "movimentacoes_mes", "manutencoes_status"):
        assert chave in body
