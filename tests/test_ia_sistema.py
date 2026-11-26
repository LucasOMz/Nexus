import pytest

from app.config import settings
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import create_access_token
from app.models import Ativo, AtivoImpressora, AtivoTI, LeituraContador, Manutencao, Movimentacao
from app.models import Planta, Produto, SuprimentoImpressora, Usuario
from app.routers import ia, monitor_impressoras
from tests.conftest import TestingSession


@pytest.fixture
def sistema_ia(client, monkeypatch):
    monkeypatch.setattr(settings, "nexus_ollama_url", "http://ollama:11434")
    monkeypatch.setattr(ia, "_limite_chat", SlidingWindowLimiter(8, 60))
    with TestingSession() as db:
        db.add(Planta(id=2, nome="Tatuí", sigla="TAT"))
        db.add(Usuario(id=2, nome="Operador", email="operador@teste.com", senha_hash="fake", papel="leitor",
                       planta_id=1, permissoes={"inventarios": ["impressora"], "modulos": ["produtos", "monitor"]}))
        db.flush()
        db.add_all([
            Ativo(id=1, planta_id=1, dominio="impressora", patrimonio="IMP-1", numero_serie="S-1"),
            Ativo(id=2, planta_id=2, dominio="impressora", patrimonio="IMP-2", numero_serie="S-2"),
            Ativo(id=3, planta_id=1, dominio="ti", patrimonio="TI-1", numero_serie="S-3"),
            Produto(id=1, sku="TON-50", nome="Toner preto", dominio="impressora", estoque_minimo=4),
            Produto(id=2, sku="CABO-1", nome="Cabo de rede", dominio="ti"),
        ])
        db.flush()
        db.add_all([
            AtivoImpressora(ativo_id=1, ip="192.168.40.10", contador_paginas=3100),
            LeituraContador(ativo_id=1, contador=3501),
            SuprimentoImpressora(ativo_id=1, tipo="toner", modelo="T50", cor="Preto", estoque_atual=3),
            AtivoTI(ativo_id=3, ram_gb=32, inventario_json='{"discos":[{"modelo":"SSD teste","gb":512}]}'),
            Movimentacao(produto_id=1, tipo="entrada", quantidade=10),
            Movimentacao(produto_id=1, tipo="saida", quantidade=7),
            Manutencao(ativo_id=1, status="aberta", descricao="Teste"),
            Manutencao(ativo_id=2, status="aberta", descricao="Outra planta"),
        ])
        db.commit()


def _perguntar(client, monkeypatch, headers, nome, **argumentos):
    def modelo(*args, **kwargs):
        return {"tool_calls": [{"function": {"name": nome, "arguments": argumentos}}]}
    monkeypatch.setattr(ia, "_perguntar", modelo)
    resposta = client.post("/api/v1/ia/chat", headers=headers, json={"pergunta": "Pergunta de teste"})
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def test_ia_orienta_e_linka_telas_conforme_permissao(client, auth_headers, sistema_ia, monkeypatch):
    dados = _perguntar(client, monkeypatch, auth_headers, "orientar_nexus", telas=["admin_usuarios", "mapa"])
    assert [link["rota"] for link in dados["resultados"][0]["links"]] == ["#/admin?aba=usuarios", "#/mapa"]
    assert "MFA" in str(dados["resultados"][0]["blocos"])

    headers = {"Authorization": f"Bearer {create_access_token(2, 'leitor')}"}
    dados = _perguntar(client, monkeypatch, headers, "orientar_nexus", telas=["admin_usuarios", "produtos"])
    assert [link["rota"] for link in dados["resultados"][0]["links"]] == ["#/produtos"]
    assert "MFA" not in str(dados["resultados"][0])


def test_ia_fichas_detalhadas_respeitam_planta_e_inventario(client, auth_headers, sistema_ia, monkeypatch):
    headers = {**auth_headers, "X-Planta-Id": "1"}
    dados = _perguntar(client, monkeypatch, headers, "consultar_ficha_ativo", identificador="IMP-1", assunto="completa")
    resultado = dados["resultados"][0]
    assert 3501 in dict(next(b for b in resultado["blocos"] if b["titulo"] == "Impressão e contador")["linhas"]).values()
    assert "T50" in str(resultado["blocos"])
    assert resultado["links"][0]["rota"] == "#/ativos?busca=S-1&destaque=1"
    dados = _perguntar(client, monkeypatch, headers, "consultar_ficha_ativo", identificador="IMP-2")
    assert "Não encontrei" in dados["resposta"]

    dados = _perguntar(client, monkeypatch, headers, "consultar_ficha_ativo", identificador="S-3", assunto="hardware")
    assert "SSD teste" in str(dados["resultados"])
    assert ["RAM (GB)", 32] in dados["resultados"][0]["blocos"][0]["linhas"]


def test_ia_monitor_e_estoque_reusam_escopo(client, auth_headers, sistema_ia, monkeypatch):
    monkeypatch.setattr(monitor_impressoras, "situacao_da_impressora", lambda *args, **kwargs: {
        "comunicacao": "online", "verificado_em": "2026-11-26", "suprimentos": [{"descricao": "Preto", "percentual": 18}],
    })
    dados = _perguntar(client, monkeypatch, auth_headers, "consultar_ficha_ativo", identificador="IMP-1", assunto="comunicacao")
    assert ["Preto", "18%"] in dados["resultados"][0]["blocos"][0]["linhas"]
    dados = _perguntar(client, monkeypatch, auth_headers, "consultar_consumiveis", termo="TON-50", operacao="estoque")
    assert ["Saldo consolidado", "3 un"] in dados["resultados"][0]["blocos"][0]["linhas"]
    assert dados["resultados"][0]["links"][0]["rota"] == "#/produtos?busca=TON-50"
    dados = _perguntar(client, monkeypatch, {**auth_headers, "X-Planta-Id": "1"},
                       "consultar_consumiveis", termo="TON-50", operacao="estoque")
    assert "saldo por planta não está disponível" in dados["resposta"]

    headers = {"Authorization": f"Bearer {create_access_token(2, 'leitor')}"}
    dados = _perguntar(client, monkeypatch, headers, "consultar_consumiveis", termo="CABO-1")
    assert dados["resultados"][0]["blocos"] == []


def test_ia_indicadores_e_historico_reaplicam_permissoes(client, auth_headers, sistema_ia, monkeypatch):
    dados = _perguntar(client, monkeypatch, {**auth_headers, "X-Planta-Id": "1"},
                       "consultar_indicador", indicador="manutencoes_abertas")
    assert dados["resposta"].endswith("1.")
    assert dados["resultados"][0]["links"][0]["rota"] == "#/manutencoes"

    headers = {"Authorization": f"Bearer {create_access_token(2, 'leitor')}"}
    dados = _perguntar(client, monkeypatch, headers, "consultar_consumiveis", termo="TON-50")
    assert dados["resultados"][0]["blocos"]
    with TestingSession() as db:
        db.get(Usuario, 2).permissoes = {"inventarios": ["impressora"], "modulos": ["monitor"]}
        db.commit()
    conversa = client.get(f"/api/v1/ia/conversas/{dados['conversa_id']}", headers=headers).json()
    assert conversa["mensagens"][0]["resultados"] == []
    assert "não tem mais acesso" in conversa["mensagens"][0]["resposta"]
