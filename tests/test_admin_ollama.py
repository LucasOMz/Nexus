import httpx

from app.config import settings
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import create_access_token
from app.models import Usuario
from app.routers import ia
from app.services import ollama
from tests.conftest import TestingSession

ROTA = "/api/v1/admin/config/ollama"


def test_administracao_lista_salva_e_aplica_modelo_no_chat(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "nexus_ollama_url", "http://ollama-original:11434")
    monkeypatch.setattr(settings, "nexus_ollama_modelo", "qwen3:32b")
    monkeypatch.setattr(ia, "_limite_chat", SlidingWindowLimiter(8, 60))
    chamadas = []

    def simular_ollama(req):
        chamadas.append((req.method, str(req.url), req.headers["host"], req.content))
        if req.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": "qwen3:32b"}, {"model": "modelo-teste:8b"}, {"name": "qwen3:32b"},
            ]})
        return httpx.Response(200, json={"message": {"content": "", "tool_calls": [
            {"function": {"name": "consultar_inventario", "arguments": {"operacao": "contar"}}},
        ]}})

    solicitar = ollama.DestinoOllama.solicitar

    def enviar(destino, _, *args, **kwargs):
        with httpx.Client(transport=httpx.MockTransport(simular_ollama)) as sessao:
            return solicitar(destino, sessao, *args, **kwargs)

    monkeypatch.setattr(ollama.DestinoOllama, "solicitar", enviar)
    monkeypatch.setattr(ollama, "getaddrinfo", lambda *args, **kwargs: [
        (2, 1, 6, "", ("192.168.7.50", 11434)),
    ])

    inicial = client.get(ROTA, headers=auth_headers)
    assert inicial.json()["origem"] == "ambiente"
    endereco = {"url": "http://ollama.interno:11434/"}
    teste = client.post(ROTA + "/testar", headers=auth_headers, json=endereco)
    assert teste.status_code == 200, teste.text
    assert teste.json() == {"modelos": ["modelo-teste:8b", "qwen3:32b"]}
    assert chamadas[0][:3] == ("GET", "http://192.168.7.50:11434/api/tags", "ollama.interno:11434")
    assert client.get(ROTA, headers=auth_headers).json() == inicial.json()

    dados = {**endereco, "modelo": "modelo-teste:8b"}
    salvo = client.put(ROTA, headers=auth_headers, json=dados)
    assert salvo.status_code == 200, salvo.text
    assert client.get(ROTA, headers=auth_headers).json() == {
        "url": "http://ollama.interno:11434", "modelo": dados["modelo"], "origem": "administracao",
    }
    invalido = client.put(ROTA, headers=auth_headers, json={**dados, "modelo": "ausente"})
    assert invalido.status_code == 422
    assert client.get(ROTA, headers=auth_headers).json() == salvo.json()

    chat = client.post("/api/v1/ia/chat", headers=auth_headers, json={"pergunta": "Quantos equipamentos?"})
    assert chat.status_code == 200, chat.text
    assert chat.json()["resultados"][0]["total"] == 0
    assert chamadas[-1][:3] == ("POST", "http://192.168.7.50:11434/api/chat", "ollama.interno:11434")
    assert b'"model":"modelo-teste:8b"' in chamadas[-1][3]


def test_configuracao_ollama_exige_admin(client):
    with TestingSession() as db:
        db.add(Usuario(id=2, nome="TI", email="ti@teste.com", senha_hash="indisponivel", papel="ti", planta_id=1))
        db.commit()
    headers = {"Authorization": f"Bearer {create_access_token(2, 'ti')}"}
    dados = {"url": "http://192.168.7.50:11434", "modelo": "qwen3:32b"}
    assert client.get(ROTA, headers=headers).status_code == 403
    assert client.put(ROTA, headers=headers, json=dados).status_code == 403
    assert client.post(ROTA + "/testar", headers=headers, json={"url": dados["url"]}).status_code == 403


def test_teste_ollama_recusa_endereco_invalido(client, auth_headers):
    for url in ("http://169.254.169.254", "http://127.0.0.1:11434", "http://u:p@192.168.7.50:11434"):
        resposta = client.post(ROTA + "/testar", headers=auth_headers, json={"url": url})
        assert resposta.status_code == 422, resposta.text
