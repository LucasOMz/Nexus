from datetime import datetime, timedelta, timezone

import pytest

from app.models import Ativo, Planta, Usuario
from app.models.agente import AcaoAgente, TokenAgente
from app.routers import acoes_agente
from app.services.agente_service import hash_segredo
from tests.conftest import TestingSession, create_access_token

API = "/api/v1"
PAINEL = API + "/ativos/101/acoes-agente"
CONSULTA = API + "/agente/acoes/consultar"
RESULTADO = API + "/agente/acoes/resultado"
LOTES = API + "/acoes-agente/lotes"


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


def test_lote_respeita_planta_permissao_e_coletas_ja_solicitadas(client, parque):
    tecnico = parque["tecnico"]
    assert client.post(LOTES, headers=parque["padrao"]).status_code == 403
    criado = client.post(LOTES, headers=tecnico)
    assert criado.status_code == 201, criado.text
    lote = criado.json()
    assert (lote["total"], lote["sem_agente"], lote["ja_solicitados"]) == (1, 1, 0)
    assert client.post(LOTES, headers=tecnico).status_code == 409
    assert client.post(PAINEL, headers=tecnico, json={"tipo": "coletar"}).status_code == 409
    assert client.get(LOTES, headers=tecnico).json()["coletas_por_minuto"] == 50
    assert client.post(CONSULTA, headers=parque["outro"]).json()["acao"] is None

    rota = f"{LOTES}/{lote['id']}"
    assert client.get(rota, headers=parque["padrao"]).status_code == 403
    assert client.get(rota, headers=tecnico).json()["aguardando"] == 1
    pedido = client.post(CONSULTA, headers=parque["agente"]).json()["acao"]
    assert pedido["tipo"] == "coletar"
    assert client.get(rota, headers=tecnico).json()["em_execucao"] == 1
    assert client.post(RESULTADO, headers=parque["agente"],
                       json={"id": pedido["id"], "resultado": "falha_coleta"}).status_code == 200
    final = client.get(rota, headers=tecnico).json()
    assert (final["aguardando"], final["em_execucao"], final["concluidas"], final["total_falhas"]) == (0, 0, 0, 1)
    assert final["falhas"] == [{"ativo": "PC-1", "estado": "falhou", "resultado": "falha_coleta"}]


def test_lotes_distintos_compartilham_intervalo_global(client, auth_headers, parque, monkeypatch):
    class Relogio(datetime):
        instante = datetime.now(timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.instante

    monkeypatch.setattr(acoes_agente, "datetime", Relogio)
    for planta in (1, 2):
        resposta = client.post(LOTES, headers={**auth_headers, "X-Planta-Id": str(planta)})
        assert resposta.status_code == 201, resposta.text
    assert client.post(CONSULTA, headers=parque["agente"]).json()["acao"]
    assert client.post(CONSULTA, headers=parque["outro"]).json()["acao"] is None
    Relogio.instante += timedelta(milliseconds=1199)
    assert client.post(CONSULTA, headers=parque["outro"]).json()["acao"] is None
    Relogio.instante += timedelta(milliseconds=1)
    assert client.post(CONSULTA, headers=parque["outro"]).json()["acao"]


def test_parque_de_3000_mantem_o_limite_por_minuto(client, auth_headers, monkeypatch):
    from starlette.requests import Request

    inicio = datetime.now(timezone.utc)

    class Relogio(datetime):
        instante = inicio

        @classmethod
        def now(cls, tz=None):
            return cls.instante

    monkeypatch.setattr(acoes_agente, "datetime", Relogio)
    with TestingSession() as db:
        db.bulk_insert_mappings(Ativo, [
            {"id": i, "dominio": "ti", "planta_id": 1, "patrimonio": f"PARQUE-{i}", "numero_serie": f"SERIE-{i}"}
            for i in range(1, 3001)
        ])
        db.bulk_insert_mappings(TokenAgente, [
            {"ativo_id": i, "prefixo": f"ag{i}", "token_hash": hash_segredo(f"parque-{i}")}
            for i in range(1, 3001)
        ])
        db.commit()

    resposta = client.post(LOTES, headers=auth_headers)
    assert resposta.status_code == 201, resposta.text
    assert resposta.json()["total"] == 3000

    def consultar(db, i):
        pedido = Request({"type": "http", "headers": [(b"authorization", f"Bearer parque-{i}".encode())]})
        return acoes_agente.consultar(pedido, db)["acao"]

    with TestingSession() as db:
        primeira_entrega = consultar(db, 1)
        assert primeira_entrega["tipo"] == "coletar"
        assert client.post(RESULTADO, headers=_headers("parque-1"),
                           json={"id": primeira_entrega["id"], "resultado": "coleta_enviada"}).status_code == 200
        assert client.post(LOTES, headers=auth_headers).status_code == 409
        assert consultar(db, 2) is None
        for i in range(2, 3001):
            Relogio.instante = inicio + timedelta(milliseconds=1200 * (i - 1))
            assert consultar(db, i)["tipo"] == "coletar", i
        assert db.query(AcaoAgente).filter(AcaoAgente.lote_entregue_em < inicio + timedelta(minutes=1)).count() == 50
        assert db.query(AcaoAgente).filter(AcaoAgente.lote_entregue_em.is_not(None)).count() == 3000
        assert Relogio.instante == inicio + timedelta(seconds=3598.8)


def test_lote_expirado_aparece_nas_falhas(client, parque):
    tecnico = parque["tecnico"]
    lote = client.post(LOTES, headers=tecnico).json()
    with TestingSession() as db:
        item = db.query(AcaoAgente).filter_by(lote_id=lote["id"]).one()
        item.expira_em = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    dados = client.get(f"{LOTES}/{lote['id']}", headers=tecnico).json()
    assert dados["aguardando"] == 0 and dados["total_falhas"] == 1
    assert dados["falhas"][0]["estado"] == "expirada"
    assert client.post(LOTES, headers=tecnico).status_code == 201
