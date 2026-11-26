from datetime import datetime, timedelta, timezone

import pytest

from app.models import Ativo, Planta, Usuario
from app.models.agente import AcaoAgente, TokenAgente
from app.services.agente_service import hash_segredo
from tests.conftest import TestingSession, create_access_token

API = "/api/v1"
PAINEL = API + "/ativos/101/acoes-agente"
CONSULTA = API + "/agente/acoes/consultar"
RESULTADO = API + "/agente/acoes/resultado"


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def parque(client):
    with TestingSession() as db:
        db.add(Planta(id=2, nome="Outra planta", sigla="OUT"))
        db.add_all([
            Ativo(id=101, dominio="ti", planta_id=1, patrimonio="PC-1", numero_serie="SN-1"),
            Ativo(id=102, dominio="ti", planta_id=2, patrimonio="PC-2", numero_serie="SN-2"),
            Ativo(id=103, dominio="ti", planta_id=1, patrimonio="PC-3", numero_serie="SN-3"),
            Usuario(id=12, nome="Técnico Autorizado", email="autorizado@teste.com", senha_hash="teste",
                    papel="ti", planta_id=1, permissoes={"pode_acoes_agente": True}),
            Usuario(id=13, nome="Técnico Padrão", email="padrao@teste.com", senha_hash="teste",
                    papel="ti", planta_id=1),
        ])
        db.flush()
        db.add_all([TokenAgente(id=i, ativo_id=ativo, prefixo=f"machine-{i}", token_hash=hash_segredo(f"machine-{i}"))
                    for i, ativo in [(21, 101), (22, 102)]])
        db.commit()
    return {"agente": _headers("machine-21"), "outro": _headers("machine-22"),
            "tecnico": _headers(create_access_token(12, "ti")), "padrao": _headers(create_access_token(13, "ti"))}


@pytest.mark.parametrize(("tipo", "resultado", "estado"), [
    ("coletar", "coleta_enviada", "concluida"),
    ("coletar", "falha_coleta", "falhou"),
    ("testar_comunicacao", "comunicacao_ok", "concluida"),
    ("status_servico", "servico_em_execucao", "concluida"),
    ("status_servico", "falha_status", "falhou"),
])
def test_acoes_com_historico_e_resultado(client, parque, tipo, resultado, estado):
    usuario, agente = parque["tecnico"], parque["agente"]
    criado = client.post(PAINEL, headers=usuario, json={"tipo": tipo})
    assert criado.status_code == 201, criado.text
    acao_id = criado.json()["id"]
    assert criado.json()["estado"] == "aguardando"
    assert client.post(PAINEL, headers=usuario, json={"tipo": tipo}).status_code == 409
    assert client.post(RESULTADO, headers=agente, json={"id": acao_id, "resultado": resultado}).status_code == 409

    assert client.post(CONSULTA, headers=parque["outro"]).json() == {"acao": None}
    assert client.post(CONSULTA, headers=agente).json()["acao"] == {"id": acao_id, "tipo": tipo}
    assert client.post(CONSULTA, headers=agente).json() == {"acao": None}
    corpo = {"id": acao_id, "resultado": resultado}
    assert client.post(RESULTADO, headers=parque["outro"], json=corpo).status_code == 404
    assert client.post(RESULTADO, headers=agente, json=corpo).status_code == 200
    assert client.post(RESULTADO, headers=agente, json=corpo).status_code == 200
    painel = client.get(PAINEL, headers=usuario).json()
    assert painel["ultimo_contato"] and painel["recebe_acoes"]
    item = painel["historico"][0]
    assert (item["solicitante"], item["estado"], item["resultado"]) == ("Técnico Autorizado", estado, resultado)
    assert item["encerrada_em"]


def test_acesso_por_usuario_planta_e_credencial(client, auth_headers, parque):
    assert client.get(PAINEL, headers=parque["padrao"]).status_code == 403
    assert client.post(PAINEL, headers=parque["padrao"], json={"tipo": "coletar"}).status_code == 403
    assert client.get(PAINEL.replace("101", "102"), headers=parque["tecnico"]).status_code == 404
    assert client.get(PAINEL.replace("101", "103"), headers=auth_headers).json()["vinculado"] is False
    assert client.post(CONSULTA, headers=auth_headers).status_code == 401
    assert client.get(PAINEL, headers=parque["agente"]).status_code == 401
    assert client.post(PAINEL, headers=auth_headers, json={"tipo": "status_servico", "argumento": "extra"}).status_code == 422
    assert client.post(PAINEL, headers=auth_headers, json={"tipo": "desconhecido"}).status_code == 422


def test_revogacao_e_expiracao_antes_da_entrega(client, auth_headers, parque):
    corpo = {"tipo": "coletar"}
    pendente = client.post(PAINEL, headers=parque["tecnico"], json=corpo).json()
    with TestingSession() as db:
        db.get(Usuario, 12).permissoes = {"pode_acoes_agente": False}
        db.commit()
    assert client.post(CONSULTA, headers=parque["agente"]).json() == {"acao": None}
    cancelada = client.get(PAINEL, headers=auth_headers).json()["historico"][0]
    assert cancelada["id"] == pendente["id"] and cancelada["estado"] == "cancelada"

    nova = client.post(PAINEL, headers=auth_headers, json=corpo).json()
    with TestingSession() as db:
        db.get(AcaoAgente, nova["id"]).expira_em = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    assert client.post(CONSULTA, headers=parque["agente"]).json() == {"acao": None}
    assert client.get(PAINEL, headers=auth_headers).json()["historico"][0]["estado"] == "expirada"


def test_historico_mostra_registros_anteriores(client, auth_headers, parque):
    agora = datetime.now(timezone.utc)
    with TestingSession() as db:
        db.add_all([AcaoAgente(token_id=21, ativo_id=101, planta_id=1, solicitante_id=1,
                               solicitante_nome="Admin", tipo="testar_comunicacao", estado="concluida",
                               solicitada_em=agora, encerrada_em=agora, expira_em=agora,
                               resultado="comunicacao_ok") for _ in range(31)])
        db.commit()
    primeira = client.get(PAINEL, headers=auth_headers).json()
    assert len(primeira["historico"]) == 30
    anterior = client.get(PAINEL, headers=auth_headers, params={"antes_de": primeira["proximo"]}).json()
    assert len(anterior["historico"]) == 1
    assert anterior["historico"][0]["id"] < primeira["historico"][-1]["id"]
    assert anterior["proximo"] is None


def test_troca_de_token_cancela_pedido_antigo(client, auth_headers, parque):
    acao = {"tipo": "coletar"}
    anterior = client.post(PAINEL, headers=auth_headers, json=acao).json()["id"]
    with TestingSession() as db:
        db.get(TokenAgente, 21).revogado_em = datetime.now(timezone.utc)
        db.add(TokenAgente(ativo_id=101, prefixo="novo-token", token_hash=hash_segredo("novo-token")))
        db.commit()
    assert client.post(CONSULTA, headers=parque["agente"]).status_code == 401
    painel = client.get(PAINEL, headers=auth_headers).json()
    assert painel["vinculado"] and painel["historico"][0]["estado"] == "cancelada"
    novo = client.post(PAINEL, headers=auth_headers, json=acao)
    assert novo.status_code == 201
    assert client.post(CONSULTA, headers=_headers("novo-token")).json()["acao"]["id"] != anterior
