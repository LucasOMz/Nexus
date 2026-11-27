import json

import httpx
import pytest

from app.config import settings
from app.core.cripto import decifrar, esta_cifrado
from app.models.core import ConfiguracaoSistema
from app.services.ia_externa import DestinoExterno
from tests.conftest import TestingSession

ROTA = "/api/v1/admin/config/agente-ia"


@pytest.mark.parametrize(("provedor", "url"), [
    ("openai", "https://api.openai.com/v1/chat/completions"),
    ("openrouter", "https://openrouter.ai/api/v1/chat/completions"),
])
def test_provedor_externo_testa_cifra_e_responde_com_ferramentas(client, auth_headers, monkeypatch, provedor, url):
    monkeypatch.setattr(settings, "nexus_ollama_url", "")
    token = "chave-de-teste"
    requisicoes = []

    def simular(req):
        assert str(req.url) == url
        assert req.headers["Authorization"] == f"Bearer {token}"
        payload = json.loads(req.content)
        requisicoes.append(payload)
        nome = "confirmar_conexao" if "tool_choice" in payload else "consultar_inventario"
        args = {} if nome == "confirmar_conexao" else {"operacao": "contar"}
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
            {"function": {"name": nome, "arguments": json.dumps(args)}},
        ]}}]})

    perguntar = DestinoExterno.perguntar

    def com_transporte(destino, _, *args, **kwargs):
        with httpx.Client(transport=httpx.MockTransport(simular)) as sessao:
            return perguntar(destino, sessao, *args, **kwargs)

    monkeypatch.setattr(DestinoExterno, "perguntar", com_transporte)
    dados = {"provedor": provedor, "modelo": "modelo-teste", "token": token}
    assert client.get(ROTA, headers=auth_headers).json()["provedor"] == "ollama"
    assert client.post(ROTA + "/externa/testar", headers=auth_headers, json=dados).status_code == 200
    assert client.get(ROTA, headers=auth_headers).json()["provedor"] == "ollama"
    salvo = client.put(ROTA + "/externa", headers=auth_headers, json=dados)
    assert salvo.status_code == 200, salvo.text
    assert salvo.json() == {"provedor": provedor, "provedor_externo": provedor,
                            "modelo_externo": "modelo-teste", "token_salvo": True}
    with TestingSession() as db:
        cifrado = db.get(ConfiguracaoSistema, 1).ia_token_externo
        assert esta_cifrado(cifrado) and decifrar(cifrado) == token
    chat = client.post("/api/v1/ia/chat", headers=auth_headers, json={"pergunta": "Quantos equipamentos?"})
    assert chat.status_code == 200, chat.text
    assert chat.json()["resultados"][0]["total"] == 0
    assert requisicoes[-1]["model"] == "modelo-teste"
    assert "Quantos equipamentos?" in requisicoes[-1]["messages"][-1]["content"]
    assert client.put(ROTA, headers=auth_headers, json={"provedor": "ollama"}).json()["token_salvo"] is True
    assert client.delete(ROTA + "/externa", headers=auth_headers).json()["token_salvo"] is False
