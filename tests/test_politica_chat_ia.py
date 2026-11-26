from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.config import settings
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import create_access_token
from app.models import ChatInventarioMensagem, ConfiguracaoSistema, Usuario
from app.routers import ia
from app.services.retencao_chat import executar_retencao
from tests.conftest import TestingSession

POLITICA = "/api/v1/admin/config/ollama/politica"
CHAT = "/api/v1/ia"


@pytest.fixture
def outro_usuario(client, monkeypatch):
    monkeypatch.setattr(settings, "nexus_ollama_url", "http://ollama:11434")
    monkeypatch.setattr(ia, "_limite_chat", SlidingWindowLimiter(8, 60))
    with TestingSession() as db:
        db.add(Usuario(id=2, nome="Operador", email="operador@teste.com", senha_hash="fake", papel="ti", planta_id=1))
        db.commit()
    return {"Authorization": f"Bearer {create_access_token(2, 'ti')}"}


def test_politica_global_e_permissao_individual_bloqueiam_chat_e_historico(client, auth_headers, outro_usuario, monkeypatch):
    def falhar_se_chamado(*args, **kwargs):
        pytest.fail("Conta bloqueada não deve acessar o Ollama")

    monkeypatch.setattr(ia, "_perguntar", falhar_se_chamado)
    assert client.get(POLITICA, headers=auth_headers).json() == {"chat_ativo": True, "historico_dias": None}
    assert client.get(CHAT + "/disponibilidade", headers=outro_usuario).json() == {"disponivel": True}
    assert client.put(POLITICA, headers=outro_usuario, json={"chat_ativo": False, "historico_dias": None}).status_code == 403

    def verificar_bloqueio(headers):
        assert client.get(CHAT + "/disponibilidade", headers=headers).json() == {"disponivel": False}
        assert client.get(CHAT + "/conversas", headers=headers).status_code == 403
        assert client.get(CHAT + f"/conversas/{uuid4()}", headers=headers).status_code == 403
        assert client.post(CHAT + "/chat", headers=headers, json={"pergunta": "Teste"}).status_code == 403
        assert client.post(CHAT + "/equipamentos", headers=headers, json={"operacao": "listar"}).status_code == 403

    assert client.put(POLITICA, headers=auth_headers, json={"chat_ativo": False, "historico_dias": None}).status_code == 200
    verificar_bloqueio(auth_headers)
    verificar_bloqueio(outro_usuario)

    atualizado = client.put("/api/v1/usuarios/2", headers=auth_headers, json={"chat_ia_ativo": False})
    assert atualizado.status_code == 200, atualizado.text
    assert atualizado.json()["chat_ia_ativo"] is False
    assert client.put(POLITICA, headers=auth_headers, json={"chat_ativo": True, "historico_dias": None}).status_code == 200
    assert client.get(CHAT + "/disponibilidade", headers=auth_headers).json() == {"disponivel": True}
    verificar_bloqueio(outro_usuario)

    assert client.put("/api/v1/usuarios/2", headers=auth_headers, json={"nome": "Operador Editado"}).json()["chat_ia_ativo"] is False
    assert client.put("/api/v1/usuarios/2", headers=auth_headers, json={"chat_ia_ativo": True}).status_code == 200
    assert client.get(CHAT + "/disponibilidade", headers=outro_usuario).json() == {"disponivel": True}


def _mensagem(conversa, usuario, idade, texto):
    return ChatInventarioMensagem(conversa_id=conversa, usuario_id=usuario, planta_id=None,
                                   inventarios="impressora,ti", pergunta=texto, resposta="Resposta",
                                   resultados=[], created_at=datetime.now(timezone.utc) - timedelta(days=idade))


def test_retencao_apaga_mensagens_vencidas_e_preserva_as_recentes(client, auth_headers, outro_usuario):
    conversa = uuid4()
    with TestingSession() as db:
        db.add_all([_mensagem(conversa, 1, 31, "Expirada"),
                    _mensagem(conversa, 1, 29, "Recente"),
                    _mensagem(uuid4(), 2, 90, "De outra conta")])
        db.commit()
        assert executar_retencao(db) == 0

    invalido = client.put(POLITICA, headers=auth_headers, json={"chat_ativo": True, "historico_dias": 0})
    assert invalido.status_code == 422
    resposta = client.put(POLITICA, headers=auth_headers, json={"chat_ativo": True, "historico_dias": 30})
    assert resposta.json() == {"chat_ativo": True, "historico_dias": 30}

    with TestingSession() as db:
        assert [m.pergunta for m in db.query(ChatInventarioMensagem).all()] == ["Recente"]
        db.add(_mensagem(uuid4(), 1, 31, "Expirada desde o último ciclo"))
        db.commit()
    historico = client.get(CHAT + "/conversas", headers=auth_headers).json()
    assert [c["titulo"] for c in historico["conversas"]] == ["Recente"]
    with TestingSession() as db:
        assert executar_retencao(db) == 1
        assert [m.pergunta for m in db.query(ChatInventarioMensagem).all()] == ["Recente"]


def test_desativar_durante_pergunta_impede_resposta_e_gravacao(client, auth_headers, outro_usuario, monkeypatch):
    def desativar(*args, **kwargs):
        with TestingSession() as db:
            db.add(ConfiguracaoSistema(id=1, ollama_chat_ativo=False))
            db.commit()
        return {"content": ""}

    monkeypatch.setattr(ia, "_perguntar", desativar)
    resposta = client.post(CHAT + "/chat", headers=auth_headers, json={"pergunta": "Em andamento"})
    assert resposta.status_code == 403, resposta.text
    with TestingSession() as db:
        assert db.query(ChatInventarioMensagem).count() == 0
