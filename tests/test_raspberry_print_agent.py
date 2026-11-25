"""Autenticação entre o Nexus e o agente de impressão."""
from collections import deque
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import raspberry_print_agent as agent
from app.config import settings
from app.services import print_service

ORIGEM = "https://impressao.exemplo.test:9100"
TOKEN = "credencial-de-teste-nao-usar-em-producao"


@pytest.fixture(autouse=True)
def configuracao_agente(monkeypatch):
    monkeypatch.setattr(agent, "_jobs_recebidos", deque())
    monkeypatch.setenv("RPI_PRINT_QUEUES", "zebra")
    monkeypatch.delenv("RPI_PRINT_RAW_DESTINATIONS", raising=False)


def test_agente_exige_token_antes_de_usar_o_cups(monkeypatch):
    imprimir = Mock(return_value=(True, "enviado"))
    listar = Mock(return_value=Mock(stdout="printer zebra pronta"))
    monkeypatch.setattr(agent, "_cups_print", imprimir)
    monkeypatch.setattr(agent.subprocess, "run", listar)
    monkeypatch.delenv("RPI_PRINT_TOKEN", raising=False)
    job = {"job_id": "etiqueta", "format": "zpl", "data": "XlhB"}
    with TestClient(agent.app) as cliente:
        assert cliente.post("/print", json=job).status_code == 503
        monkeypatch.setenv("RPI_PRINT_TOKEN", TOKEN)
        assert cliente.post("/print", json=job).status_code == 401
        assert cliente.get("/health", headers={"Authorization": "Bearer incorreto"}).status_code == 401
        imprimir.assert_not_called()
        listar.assert_not_called()

        headers = {"Authorization": f"Bearer {TOKEN}"}
        assert cliente.post("/print", json=job, headers=headers).json()["status"] == "ok"
        imprimir.assert_called_once_with("zebra", 1, True, b"^XA")
        assert cliente.get("/health", headers=headers).json()["printers"] == ["zebra"]


def test_agente_envia_apenas_para_destinos_de_rede_configurados(monkeypatch):
    monkeypatch.setenv("RPI_PRINT_TOKEN", TOKEN)
    monkeypatch.setenv("RPI_PRINT_RAW_DESTINATIONS", "etiquetas.exemplo.test:9101")
    imprimir = Mock(return_value=(True, "enviado"))
    cups = Mock()
    monkeypatch.setattr(agent, "_raw_socket_print", imprimir)
    monkeypatch.setattr(agent, "_cups_print", cups)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    job = {"job_id": "etiqueta", "format": "zpl", "data": "XlhB"}
    with TestClient(agent.app) as cliente:
        assert cliente.post("/print", json={**job, "printer": "outra.exemplo.test"}, headers=headers).status_code == 403
        imprimir.assert_not_called()
        resposta = cliente.post("/print", json={**job, "printer": "etiquetas.exemplo.test:9101"}, headers=headers)
        assert resposta.status_code == 200
        imprimir.assert_called_once_with("etiquetas.exemplo.test", 9101, b"^XA")
        cups.assert_not_called()


def test_agente_limita_tamanho_e_frequencia_de_trabalhos(monkeypatch):
    monkeypatch.setenv("RPI_PRINT_TOKEN", TOKEN)
    monkeypatch.setattr(agent, "MAX_JOB_BYTES", 256)
    monkeypatch.setattr(agent, "MAX_JOBS_PER_MINUTE", 1)
    imprimir = Mock()
    monkeypatch.setattr(agent, "_cups_print", imprimir)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(agent.app) as cliente:
        assert cliente.post("/print", content=b"x" * 257).status_code == 401
        assert cliente.post("/print", content=b"x" * 257, headers=headers).status_code == 413
        limitada = cliente.post("/print", json={"job_id": "teste", "data": "XlhB"}, headers=headers)
        assert limitada.status_code == 429
        assert int(limitada.headers["Retry-After"]) > 0
        imprimir.assert_not_called()


@pytest.mark.parametrize("url", [
    "https://outro.exemplo.test:9100",
    "https://impressao.exemplo.test",
    "http://impressao.exemplo.test:9100",
    "https://usuario@impressao.exemplo.test:9100",
    f"{ORIGEM}?chave=valor",
])
def test_nexus_recusa_destinos_sem_credencial_vinculada_ou_sem_tls(monkeypatch, url):
    monkeypatch.setattr(settings, "print_agent_tokens", {ORIGEM: SecretStr(TOKEN)})
    post = Mock()
    monkeypatch.setattr(print_service.httpx, "post", post)
    assert print_service._via_agente(url, "zpl", b"^XA", "zebra", 1, "etiqueta")["status"] == "error"
    post.assert_not_called()


def test_nexus_envia_token_e_etiqueta_ao_agente_autorizado(monkeypatch):
    monkeypatch.setattr(settings, "print_agent_tokens", {ORIGEM: SecretStr(TOKEN)})
    monkeypatch.setenv("RPI_PRINT_TOKEN", TOKEN)
    imprimir = Mock(return_value=(True, "enviado"))
    monkeypatch.setattr(agent, "_cups_print", imprimir)
    with TestClient(agent.app, base_url=ORIGEM) as cliente:
        def post(url, **kwargs):
            assert str(url) == f"{ORIGEM}/print"
            assert kwargs.pop("trust_env") is True
            assert kwargs.pop("timeout") == settings.print_agent_timeout
            assert kwargs["follow_redirects"] is False
            return cliente.post(str(url), **kwargs)

        monkeypatch.setattr(print_service.httpx, "post", post)
        resposta = print_service._via_agente(ORIGEM, "zpl", b"^XA", "zebra", 1, "etiqueta")
    assert (resposta["status"], resposta["attempts"]) == ("ok", 1)
    imprimir.assert_called_once_with("zebra", 1, True, b"^XA")


@pytest.mark.parametrize("falha", [
    httpx.ReadTimeout("Sem confirmação"),
    httpx.Response(302, headers={"Location": "https://outro.exemplo.test"}),
    httpx.Response(401),
])
def test_nexus_nao_reenvia_trabalho_quando_o_agente_ja_recebeu_a_requisicao(monkeypatch, falha):
    monkeypatch.setattr(settings, "print_agent_tokens", {ORIGEM: SecretStr(TOKEN)})
    post = Mock(side_effect=[falha])
    if isinstance(falha, httpx.Response):
        falha.request = httpx.Request("POST", f"{ORIGEM}/print")
    monkeypatch.setattr(print_service.httpx, "post", post)
    resposta = print_service._via_agente(ORIGEM, "zpl", b"^XA", "zebra", 1, "etiqueta")
    assert resposta["retryable"] is False
    post.assert_called_once()
