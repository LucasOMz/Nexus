"""Datas da API precisam sair COM FUSO.

O banco grava `func.now()` sem fuso, e o valor é UTC. Quando a API devolvia
`2026-10-06T00:12:04` (sem fuso), o navegador interpretava como hora LOCAL e a
tela mostrava 3 horas à frente do relógio da máquina (horário de Brasília).

A correção envia `+00:00`, e o navegador converte para a hora do equipamento.
"""
from __future__ import annotations

import re

# Um datetime sem fuso: "2026-10-06T00:12:04" ou "...T00:12:04.123456"
SEM_FUSO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$")
# Data pura (sem hora) — garantia, aquisição. NÃO deve ganhar fuso.
SO_DATA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _tem_fuso(valor: str) -> bool:
    return bool(re.search(r"(Z|[+-]\d{2}:?\d{2})$", valor))


def test_created_at_do_ativo_tem_fuso(client, auth_headers):
    r = client.post(
        "/api/v1/ativos",
        json={"dominio": "ti", "patrimonio": "TZ-0001", "numero_serie": "NS-TZ-0001", "tipo_item": "ativo"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    criado = r.json()["created_at"]
    assert not SEM_FUSO.match(criado), f"created_at saiu SEM fuso: {criado}"
    assert _tem_fuso(criado), criado


def test_manutencao_tem_fuso(client, auth_headers):
    ativo = client.post(
        "/api/v1/ativos",
        json={"dominio": "ti", "patrimonio": "TZ-0002", "numero_serie": "NS-TZ-0002", "tipo_item": "ativo"},
        headers=auth_headers,
    ).json()
    m = client.post(
        "/api/v1/manutencoes",
        json={"ativo_id": ativo["id"], "descricao": "Teste de fuso"},
        headers=auth_headers,
    ).json()

    assert _tem_fuso(m["data_abertura"]), m["data_abertura"]

    concluida = client.patch(
        f"/api/v1/manutencoes/{m['id']}",
        json={"status": "concluida", "comentario_conclusao": "Feito"},
        headers=auth_headers,
    ).json()
    assert _tem_fuso(concluida["data_conclusao"]), concluida["data_conclusao"]


def test_movimentacao_e_auditoria_tem_fuso(client, auth_headers):
    movs = client.get("/api/v1/movimentacoes", params={"size": 1}, headers=auth_headers).json()
    itens = movs["items"] if isinstance(movs, dict) else movs
    for m in itens:
        assert _tem_fuso(m["data_mov"]), m["data_mov"]

    logs = client.get("/api/v1/admin/auditoria", params={"por_pagina": 1}, headers=auth_headers).json()["itens"]
    for log in logs:
        assert _tem_fuso(log["criado_em"]), log["criado_em"]


def test_cadastros_com_data_tambem_tem_fuso(client, auth_headers):
    dep = client.post("/api/v1/departamentos", json={"nome": "Fuso"}, headers=auth_headers).json()
    assert _tem_fuso(dep["created_at"]), dep["created_at"]


def test_data_pura_nao_ganha_fuso(client, auth_headers):
    """Garantia é uma DATA, não um instante — não pode virar '2026-10-05T00:00:00Z'."""
    r = client.post(
        "/api/v1/ativos",
        json={
            "dominio": "ti", "patrimonio": "TZ-0003", "numero_serie": "NS-TZ-0003", "tipo_item": "ativo",
            "data_garantia": "2027-03-15", "data_aquisicao": "2025-01-10",
        },
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert SO_DATA.match(corpo["data_garantia"]), corpo["data_garantia"]
    assert SO_DATA.match(corpo["data_aquisicao"]), corpo["data_aquisicao"]


def test_o_fuso_enviado_e_utc(client, auth_headers):
    """O valor marcado precisa ser UTC — é assim que o banco grava."""
    r = client.post(
        "/api/v1/ativos",
        json={"dominio": "ti", "patrimonio": "TZ-0004", "numero_serie": "NS-TZ-0004", "tipo_item": "ativo"},
        headers=auth_headers,
    ).json()
    assert r["created_at"].endswith("+00:00")
