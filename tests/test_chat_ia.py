from uuid import uuid4

import pytest

from app.config import settings
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import create_access_token
from app.models import Ativo, ChatInventarioMensagem, Departamento, Planta, PlantaLocalidade, SoftwareInstalado, Usuario
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


@pytest.mark.parametrize("sigla_cadastrada", [None, "TI"])
def test_contagem_departamento_por_sigla_e_nome_aplica_o_mesmo_escopo(
    client, auth_headers, inventario_ia, monkeypatch, sigla_cadastrada,
):
    with TestingSession() as db:
        db.add(Departamento(id=2, nome="Técnologia da Informação", sigla=sigla_cadastrada, planta_id=1))
        db.flush()
        db.get(Ativo, 1).departamento_id = 2
        db.get(Ativo, 4).departamento_id = 2
        ficha = db.get(AtivoTI, 1)
        ficha.hostname = "LUCASMENDES"
        ficha.so = "Windows 11"
        db.commit()
    chamadas = _modelo(monkeypatch, [{
        "operacao": "contar",
        "filtros": [_filtro("departamento", "igual", "TI"), _filtro("tipo_equipamento", "igual", "desktop")],
    }])
    headers = {**auth_headers, "X-Planta-Id": "1"}
    for nome in ("TI", "T.I.", "Técnologia da Informação"):
        resposta = client.post("/api/v1/ia/chat", headers=headers, json={
            "pergunta": f"Quantos computadores tenho no departamento de {nome}?",
        })
        assert resposta.status_code == 200, resposta.text
        dados = resposta.json()["resultados"][0]
        assert dados["total"] == 1
        assert dados["cadastros_consultados"]["departamento"] == ["Técnologia da Informação"]
        assert [a["hostname"] for a in dados["amostra_equipamentos"]["equipamentos"]] == ["LUCASMENDES"]
    assert not chamadas
    client.post("/api/v1/ia/chat", headers=headers, json={
        "pergunta": "Quantos computadores tenho no departamento de TI com Windows 11?",
    })
    assert chamadas


def test_siglas_da_planta_e_departamento_com_software_e_versao(client, auth_headers, inventario_ia, monkeypatch):
    with TestingSession() as db:
        planta = db.get(Planta, 2)
        planta.nome = "Unidade Tatuí"
        planta.sigla = "UTU"
        db.add(PlantaLocalidade(codigo="TAT", planta_id=2))
        db.add_all([
            Departamento(id=2, nome="Tecnologia da Informação", sigla="TI", planta_id=2),
            Departamento(id=3, nome="Tecnologia da Informação", sigla="TI", planta_id=1),
            Departamento(id=4, nome="Qualidade", sigla="QL-2", planta_id=2),
        ])
        db.flush()
        db.get(Ativo, 3).departamento_id = 2
        db.get(Ativo, 1).departamento_id = 3
        db.add(Ativo(id=5, planta_id=2, departamento_id=4, numero_serie="QA-5", dominio="ti"))
        db.add(AtivoTI(ativo_id=5, hostname="DTAT0005", so="Windows 11"))
        db.add_all([SoftwareInstalado(ativo_id=i, nome="Google Chrome", versao="120.0.1") for i in (1, 3, 5)])
        db.commit()

    chamadas = _modelo(monkeypatch, [{
        "operacao": "contar", "softwares": [{"nome": "Chrome", "versao": "120.0.1"}],
        "filtros": [_filtro("dominio", "igual", "TI"), _filtro("planta", "igual", "Matriz")],
    }])
    for depto, planta, id_, nome in (
        ("TI", "TAT", 3, "Tecnologia da Informação"), ("T.I.", "UTU", 3, "Tecnologia da Informação"),
        ("QL-2", "T.A.T.", 5, "Qualidade"),
    ):
        resposta = client.post("/api/v1/ia/chat", headers=auth_headers, json={
            "pergunta": f"quantos computadores do {depto} em {planta} têm o Chrome na versão 120.0.1?",
        })
        assert resposta.status_code == 200, resposta.text
        chat = resposta.json()
        dados = chat["resultados"][0]
        assert dados["total"] == 1
        assert dados["cadastros_consultados"] == {"planta": ["Unidade Tatuí"], "departamento": [nome]}
        assert dados["amostra_equipamentos"]["equipamentos"][0]["id"] == id_
        csv = client.get(f"/api/v1/ia/mensagens/{chat['id']}/exportacao", headers=auth_headers).json()
        assert [a["id"] for a in csv["resultados"][0]["equipamentos_exibidos"]] == [id_]
    assert '"referencias_de_escopo": {"departamento": ["ti"], "planta": ["tat"]}' in chamadas[0][1]

    fora = client.post("/api/v1/ia/chat", headers={**auth_headers, "X-Planta-Id": "1"}, json={
        "pergunta": "Quantos computadores do TI em TAT têm o Chrome na versão 120.0.1?",
    })
    assert "não corresponde ao escopo atual" in fora.json()["resposta"]


def test_software_por_versao_com_lista_paginada_e_exportacao_completa(client, auth_headers, inventario_ia, monkeypatch):
    with TestingSession() as db:
        for id_ in range(10, 55):
            db.add(Ativo(id=id_, planta_id=1, departamento_id=1, numero_serie=f"SW-{id_}", dominio="ti"))
            db.add(AtivoTI(ativo_id=id_, hostname=f"PC-{id_}", ram_gb=32, so="Windows 11"))
            db.add(SoftwareInstalado(ativo_id=id_, nome="Google Chrome", versao="120.0.1"))
            db.add(SoftwareInstalado(ativo_id=id_, nome="7-Zip", versao="25.0"))
        db.add(SoftwareInstalado(ativo_id=10, nome="Google Chrome", versao="120.0.1"))
        db.add(SoftwareInstalado(ativo_id=1, nome="Google Chrome", versao="1200.0"))
        db.add(SoftwareInstalado(ativo_id=2, nome="Google Chrome", versao="120.0.1"))
        db.add(SoftwareInstalado(ativo_id=3, nome="Google Chrome", versao="120.0.1"))
        db.commit()
    _modelo(monkeypatch, [{
        "operacao": "contar", "filtros": [_filtro("ram_gb", "no_minimo", "16"), _filtro("so", "contém", "Windows")],
        "softwares": [{"nome": "Chrome", "versao": "120", "comparacao_versao": "prefixo"}, {"nome": "7-Zip"}],
        "agrupar_por": ["departamento"],
    }])
    headers = {**auth_headers, "X-Planta-Id": "1"}
    chat = client.post("/api/v1/ia/chat", headers=headers, json={"pergunta": "Quantos PCs com Chrome 120.x e 7-Zip por setor?"})
    assert chat.status_code == 200, chat.text
    dados = chat.json()
    resultado = dados["resultados"][0]
    assert resultado["total"] == 45 and resultado["grupos"][0]["valores"] == ["Operações"]
    amostra = resultado["amostra_equipamentos"]
    assert [a["id"] for a in amostra["equipamentos"]] == list(range(10, 15))
    rota = f"/api/v1/ia/mensagens/{dados['id']}"
    pagina = client.get(rota + "/resultados/0", headers=headers, params={"inicio": amostra["proximo"]}).json()
    assert pagina["proximo"] == 35 and len(pagina["equipamentos"]) == 30
    exportado = client.get(rota + "/exportacao", headers=headers).json()["resultados"][0]
    ativos = exportado["equipamentos_exibidos"]
    assert len(ativos) == 45 and ativos[-1]["numero_serie"] == "SW-54"
    assert ativos[0]["softwares"] == [{"nome": "7-Zip", "versao": "25.0"}, {"nome": "Google Chrome", "versao": "120.0.1"}]
    assert client.get(rota + "/exportacao", headers={**headers, "X-Planta-Id": "2"}).status_code == 404
    leitor = {"Authorization": f"Bearer {create_access_token(2, 'leitor')}", "X-Planta-Id": "1"}
    assert client.get(rota + "/exportacao", headers=leitor).status_code == 404
    assert client.post("/api/v1/ia/equipamentos", headers=leitor, json=resultado["consulta"]).status_code == 403
    consulta_restrita = client.post("/api/v1/ia/chat", headers=leitor, json={"pergunta": "Quantos ativos com Chrome?"})
    assert "não tem acesso ao inventário de software" in consulta_restrita.json()["resposta"]


def test_percentual_e_ausencia_de_software_usam_a_coleta_existente(client, auth_headers, inventario_ia, monkeypatch):
    with TestingSession() as db:
        db.add_all([
            SoftwareInstalado(ativo_id=1, nome="Chrome", versao="120"),
            SoftwareInstalado(ativo_id=2, nome="7-Zip", versao="25"),
        ])
        db.commit()
    _modelo(monkeypatch, [{
        "operacao": "percentual",
        "filtros": [_filtro("dominio", "igual", "ti")],
        "softwares_numerador": [{"nome": "Chrome", "versao": "120", "situacao": "ausente"}],
    }])
    resposta = client.post("/api/v1/ia/chat", headers=auth_headers, json={"pergunta": "Qual percentual sem Chrome 120?"})
    assert resposta.status_code == 200, resposta.text
    resultado = resposta.json()["resultados"][0]
    assert resultado["total"] == 3 and resultado["correspondentes"] == 1
    assert [a["id"] for a in resultado["amostra_equipamentos"]["equipamentos"]] == [2]
    with TestingSession() as db:
        db.add(SoftwareInstalado(ativo_id=2, nome="Chrome"))
        db.commit()
    indefinida = client.post("/api/v1/ia/chat", headers=auth_headers, json={"pergunta": "Qual percentual sem Chrome 120?"})
    assert indefinida.json()["resultados"][0]["correspondentes"] == 0


def test_exportacao_de_ficha_traz_software_acima_do_limite_da_previa(client, auth_headers, inventario_ia, monkeypatch):
    with TestingSession() as db:
        db.add_all([SoftwareInstalado(ativo_id=1, nome=f"Aplicativo {i:02d}", versao="1.0") for i in range(25)])
        db.commit()

    def modelo(*args, **kwargs):
        return {"tool_calls": [{"function": {"name": "consultar_ficha_ativo",
                              "arguments": {"identificador": "DTAT0001", "assunto": "software"}}}]}

    monkeypatch.setattr(ia, "_perguntar", modelo)
    chat = client.post("/api/v1/ia/chat", headers=auth_headers, json={"pergunta": "Quais softwares tem no DTAT0001?"}).json()
    assert ["Aplicativo 24", "1.0"] not in chat["resultados"][0]["blocos"][0]["linhas"]
    resposta = client.get(f"/api/v1/ia/mensagens/{chat['id']}/exportacao", headers=auth_headers)
    assert resposta.status_code == 200, resposta.text
    linhas = resposta.json()["resultados"][0]["blocos"][0]["linhas"]
    assert len(linhas) == 25 and linhas[-1] == ["Aplicativo 24", "1.0"]


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


def test_chat_conta_os_mesmos_99_ativos_do_rateio_por_planta_e_departamento(
    client, auth_headers, inventario_ia, monkeypatch,
):
    with TestingSession() as db:
        planta = db.get(Planta, 2)
        planta.nome = "Unidade Tatuí"
        planta.cidade = "Tatuí"
        db.add_all([
            Departamento(id=2, nome="Engenharia de Produção", sigla="Engenharia", planta_id=2),
            Departamento(id=3, nome="Engenharia", planta_id=1),
        ])
        db.flush()
        db.add_all(Ativo(planta_id=2, departamento_id=2, numero_serie=f"ENG-{i}", dominio="ti") for i in range(98))
        db.add(Ativo(planta_id=2, departamento_id=2, numero_serie="ENG-legado", dominio="ti", tipo_item="consumivel"))
        db.add(Ativo(planta_id=1, departamento_id=3, numero_serie="ENG-outra-planta", dominio="ti"))
        db.commit()

    rateio = client.get("/api/v1/financeiro/rateio", headers={**auth_headers, "X-Planta-Id": "2"})
    esperado = next(item["ativos"] for item in rateio.json()["itens"] if item["departamento"] == "Engenharia")
    _modelo(monkeypatch, [
        {"operacao": "contar", "filtros": [_filtro("planta", "igual", "Tatui"), _filtro("departamento", "igual", "Engenharia")]},
        {"operacao": "contar", "filtros": [
            _filtro("planta", "igual", "planta de Tatui"), _filtro("departamento", "igual", "departamento da Engenharia"),
            _filtro("tipo_equipamento", "igual", "ativos"),
        ]},
    ])
    resposta = client.post("/api/v1/ia/chat", headers=auth_headers, json={
        "pergunta": "Quantos ativos tem na planta de tatui no departamento da engenharia?",
    })
    assert resposta.status_code == 200, resposta.text
    resultados = resposta.json()["resultados"]
    assert [resultado["total"] for resultado in resultados] == [esperado, esperado] == [99, 99]
    assert resultados[0]["cadastros_consultados"] == {"planta": ["Unidade Tatuí"], "departamento": ["Engenharia de Produção"]}
    equipamentos = client.post("/api/v1/ia/equipamentos", headers=auth_headers, json=resultados[0]["consulta"]).json()
    assert equipamentos["total"] == 99
    assert {equipamento["departamento"] for equipamento in equipamentos["equipamentos"]} == {"Engenharia de Produção"}


def test_chat_aponta_departamento_nao_encontrado(client, auth_headers, inventario_ia, monkeypatch):
    _modelo(monkeypatch, [{"operacao": "contar", "filtros": [_filtro("departamento", "igual", "Engenharia")]}])
    resposta = client.post("/api/v1/ia/chat", headers=auth_headers, json={"pergunta": "Quantos ativos em Engenharia?"})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["resultados"] == []
    assert "Não encontrei o departamento" in resposta.json()["resposta"]


def test_chat_consulta_ram_cadastrada_por_patrimonio(client, auth_headers, inventario_ia, monkeypatch):
    with TestingSession() as db:
        db.get(Ativo, 3).patrimonio = "TP98000011212"
        db.get(AtivoTI, 3).ram_gb = 32
        db.get(AtivoTI, 3).cpu = "Processador de teste"
        db.commit()
    recebidas = _modelo(monkeypatch, [{
        "operacao": "listar", "atributos": ["ram_gb"],
        "filtros": [_filtro("patrimonio", "igual", "tp98000011212")],
    }])
    pergunta = {"pergunta": "Quantos gigas de RAM tem o ativo TP98000011212?"}
    resposta = client.post("/api/v1/ia/chat", headers=auth_headers, json=pergunta)
    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()
    assert dados["resposta"] == "O ativo TP98000011212 tem 32 GB de RAM cadastrados."
    assert dados["resultados"][0]["atributos"] == ["ram_gb"]
    assert dados["resultados"][0]["equipamentos"][0]["ram_gb"] == 32
    assert "cpu" not in dados["resultados"][0]["equipamentos"][0]
    assert len(recebidas) == 1

    outra_planta = {"Authorization": f"Bearer {create_access_token(2, 'leitor')}"}
    resposta = client.post("/api/v1/ia/chat", headers=outra_planta, json=pergunta).json()
    assert resposta["resultados"][0]["equipamentos"] == []
    assert "Nenhum equipamento encontrado" in resposta["resposta"]


def test_chat_informa_quando_o_ativo_nao_tem_ram_cadastrada(client, auth_headers, inventario_ia, monkeypatch):
    _modelo(monkeypatch, [{
        "operacao": "listar", "atributos": ["ram_gb"],
        "filtros": [_filtro("patrimonio", "igual", "PT-2")],
    }])
    resposta = client.post("/api/v1/ia/chat", headers=auth_headers, json={"pergunta": "Qual a RAM do ativo PT-2?"}).json()
    assert resposta["resultados"][0]["equipamentos"][0]["ram_gb"] is None
    assert "sem informação cadastrada" in resposta["resposta"]


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
