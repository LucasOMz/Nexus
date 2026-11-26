"""SNMP de impressora: interpretação das respostas.

Testa a TRADUÇÃO, não a rede. É o que torna este módulo verificável sem uma
impressora acessível — e é onde estão as decisões que erram na prática: os
códigos especiais da MIB, o índice dos suprimentos, a estimativa de duração.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Ativo, Base, Planta, Usuario
from app.models.impressora import AtivoImpressora, LeituraContador
from app.routers import monitor_impressoras
from app.services import snmp_service
from app.services.snmp_service import (
    OIDS,
    alertas_de_suprimento,
    classificar_suprimento,
    estimar_duracao,
    extrair_suprimentos,
    mapear,
    percentual_suprimento,
)
from tests.conftest import TestingSession


@pytest.fixture
def monitor_pool_minimo(client, tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'monitor.db').as_posix()}", pool_size=1,
        max_overflow=0, pool_timeout=0.15, connect_args={"check_same_thread": False},
    )
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            db.add(Planta(id=1, nome="Matriz", sigla="MAT", ativa=True))
            db.add(Usuario(id=1, nome="Admin", email="pool@teste.com", senha_hash="teste", papel="admin"))
            db.add(Ativo(id=1, planta_id=1, dominio="impressora", patrimonio="IMP-POOL", numero_serie="POOL-SNMP"))
            db.flush()
            db.add(AtivoImpressora(ativo_id=1, hostname="impressora-teste", contador_paginas=100))
            db.commit()

        def override():
            with Session(engine, expire_on_commit=False) as db:
                yield db

        anterior = client.app.dependency_overrides[get_db]
        client.app.dependency_overrides[get_db] = override
        try:
            yield engine
        finally:
            client.app.dependency_overrides[get_db] = anterior
    finally:
        engine.dispose()


@pytest.mark.parametrize(("metodo", "rota", "grava_contador"), [
    ("GET", "/1/situacao", False),
    ("GET", "/1/alertas", False),
    ("POST", "/1/coletar", True),
    ("POST", "/coletar-todas", True),
])
def test_monitor_devolve_conexao_antes_do_snmp(
    client, auth_headers, monkeypatch, monitor_pool_minimo, metodo, rota, grava_contador,
):
    conexoes_disponiveis = []

    def medir(endereco, comunidade="public"):
        with monitor_pool_minimo.connect() as conexao:
            conexoes_disponiveis.append(conexao.scalar(text("SELECT 1")))

    def monitorar(endereco):
        medir(endereco)
        return [], True

    def varrer(endereco, comunidade):
        medir(endereco, comunidade)
        return []

    def coletar(endereco, comunidade):
        medir(endereco, comunidade)
        return {"respondeu": True, "contador": 150}

    monkeypatch.setattr(snmp_service, "monitorar_suprimentos", monitorar)
    monkeypatch.setattr(monitor_impressoras, "_varrer_suprimentos", varrer)
    monkeypatch.setattr(snmp_service, "coletar", coletar)
    monkeypatch.setattr(snmp_service, "disponivel", lambda: True)

    resposta = client.request(metodo, "/api/v1/monitor/impressoras" + rota, headers=auth_headers)
    assert resposta.status_code == 200, resposta.text
    assert conexoes_disponiveis == [1]
    with Session(monitor_pool_minimo) as db:
        assert db.get(AtivoImpressora, 1).contador_paginas == (150 if grava_contador else 100)
        assert db.query(LeituraContador).count() == int(grava_contador)


def test_api_responde_503_quando_pool_esta_ocupado(client, auth_headers, monitor_pool_minimo):
    with monitor_pool_minimo.connect():
        resposta = client.get("/api/v1/auth/me", headers=auth_headers)
    assert resposta.status_code == 503
    assert "temporariamente ocupado" in resposta.json()["detail"]
    assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 200


@pytest.mark.parametrize(("respondeu", "nivel", "comunicacao"), [
    (True, 8, "online"),
    (True, None, "online"),
    (False, None, "sem_resposta"),
])
def test_situacao_da_impressora(client, auth_headers, monkeypatch, respondeu, nivel, comunicacao):
    with TestingSession() as db:
        ativo = Ativo(planta_id=1, dominio="impressora", tipo_item="ativo", status="em_uso",
                      patrimonio="IMP-01", numero_serie="SERIE-IMP-01")
        db.add(ativo)
        db.flush()
        ativo_id = ativo.id
        db.add(AtivoImpressora(ativo_id=ativo_id, hostname="impressora-teste", contador_paginas=200))
        db.commit()

    def monitorar(endereco):
        assert endereco == "impressora-teste"
        suprimentos = [] if nivel is None else [{
            "descricao": "Toner preto", "indice": "1", "percentual": nivel,
            "situacao": "critico", "nivel": nivel, "capacidade": 100,
        }]
        return suprimentos, respondeu

    monkeypatch.setattr(snmp_service, "monitorar_suprimentos", monitorar)
    resposta = client.get(f"/api/v1/monitor/impressoras/{ativo_id}/situacao", headers=auth_headers)
    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()
    assert dados["comunicacao"] == comunicacao
    assert dados["patrimonio"] == "IMP-01"
    assert dados["contador_cadastro"] == 200
    if nivel is None:
        assert dados["alertas"] == dados["suprimentos"] == []
    else:
        assert dados["suprimentos"][0]["percentual"] == nivel
        assert dados["alertas"][0]["gravidade"] == "alta"
    with TestingSession() as db:
        assert db.query(LeituraContador).filter_by(ativo_id=ativo_id).count() == 0


@pytest.mark.parametrize("erro", [None, "tempo esgotado"])
def test_monitoramento_confirma_comunicacao_quando_tabela_esta_vazia(monkeypatch, erro):
    transporte = pytest.importorskip("pysnmp.hlapi.v3arch.asyncio")

    async def alvo(*args, **kwargs):
        return object()

    async def varrer(*args, **kwargs):
        for resposta in ():
            yield resposta

    async def consultar(*args, **kwargs):
        return erro, None, None, ()

    monkeypatch.setattr(transporte.UdpTransportTarget, "create", alvo)
    monkeypatch.setattr(transporte, "walk_cmd", varrer)
    monkeypatch.setattr(transporte, "get_cmd", consultar)
    assert snmp_service.monitorar_suprimentos("impressora-teste") == ([], erro is None)


class TestMapeamento:
    """Traduz o que a impressora respondeu."""

    def test_leitura_completa(self):
        r = mapear({
            "modelo": "HP LaserJet M404",
            "numero_serie": "BRC123456",
            "contador": 152340,
            "status": 2,
            "suprimento_nivel": 45,
            "suprimento_max": 100,
            "suprimento_desc": "Black Cartridge",
        })
        assert r["modelo"] == "HP LaserJet M404"
        assert r["contador"] == 152340
        assert r["status"] == "rodando"
        assert r["suprimento"]["percentual"] == 45.0
        assert r["suprimento"]["situacao"] == "ok"

    def test_aceita_o_oid_cru(self):
        """A resposta real vem por OID, não por nome."""
        r = mapear({OIDS["contador"]: "9999", OIDS["modelo"]: "Epson WF"})
        assert r["contador"] == 9999
        assert r["modelo"] == "Epson WF"

    def test_contador_vem_como_texto(self):
        """SNMP devolve ora int, ora string — os dois precisam funcionar."""
        assert mapear({"contador": "12345"})["contador"] == 12345

    def test_contador_vem_como_bytes(self):
        assert mapear({"contador": b"777"})["contador"] == 777

    def test_status_desconhecido_nao_quebra(self):
        r = mapear({"status": 99})
        assert r["status"] is None
        assert r["status_codigo"] == 99

    def test_resposta_vazia_nao_respondeu(self):
        assert mapear({})["respondeu"] is False

    def test_alguma_resposta_marca_respondeu(self):
        assert mapear({"contador": 1})["respondeu"] is True


class TestNivelDeSuprimento:
    """A MIB usa códigos negativos com significados especiais."""

    def test_percentual_normal(self):
        assert percentual_suprimento(50, 100) == 50.0

    def test_vazio_e_zero(self):
        """-1 não é '-1%': é vazio."""
        assert percentual_suprimento(-1, 100) == 0.0
        assert classificar_suprimento(0.0) == "vazio"

    def test_desconhecido_nao_vira_numero(self):
        """-3 é 'não sei'. Tratar como número daria barra de -3%."""
        assert percentual_suprimento(-3, 100) is None
        assert classificar_suprimento(None) == "desconhecido"

    def test_sem_limite_nao_vira_numero(self):
        """-2 é 'sem limite' (suprimento contínuo)."""
        assert percentual_suprimento(-2, 100) is None

    def test_acima_da_capacidade_e_limitado(self):
        assert percentual_suprimento(150, 100) == 100.0

    def test_capacidade_zero_nao_divide(self):
        assert percentual_suprimento(50, 0) is None

    def test_faixas(self):
        assert classificar_suprimento(80) == "ok"
        assert classificar_suprimento(20) == "atencao"
        assert classificar_suprimento(5) == "critico"
        assert classificar_suprimento(0) == "vazio"


class TestVariosSuprimentos:
    """Uma impressora colorida tem tonner por cor."""

    PREFIXO = "1.3.6.1.2.1.43.11.1.1"

    def test_separa_por_indice(self):
        pares = [
            (f"{self.PREFIXO}.6.1.1", "Black Cartridge"),
            (f"{self.PREFIXO}.9.1.1", 80),
            (f"{self.PREFIXO}.8.1.1", 100),
            (f"{self.PREFIXO}.6.1.2", "Cyan Cartridge"),
            (f"{self.PREFIXO}.9.1.2", 5),
            (f"{self.PREFIXO}.8.1.2", 100),
        ]
        s = extrair_suprimentos(pares)
        assert len(s) == 2
        assert s[0]["descricao"] == "Black Cartridge"
        assert s[0]["situacao"] == "ok"
        assert s[1]["descricao"] == "Cyan Cartridge"
        assert s[1]["situacao"] == "critico"

    def test_ignora_oid_de_fora(self):
        assert extrair_suprimentos([("1.3.6.1.2.1.25.3.2.1.3.1", "x")]) == []

    def test_sem_suprimento_e_lista_vazia(self):
        assert extrair_suprimentos([]) == []


class TestAlertas:
    def _s(self, pct, desc="Tonner"):
        from app.services.snmp_service import classificar_suprimento
        return {"descricao": desc, "percentual": pct, "situacao": classificar_suprimento(pct)}

    def test_vazio_e_critico_alertam(self):
        a = alertas_de_suprimento([self._s(0.0, "Preto"), self._s(4.0, "Ciano")])
        assert len(a) == 2
        assert a[0]["gravidade"] == "alta"
        assert a[1]["gravidade"] == "alta"

    def test_atencao_alerta_com_gravidade_media(self):
        a = alertas_de_suprimento([self._s(20.0)])
        assert a[0]["gravidade"] == "media"

    def test_ok_nao_alerta(self):
        assert alertas_de_suprimento([self._s(70.0)]) == []

    def test_desconhecido_nao_vira_alarme_falso(self):
        """Não saber o nível não é motivo para alarmar."""
        assert alertas_de_suprimento([self._s(None)]) == []

    def test_ordena_do_mais_urgente(self):
        a = alertas_de_suprimento([self._s(20.0), self._s(0.0), self._s(5.0)])
        assert [x["situacao"] for x in a] == ["vazio", "critico", "atencao"]


class TestEstimativaDeDuracao:
    """A porcentagem sozinha não diz QUANDO acaba."""

    def test_estima_pelo_ritmo_real(self):
        # Caiu de 100% para 50% imprimindo 5.000 páginas em 10 dias.
        # Restam 50% => 5.000 páginas => a 500/dia, 10 dias.
        r = estimar_duracao(50.0, contador_atual=5000, contador_anterior=0,
                            dias_entre_leituras=10)
        assert r["aplicavel"]
        assert r["paginas_por_dia"] == 500.0
        assert r["dias_restantes"] == 10

    def test_urgente_quando_acaba_na_semana(self):
        r = estimar_duracao(5.0, contador_atual=10000, contador_anterior=0,
                            dias_entre_leituras=10)
        assert r["situacao"] == "urgente"

    def test_tranquilo_com_pouco_uso(self):
        r = estimar_duracao(80.0, contador_atual=100, contador_anterior=0,
                            dias_entre_leituras=30)
        assert r["situacao"] == "tranquilo"

    def test_sem_historico_nao_estima(self):
        assert not estimar_duracao(50.0, None, None, None)["aplicavel"]

    def test_sem_consumo_nao_estima(self):
        """Impressora parada: ritmo zero não permite projetar."""
        assert not estimar_duracao(50.0, 100, 100, 10)["aplicavel"]

    def test_suprimento_vazio_nao_estima(self):
        assert not estimar_duracao(0.0, 200, 100, 10)["aplicavel"]

    def test_contador_menor_que_o_anterior_nao_estima(self):
        """Troca de impressora ou reset do contador: não dá para projetar."""
        assert not estimar_duracao(50.0, 50, 500, 10)["aplicavel"]
