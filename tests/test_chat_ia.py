import pytest

from app.config import settings
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import create_access_token
from app.models import Ativo, Departamento, Planta, Usuario
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
