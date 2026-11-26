from uuid import uuid4

import pytest

from app.config import settings
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import create_access_token
from app.models import Ativo, ChatInventarioMensagem, Departamento, Planta, PlantaLocalidade, Usuario
from app.models.ti import AtivoTI
from app.routers import ia
from tests.conftest import TestingSession

@pytest.fixture
def inventario_ia(client, monkeypatch):
    monkeypatch.setattr(settings, "nexus_ollama_url", "http://ollama:11434")
    monkeypatch.setattr(ia, "_limite_chat", SlidingWindowLimiter(8, 60))
    with TestingSession() as db:
        db.add(Planta(id=2, nome="Filial", sigla="FIL", ativa=True))
        db.add(Departamento(id=1, nome="Operações", planta_id=1))
        db.add_all([
            Usuario(id=2, nome="Leitor", email="leitor@teste.com", senha_hash="indisponivel",
                    papel="leitor", planta_id=1, permissoes={"inventarios": ["ti"], "modulos": ["ativos"]}),
            Usuario(id=3, nome="Leitor sem ativos", email="restrito@teste.com", senha_hash="indisponivel",
                    papel="leitor", planta_id=1, permissoes={"inventarios": ["ti"], "modulos": ["mapa"]}),
        ])
        db.flush()
        for i, planta, hostname, patrimonio in [
            (1, 1, "DTAT0001", None), (2, 1, "NTAT0002", "PT-2"), (3, 2, "DMTZ0003", None),
        ]:
            db.add(Ativo(id=i, planta_id=planta, departamento_id=1 if planta == 1 else None,
                         numero_serie=f"QA-{i}", patrimonio=patrimonio, dominio="ti"))
            db.flush()
            db.add(AtivoTI(ativo_id=i, hostname=hostname))
        db.add(Ativo(id=4, planta_id=1, numero_serie="QA-4", dominio="impressora"))
        db.commit()


def _filtro(campo, operador, valor=None):
    return {"campo": campo, "operador": operador, "valor": valor}


def _modelo(monkeypatch, consultas):
    recebidas = []

    def perguntar(client, destino, mensagens, prazo, *, modelo, ferramentas):
        recebidas.append((str(destino.url), mensagens[-1]["content"]))
        if not ferramentas:
            return {"content": "Resultados do inventário."}
        return {"tool_calls": [
            {"function": {"name": "consultar_inventario", "arguments": consulta}} for consulta in consultas
        ]}

    monkeypatch.setattr(ia, "_perguntar", perguntar)
    return recebidas


def test_chat_percentual_por_departamento_e_detalhes(client, auth_headers, inventario_ia, monkeypatch):
    recebidas = _modelo(monkeypatch, [{
        "operacao": "percentual",
        "filtros": [_filtro("tipo_equipamento", "igual", "computador")],
        "filtros_numerador": [_filtro("patrimonio", "vazio")],
        "agrupar_por": ["departamento"],
    }])
    headers = {**auth_headers, "X-Planta-Id": "1"}
    resposta = client.post("/api/v1/ia/chat", headers=headers, json={
        "pergunta": "E qual o percentual por departamento?",
        "historico": ["Quantos computadores estão sem patrimônio?"],
    })
    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()["resultados"][0]
    assert (dados["total"], dados["correspondentes"], dados["percentual"]) == (2, 1, 50)
    assert dados["grupos"] == [{"valores": ["Operações"], "total": 2, "correspondentes": 1, "percentual": 50}]
    assert recebidas[0][0] == "http://ollama:11434"
    assert "Quantos computadores" in recebidas[0][1]
    lista = client.post("/api/v1/ia/equipamentos", headers=headers, json=dados["consulta"]).json()
    assert [ativo["hostname"] for ativo in lista["equipamentos"]] == ["DTAT0001"]


def test_chat_isola_planta_inventario_e_detalhes(client, inventario_ia, monkeypatch):
    recebidas = _modelo(monkeypatch, [{"operacao": "listar"}])
    headers = {"Authorization": f"Bearer {create_access_token(2, 'leitor')}", "X-Planta-Id": "2"}
    resposta = client.post("/api/v1/ia/chat", headers=headers, json={"pergunta": "Liste todos os equipamentos"})
    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()["resultados"][0]
    assert dados["total"] == 2
    assert [ativo["hostname"] for ativo in dados["equipamentos"]] == ["DTAT0001", "NTAT0002"]
    assert "DTAT0001" not in recebidas[1][1]
    sem_modulo = {"Authorization": f"Bearer {create_access_token(3, 'leitor')}"}
    assert client.post("/api/v1/ia/equipamentos", headers=sem_modulo, json={"operacao": "listar"}).status_code == 403


def test_web_chat_rejeita_campos_fora_do_inventario(client, auth_headers, inventario_ia, monkeypatch):
    recebidas = _modelo(monkeypatch, [{"operacao": "listar", "filtros": [_filtro("email", "preenchido")]}])
    resposta = client.post("/api/v1/ia/chat", headers=auth_headers, json={"pergunta": "Liste os e-mails"})
    assert resposta.status_code == 200
    assert resposta.json()["resultados"] == []
    assert len(recebidas) == 1


def test_chat_informa_quando_ollama_nao_configurado(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "nexus_ollama_url", "")
    resposta = client.post("/api/v1/ia/chat", headers=auth_headers, json={"pergunta": "Quantos computadores?"})
    assert resposta.status_code == 503
    assert "não está configurado" in resposta.json()["detail"]


@pytest.mark.parametrize("planta_pedida", ["Tatui", "TATUÍ", "TAT", "UTU"])
def test_chat_encontra_computador_em_tatui(client, auth_headers, inventario_ia, monkeypatch, planta_pedida):
    with TestingSession() as db:
        planta = db.get(Planta, 2)
        planta.nome = "Unidade Tatuí"
        planta.sigla = "UTU"
        planta.cidade = "Tatuí"
        db.add(PlantaLocalidade(planta_id=2, codigo="TAT"))
        computador = db.get(AtivoTI, 3)
        computador.hostname = "PC-LEGADO"
        computador.so = "Windows 11 Pro"
        db.commit()

    recebidas = _modelo(monkeypatch, [{
        "operacao": "contar",
        "filtros": [_filtro("planta", "igual", planta_pedida), _filtro("tipo_equipamento", "igual", "computador")],
    }])
    resposta = client.post("/api/v1/ia/chat", headers=auth_headers, json={"pergunta": "Quantos computadores tenho na planta de Tatui?"})
    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()
    assert dados["resposta"] == "Encontrei 1 equipamento."
    assert dados["resultados"][0]["total"] == 1
    assert len(recebidas) == 1
    lista = client.post("/api/v1/ia/equipamentos", headers=auth_headers, json=dados["resultados"][0]["consulta"]).json()
    assert [ativo["hostname"] for ativo in lista["equipamentos"]] == ["PC-LEGADO"]


def test_chat_explicita_planta_fora_do_escopo_em_vez_de_zero(client, auth_headers, inventario_ia, monkeypatch):
    _modelo(monkeypatch, [{"operacao": "contar", "filtros": [_filtro("planta", "igual", "Filial")]}])
    resposta = client.post("/api/v1/ia/chat", headers={**auth_headers, "X-Planta-Id": "1"},
                           json={"pergunta": "Quantos ativos tenho na Filial?"})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["resultados"] == []
    assert "escopo atual" in resposta.json()["resposta"]


def test_chat_salva_e_retoma_conversa_no_mesmo_escopo(client, auth_headers, inventario_ia, monkeypatch):
    recebidas = _modelo(monkeypatch, [{"operacao": "contar"}])
    headers = {**auth_headers, "X-Planta-Id": "1"}
    pergunta = "Quantos equipamentos?"
    primeira = client.post("/api/v1/ia/chat", headers=headers, json={"pergunta": pergunta})
    assert primeira.status_code == 200, primeira.text
    conversa_id = primeira.json()["conversa_id"]
    rota = f"/api/v1/ia/conversas/{conversa_id}"

    listagem = client.get("/api/v1/ia/conversas", headers=headers)
    assert listagem.status_code == 200, listagem.text
    assert listagem.headers["Cache-Control"] == "no-store"
    assert [(item["id"], item["titulo"]) for item in listagem.json()["conversas"]] == [(conversa_id, pergunta)]
    segunda = client.post("/api/v1/ia/chat", headers=headers, json={
        "pergunta": "E só os notebooks?", "conversa_id": conversa_id, "historico": ["Contexto incorreto"],
    })
    assert segunda.status_code == 200, segunda.text
    assert segunda.json()["conversa_id"] == conversa_id
    assert pergunta in recebidas[1][1]
    assert "Contexto incorreto" not in recebidas[1][1]

    historico = client.get(rota, headers=headers).json()["mensagens"]
    assert [(m["pergunta"], m["resultados"][0]["total"]) for m in historico] == [
        (pergunta, 3), ("E só os notebooks?", 3),
    ]
    for outros_headers in (
        {**auth_headers, "X-Planta-Id": "2"},
        {"Authorization": f"Bearer {create_access_token(2, 'leitor')}", "X-Planta-Id": "1"},
    ):
        assert client.get("/api/v1/ia/conversas", headers=outros_headers).json()["conversas"] == []
        assert client.get(rota, headers=outros_headers).status_code == 404
        assert client.post("/api/v1/ia/chat", headers=outros_headers, json={
            "pergunta": "Continuar", "conversa_id": conversa_id,
        }).status_code == 404


def test_chat_pagina_conversas_e_mensagens(client, auth_headers, inventario_ia):
    conversa_principal = uuid4()
    with TestingSession() as db:
        for i in range(22):
            for conversa_id in (uuid4(), conversa_principal):
                db.add(ChatInventarioMensagem(conversa_id=conversa_id, usuario_id=1, planta_id=1,
                                              inventarios="impressora,ti", pergunta=f"Pergunta {i}",
                                              resposta="Resposta", resultados=[]))
        db.commit()
    headers = {**auth_headers, "X-Planta-Id": "1"}
    rota = "/api/v1/ia/conversas"
    primeira = client.get(rota, headers=headers).json()
    assert len(primeira["conversas"]) == 20
    segunda = client.get(rota, headers=headers, params={"antes_de": primeira["proximo"]}).json()
    assert len(segunda["conversas"]) == 3
    assert {c["id"] for c in primeira["conversas"]}.isdisjoint(c["id"] for c in segunda["conversas"])

    rota += f"/{conversa_principal}"
    primeira = client.get(rota, headers=headers).json()
    assert [m["pergunta"] for m in primeira["mensagens"]] == [f"Pergunta {i}" for i in range(2, 22)]
    segunda = client.get(rota, headers=headers, params={"antes_de": primeira["proximo"]}).json()
    assert [m["pergunta"] for m in segunda["mensagens"]] == ["Pergunta 0", "Pergunta 1"]
