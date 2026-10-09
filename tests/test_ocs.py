"""Integração com o OCS Inventory.

Os testes usam um OCS **simulado** (monkeypatch nas funções de rede), para
exercitar o mapeamento, o casamento e as regras de planta sem depender de um
servidor real.

O que estes testes protegem, acima de tudo: **o OCS não pode sobrescrever dados
patrimoniais** (planta, patrimônio, responsável) nem duplicar máquinas.
"""
from __future__ import annotations

import pytest

from app.core.rate_limit import login_limiter, scan_limiter
from app.services import ocs_service


@pytest.fixture(autouse=True)
def _liberar_rate_limit():
    login_limiter._hits.clear()
    scan_limiter._hits.clear()
    yield
    login_limiter._hits.clear()
    scan_limiter._hits.clear()


# ---------------------------------------------------------------------------
# OCS simulado
# ---------------------------------------------------------------------------
class OCSSimulado:
    """Substitui as chamadas de rede por dados fixos."""

    def __init__(self, maquinas: list[dict]):
        self.maquinas = maquinas
        self.chamadas: list[str] = []

    def listar(self, cfg):
        self.chamadas.append("listar")
        return [m["maquina"] for m in self.maquinas]

    def detalhes(self, cfg, maquina_id):
        self.chamadas.append(f"detalhes:{maquina_id}")
        for m in self.maquinas:
            if m["maquina"].get("ID") == maquina_id:
                return m["detalhes"]
        return {}


def maquina(ocs_id=1, hostname="PC-BNT-001", serie="ABC123", **extra):
    """Uma máquina no formato que o OCS devolve."""
    return {
        "maquina": {"ID": ocs_id, "NAME": hostname, "LASTDATE": "2026-10-07 08:00:00", "USERID": "joao"},
        "detalhes": {
            "bios": {"SSN": serie, "SMANUFACTURER": extra.get("marca", "Dell"), "SMODEL": extra.get("modelo", "Latitude 5420")},
            "hardware": {"PROCESSORT": "Intel i5", "MEMORY": str(16 * 1024**3), "DISKSIZE": str(256 * 1024**3)},
            "os": {"OSNAME": "Windows 11 Pro"},
            "networks": {"MACADDR": "AA:BB:CC:DD:EE:FF", "IPADDRESS": "10.0.0.10"},
            "disk": None,
        },
    }


@pytest.fixture
def ocs(monkeypatch):
    """Instala um OCS simulado e devolve o objeto para inspeção."""
    simulado = OCSSimulado([maquina()])
    monkeypatch.setattr(ocs_service, "listar_maquinas", simulado.listar)
    monkeypatch.setattr(ocs_service, "detalhes", simulado.detalhes)
    return simulado


def _configurar(client, auth_headers, **extra):
    dados = {"ativo": True, "servidor": "http://ocs-teste/ocsinventory", "token": "tok-123", **extra}
    r = client.put("/api/v1/ocs/config", json=dados, headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()


def _planta(client, auth_headers, nome, sigla):
    return client.post("/api/v1/admin/plantas", json={"nome": nome, "sigla": sigla},
                       headers=auth_headers).json()["id"]


# ---------------------------------------------------------------------------
class TestConfiguracao:
    def test_config_inicial_sem_token(self, client, auth_headers):
        r = client.get("/api/v1/ocs/config", headers=auth_headers).json()
        assert r["ativo"] is False
        assert r["token_definido"] is False
        assert r["sync_intervalo_minutos"] == 60

    def test_token_fica_cifrado_e_nunca_volta(self, client, auth_headers):
        _configurar(client, auth_headers, token="segredo-do-ocs")
        r = client.get("/api/v1/ocs/config", headers=auth_headers).json()

        assert "token" not in r, "o token não pode voltar para a tela"
        assert r["token_definido"] is True
        assert r["token_cifrado"] is True

    def test_token_gravado_cifrado_e_lido_de_volta(self):
        """O formato guardado precisa ser reversível pelo próprio serviço."""
        from app.core.cripto import cifrar, esta_cifrado
        from app.models.ocs import ConfiguracaoOCS
        from app.services.ocs_service import token_de

        claro = "meu-token-do-ocs"
        guardado = cifrar(claro)
        assert claro not in guardado, "o token foi guardado em texto puro"
        assert esta_cifrado(guardado) is True

        cfg = ConfiguracaoOCS(id=1, token=guardado)
        assert token_de(cfg) == claro

    def test_token_vazio_mantem_o_atual(self, client, auth_headers):
        _configurar(client, auth_headers, token="original")
        client.put("/api/v1/ocs/config", json={"servidor": "http://novo/ocs"}, headers=auth_headers)
        assert client.get("/api/v1/ocs/config", headers=auth_headers).json()["token_definido"] is True

    def test_intervalo_fora_da_faixa_e_recusado(self, client, auth_headers):
        assert client.put("/api/v1/ocs/config", json={"sync_intervalo_minutos": 0}, headers=auth_headers).status_code == 422
        assert client.put("/api/v1/ocs/config", json={"sync_intervalo_minutos": 99999}, headers=auth_headers).status_code == 422

    def test_somente_admin_acessa(self, client, auth_headers):
        client.post("/api/v1/usuarios",
                    json={"nome": "Tec", "email": "tec.ocs@teste.com", "papel": "ti", "senha": "senha123"},
                    headers=auth_headers)
        login = client.post("/api/v1/auth/login", data={"username": "tec.ocs@teste.com", "password": "senha123"})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}

        assert client.get("/api/v1/ocs/config", headers=h).status_code == 403
        assert client.post("/api/v1/ocs/sincronizar", headers=h).status_code == 403


class TestRegrasDePlanta:
    def test_regra_valida_e_gravada(self, client, auth_headers):
        pid = _planta(client, auth_headers, "Bonito", "BON")
        r = _configurar(client, auth_headers, regras_planta=[{"prefixo": "PC-BNT-", "planta_id": pid}])
        # Regra sem `tipo` é gravada como "comeca_com" — compatível com o que
        # existia antes dos tipos de comparação.
        assert r["regras_planta"] == [{"prefixo": "PC-BNT-", "tipo": "comeca_com", "planta_id": pid}]

    def test_regra_para_planta_inexistente_e_recusada(self, client, auth_headers):
        r = client.put("/api/v1/ocs/config",
                       json={"regras_planta": [{"prefixo": "X-", "planta_id": 99999}]},
                       headers=auth_headers)
        assert r.status_code == 400

    def test_prefixo_vazio_e_descartado(self, client, auth_headers):
        pid = _planta(client, auth_headers, "Bonito", "BON")
        r = _configurar(client, auth_headers, regras_planta=[{"prefixo": "  ", "planta_id": pid}])
        assert r["regras_planta"] == []

    def test_casamento_por_prefixo(self):
        regras = [{"prefixo": "PC-BNT-", "planta_id": 2}, {"prefixo": "PC-TAT-", "planta_id": 3}]
        assert ocs_service.planta_por_hostname(regras, "PC-BNT-001") == 2
        assert ocs_service.planta_por_hostname(regras, "pc-tat-999") == 3   # sem diferenciar caixa
        assert ocs_service.planta_por_hostname(regras, "SERVIDOR-01") is None
        assert ocs_service.planta_por_hostname(regras, None) is None

    def test_regra_mais_especifica_nao_e_engolida(self):
        """A primeira regra que casa decide — a ordem importa."""
        regras = [{"prefixo": "PC-", "planta_id": 1}, {"prefixo": "PC-BNT-", "planta_id": 2}]
        assert ocs_service.planta_por_hostname(regras, "PC-BNT-001") == 1


class TestMapeamento:
    def test_traduz_os_campos_do_ocs(self):
        m = maquina()
        dados = ocs_service.mapear(m["maquina"], m["detalhes"])

        assert dados["hostname"] == "PC-BNT-001"
        assert dados["numero_serie"] == "ABC123"
        assert dados["marca"] == "Dell"
        assert dados["modelo"] == "Latitude 5420"
        assert dados["so"] == "Windows 11 Pro"
        assert dados["ram_gb"] == 16
        assert dados["armazenamento_gb"] == 256
        assert dados["mac_address"] == "AA:BB:CC:DD:EE:FF"

    def test_nomes_alternativos_de_campo(self):
        """Versões diferentes do OCS usam nomes diferentes — os dois funcionam."""
        det = {"bios": [{"serialnumber": "xyz", "manufacturer": "HP", "model": "ProDesk"}]}
        dados = ocs_service.mapear({"name": "PC-01"}, det)
        assert dados["numero_serie"] == "xyz"
        assert dados["marca"] == "HP"
        assert dados["modelo"] == "ProDesk"
        assert dados["hostname"] == "PC-01"

    def test_bytes_viram_gb(self):
        assert ocs_service._para_gb(str(8 * 1024**3)) == 8
        assert ocs_service._para_gb("0") is None
        assert ocs_service._para_gb("abc") is None
        assert ocs_service._para_gb(None) is None

    def test_serial_placeholder_e_reconhecido(self):
        from app.services.ocs_sync import _serial_placeholder
        assert _serial_placeholder("To be filled by O.E.M.") is True
        assert _serial_placeholder("Default string") is True
        assert _serial_placeholder("VMware-56 4d 12") is True
        assert _serial_placeholder(None) is True
        assert _serial_placeholder("5CG1234ABC") is False


class TestSimulacao:
    def test_simulacao_nao_grava_nada(self, client, auth_headers, ocs):
        _configurar(client, auth_headers)
        antes = client.get("/api/v1/ativos", headers=auth_headers).json()["total"]

        r = client.post("/api/v1/ocs/simular", headers=auth_headers).json()
        assert r["novas"] == 1
        assert "Nada foi gravado" in r["mensagem"]

        depois = client.get("/api/v1/ativos", headers=auth_headers).json()["total"]
        assert depois == antes, "a simulação criou ativo"

    def test_simulacao_nao_entra_no_historico(self, client, auth_headers, ocs):
        _configurar(client, auth_headers)
        client.post("/api/v1/ocs/simular", headers=auth_headers)
        assert client.get("/api/v1/ocs/historico", headers=auth_headers).json()["total"] == 0


class TestSincronizacao:
    def test_cria_ativo_com_os_dados_do_ocs(self, client, auth_headers, ocs):
        pid = _planta(client, auth_headers, "Bonito", "BON")
        _configurar(client, auth_headers, regras_planta=[{"prefixo": "PC-BNT-", "planta_id": pid}])

        r = client.post("/api/v1/ocs/sincronizar", headers=auth_headers).json()
        assert r["novas"] == 1
        assert r["sem_planta"] == 0

        ativos = client.get("/api/v1/ativos", params={"search": "PC-BNT-001"}, headers=auth_headers).json()
        ativo = ativos["items"][0]
        assert ativo["planta_id"] == pid
        assert ativo["numero_serie"] == "ABC123"
        assert ativo["modelo"] == "Latitude 5420"
        assert ativo["marca"] == "Dell"

    def test_maquina_sem_regra_entra_sem_planta(self, client, auth_headers, ocs):
        """Melhor sem planta (para revisar) do que numa planta chutada."""
        _configurar(client, auth_headers, regras_planta=[])

        r = client.post("/api/v1/ocs/sincronizar", headers=auth_headers).json()
        assert r["novas"] == 1
        assert r["sem_planta"] == 1

        ativo = client.get("/api/v1/ativos", params={"search": "PC-BNT-001"}, headers=auth_headers).json()["items"][0]
        assert ativo["planta_id"] is None

    def test_segunda_sincronizacao_atualiza_em_vez_de_duplicar(self, client, auth_headers, ocs):
        _configurar(client, auth_headers)
        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)

        # A máquina mudou de SO e de memória no OCS.
        ocs.maquinas[0]["detalhes"]["os"] = {"OSNAME": "Windows 12"}
        ocs.maquinas[0]["detalhes"]["hardware"]["MEMORY"] = str(32 * 1024**3)

        r = client.post("/api/v1/ocs/sincronizar", headers=auth_headers).json()
        assert r["novas"] == 0
        assert r["atualizadas"] == 1

        total = client.get("/api/v1/ativos", params={"search": "PC-BNT-001"}, headers=auth_headers).json()["total"]
        assert total == 1, "duplicou o ativo na segunda sincronização"

    def test_nao_sobrescreve_planta_nem_patrimonio(self, client, auth_headers, ocs):
        """O ponto central: o OCS manda no técnico, o sistema manda no patrimonial."""
        pid = _planta(client, auth_headers, "Bonito", "BON")
        _configurar(client, auth_headers, regras_planta=[{"prefixo": "PC-BNT-", "planta_id": pid}])

        ativo = client.post("/api/v1/ativos", json={
            "dominio": "ti", "tipo_item": "ativo", "patrimonio": "PATRIMONIO-0421",
            "numero_serie": "ABC123", "modelo": "Antigo",
        }, headers={**auth_headers, "X-Planta-Id": str(pid)}).json()

        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)

        depois = client.get(f"/api/v1/ativos/{ativo['id']}", headers=auth_headers).json()
        assert depois["patrimonio"] == "PATRIMONIO-0421", "o patrimônio foi sobrescrito"
        assert depois["planta_id"] == pid, "a planta foi sobrescrita"
        assert depois["modelo"] == "Latitude 5420", "os dados técnicos deveriam atualizar"

    def test_casamento_pelo_patrimonio_quando_nao_ha_serial(self, client, auth_headers, ocs):
        """Cobre os ativos cadastrados antes da integração (sem serial)."""
        ocs.maquinas[0]["detalhes"]["bios"]["SSN"] = ""
        _configurar(client, auth_headers)

        client.post("/api/v1/ativos", json={
            "dominio": "ti", "tipo_item": "ativo", "patrimonio": "PC-BNT-001",
        }, headers=auth_headers)

        r = client.post("/api/v1/ocs/sincronizar", headers=auth_headers).json()
        assert r["novas"] == 0, "criou duplicata em vez de casar pelo patrimônio"
        assert r["atualizadas"] == 1

    def test_serial_falso_e_ignorado(self, client, auth_headers, ocs):
        ocs.maquinas[0]["detalhes"]["bios"]["SSN"] = "To be filled by O.E.M."
        _configurar(client, auth_headers, ignorar_sem_serial=True)

        r = client.post("/api/v1/ocs/sincronizar", headers=auth_headers).json()
        assert r["novas"] == 0
        assert r["ignoradas"] == 1

    def test_serial_falso_pode_ser_aceito(self, client, auth_headers, ocs):
        """Com a opção desligada, a máquina entra mesmo sem serial confiável."""
        ocs.maquinas[0]["detalhes"]["bios"]["SSN"] = ""
        _configurar(client, auth_headers, ignorar_sem_serial=False)

        r = client.post("/api/v1/ocs/sincronizar", headers=auth_headers).json()
        assert r["novas"] == 1

    def test_filtro_de_hostname(self, client, auth_headers):
        simulado = OCSSimulado([maquina(1, "PC-BNT-001"), maquina(2, "SERVIDOR-01")])
        import app.services.ocs_service as svc
        svc_listar, svc_det = svc.listar_maquinas, svc.detalhes
        svc.listar_maquinas, svc.detalhes = simulado.listar, simulado.detalhes
        try:
            _configurar(client, auth_headers, filtrar_hostname="^PC-")
            r = client.post("/api/v1/ocs/sincronizar", headers=auth_headers).json()
            assert r["novas"] == 1
            assert r["ignoradas"] == 1
        finally:
            svc.listar_maquinas, svc.detalhes = svc_listar, svc_det

    def test_desativado_recusa_sincronizar(self, client, auth_headers, ocs):
        client.put("/api/v1/ocs/config", json={"ativo": False}, headers=auth_headers)
        assert client.post("/api/v1/ocs/sincronizar", headers=auth_headers).status_code == 400


class TestHistoricoEAuditoria:
    def test_sincronizacao_entra_no_historico(self, client, auth_headers, ocs):
        _configurar(client, auth_headers)
        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)

        h = client.get("/api/v1/ocs/historico", headers=auth_headers).json()
        assert h["total"] == 1
        item = h["itens"][0]
        assert item["origem"] == "manual"
        assert item["novas"] == 1
        assert item["sucesso"] is True

    def test_sincronizacao_e_auditada(self, client, auth_headers, ocs):
        _configurar(client, auth_headers)
        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)

        logs = client.get("/api/v1/admin/auditoria", params={"acao": "ocs_sincronizado"},
                          headers=auth_headers).json()["itens"]
        assert logs, "a sincronização não foi auditada"

    def test_config_salva_e_atualiza_ultima_sync(self, client, auth_headers, ocs):
        _configurar(client, auth_headers)
        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)

        cfg = client.get("/api/v1/ocs/config", headers=auth_headers).json()
        assert cfg["ultima_sync_em"]
        assert "nova" in cfg["ultima_sync_resumo"]


class TestAgendador:
    def test_desligado_por_padrao(self):
        from app.services import ocs_agendador
        ocs_agendador.parar()
        assert ocs_agendador.esta_rodando() is False

    def test_inicia_e_para(self):
        from app.services import ocs_agendador
        ocs_agendador.iniciar()
        assert ocs_agendador.esta_rodando() is True
        ocs_agendador.parar()

    def test_nao_cria_duas_linhas_de_execucao(self):
        from app.services import ocs_agendador
        ocs_agendador.iniciar()
        ocs_agendador.iniciar()  # a segunda não deve criar outra
        assert ocs_agendador.esta_rodando() is True
        ocs_agendador.parar()

    def test_intervalo_configuravel(self, client, auth_headers):
        r = _configurar(client, auth_headers, sync_automatica=True, sync_intervalo_minutos=12)
        assert r["sync_automatica"] is True
        assert r["sync_intervalo_minutos"] == 12


class TestTiposDeRegra:
    """A planta pode estar no MEIO do hostname.

    No parque do usuário o nome é `DTAT0001`: D = desktop, TAT = planta,
    0001 = numeração. "Começa com" não serve — a sigla da planta fica no meio.
    """

    def test_contem_encontra_a_sigla_no_meio(self):
        regras = [{"prefixo": "TAT", "tipo": "contem", "planta_id": 1},
                  {"prefixo": "BNT", "tipo": "contem", "planta_id": 2}]
        for hostname in ("DTAT0001", "NTAT0002", "RTAT0003"):
            assert ocs_service.planta_por_hostname(regras, hostname) == 1, hostname
        for hostname in ("DBNT0001", "NBNT9999", "RBNT0001"):
            assert ocs_service.planta_por_hostname(regras, hostname) == 2, hostname

    def test_contem_nao_casa_o_que_nao_tem_a_sigla(self):
        regras = [{"prefixo": "TAT", "tipo": "contem", "planta_id": 1}]
        assert ocs_service.planta_por_hostname(regras, "SERVIDOR-01") is None
        assert ocs_service.planta_por_hostname(regras, "SW-CORE") is None

    def test_contem_ignora_caixa(self):
        regras = [{"prefixo": "tat", "tipo": "contem", "planta_id": 1}]
        assert ocs_service.planta_por_hostname(regras, "dtat0001") == 1

    def test_comeca_com_continua_funcionando(self):
        regras = [{"prefixo": "PC-BNT-", "tipo": "comeca_com", "planta_id": 5}]
        assert ocs_service.planta_por_hostname(regras, "PC-BNT-001") == 5
        assert ocs_service.planta_por_hostname(regras, "PC-TAT-001") is None

    def test_regra_antiga_sem_tipo_e_tratada_como_comeca_com(self):
        """Configurações gravadas antes dos tipos não podem quebrar."""
        regras = [{"prefixo": "PC-BNT-", "planta_id": 5}]
        assert ocs_service.planta_por_hostname(regras, "PC-BNT-001") == 5

    def test_regex_da_controle_total(self):
        """Com regex dá para exigir o formato inteiro: tipo + planta + número."""
        regras = [{"prefixo": r"^[DNR]TAT\d+$", "tipo": "regex", "planta_id": 1}]
        assert ocs_service.planta_por_hostname(regras, "DTAT0001") == 1
        assert ocs_service.planta_por_hostname(regras, "NTAT0009") == 1
        assert ocs_service.planta_por_hostname(regras, "XTAT0001") is None
        assert ocs_service.planta_por_hostname(regras, "DTAT0001-X") is None

    def test_regex_invalida_nao_derruba_nada(self):
        regras = [{"prefixo": "[invalida(", "tipo": "regex", "planta_id": 1},
                  {"prefixo": "BNT", "tipo": "contem", "planta_id": 2}]
        # A regra quebrada é ignorada e a seguinte assume.
        assert ocs_service.planta_por_hostname(regras, "DBNT0001") == 2

    def test_primeira_regra_que_casa_decide(self):
        regras = [{"prefixo": "TAT", "tipo": "contem", "planta_id": 1},
                  {"prefixo": "DTAT", "tipo": "contem", "planta_id": 9}]
        assert ocs_service.planta_por_hostname(regras, "DTAT0001") == 1

    def test_regra_que_casa_devolve_a_regra_inteira(self):
        regras = [{"prefixo": "TAT", "tipo": "contem", "planta_id": 1}]
        r = ocs_service.regra_que_casa(regras, "DTAT0001")
        assert r is not None and r["planta_id"] == 1
        assert ocs_service.regra_que_casa(regras, "OUTRO") is None

    def test_sincronizacao_usa_a_regra_contem(self, client, auth_headers, ocs):
        """Ponta a ponta: hostname DTAT0001 cai na planta certa."""
        pid = _planta(client, auth_headers, "Tatuí", "TAT")
        ocs.maquinas[0]["maquina"]["NAME"] = "DTAT0001"
        _configurar(client, auth_headers,
                    regras_planta=[{"prefixo": "TAT", "tipo": "contem", "planta_id": pid}])

        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)
        ativo = client.get("/api/v1/ativos", params={"search": "DTAT0001"}, headers=auth_headers).json()["items"][0]
        assert ativo["planta_id"] == pid

    def test_regex_invalida_e_recusada_ao_salvar(self, client, auth_headers):
        pid = _planta(client, auth_headers, "Tatuí", "TAT")
        r = client.put("/api/v1/ocs/config",
                       json={"regras_planta": [{"prefixo": "[quebrada(", "tipo": "regex", "planta_id": pid}]},
                       headers=auth_headers)
        assert r.status_code == 400
        assert "regular" in r.json()["detail"].lower()

    def test_tipo_invalido_e_recusado(self, client, auth_headers):
        pid = _planta(client, auth_headers, "Tatuí", "TAT")
        r = client.put("/api/v1/ocs/config",
                       json={"regras_planta": [{"prefixo": "X", "tipo": "inventado", "planta_id": pid}]},
                       headers=auth_headers)
        assert r.status_code == 400

    def test_tipo_e_gravado_junto_da_regra(self, client, auth_headers):
        pid = _planta(client, auth_headers, "Tatuí", "TAT")
        r = _configurar(client, auth_headers,
                        regras_planta=[{"prefixo": "TAT", "tipo": "contem", "planta_id": pid}])
        assert r["regras_planta"][0]["tipo"] == "contem"


class TestIntervaloPersonalizado:
    """O intervalo é guardado em MINUTOS, o que permite valores curtos.

    Antes a unidade era hora, e 15 ou 30 minutos eram impossíveis de representar.
    """

    def test_padrao_e_60_minutos(self, client, auth_headers):
        assert client.get("/api/v1/ocs/config", headers=auth_headers).json()["sync_intervalo_minutos"] == 60

    @pytest.mark.parametrize("minutos", [15, 30, 60, 120, 240, 480, 720, 1440])
    def test_multiplos_aceitos(self, client, auth_headers, minutos):
        r = _configurar(client, auth_headers, sync_automatica=True, sync_intervalo_minutos=minutos)
        assert r["sync_intervalo_minutos"] == minutos

    @pytest.mark.parametrize("minutos", [45, 90, 200, 360, 2880, 10080])
    def test_valores_personalizados(self, client, auth_headers, minutos):
        """Qualquer valor dentro da faixa é aceito, não só os múltiplos prontos."""
        r = _configurar(client, auth_headers, sync_intervalo_minutos=minutos)
        assert r["sync_intervalo_minutos"] == minutos

    @pytest.mark.parametrize("invalido", [0, 1, 4, -10, 10081, 99999])
    def test_fora_da_faixa_e_recusado(self, client, auth_headers, invalido):
        r = client.put("/api/v1/ocs/config", json={"sync_intervalo_minutos": invalido}, headers=auth_headers)
        assert r.status_code == 422

    def test_limites_da_faixa(self, client, auth_headers):
        """5 minutos e 7 dias são os extremos permitidos."""
        assert _configurar(client, auth_headers, sync_intervalo_minutos=5)["sync_intervalo_minutos"] == 5
        assert _configurar(client, auth_headers, sync_intervalo_minutos=10080)["sync_intervalo_minutos"] == 10080

    def test_conversao_do_campo_antigo_em_horas(self, client, auth_headers):
        """Quem já tinha configurado em horas não perde a configuração.

        A versão anterior media o intervalo em horas; o valor antigo é
        convertido uma única vez e o campo legado é zerado.
        """
        from app.database import get_db
        from app.services.config_service import obter_config_ocs

        # A sessão do próprio teste — não a do banco real.
        sessao = next(client.app.dependency_overrides[get_db]())
        cfg = obter_config_ocs(sessao)
        cfg.sync_intervalo_horas = 4      # valor da versão anterior
        cfg.sync_intervalo_minutos = 60   # ainda no padrão
        sessao.commit()

        convertido = obter_config_ocs(sessao)
        assert convertido.sync_intervalo_minutos == 240, "4 horas deveriam virar 240 minutos"
        assert not convertido.sync_intervalo_horas, "o campo antigo deveria ser zerado"

    def test_agendador_usa_minutos(self):
        """O agendador precisa converter minutos para segundos corretamente."""
        import inspect

        from app.services import ocs_agendador

        fonte = inspect.getsource(ocs_agendador._laco)
        assert "sync_intervalo_minutos" in fonte
        assert "* 60" in fonte, "faltou converter minutos para segundos"


class TestAvisoDeProblema:
    """Falha na sincronização precisa chegar no sino do administrador.

    Antes, um erro só aparecia para quem clicasse em "Sincronizar" — se o OCS
    caísse durante a madrugada, ninguém ficava sabendo e o inventário parava
    de atualizar em silêncio.
    """

    @pytest.fixture
    def ocs_quebrado(self, monkeypatch):
        def falha(cfg):
            raise RuntimeError("Connection refused")
        monkeypatch.setattr(ocs_service, "listar_maquinas", falha)

    def _avisos_ocs(self, client, auth_headers):
        itens = client.get("/api/v1/notificacoes", headers=auth_headers).json()["itens"]
        return [i for i in itens if i["tipo"].startswith("ocs")]

    def test_sem_integracao_nao_alerta(self, client, auth_headers):
        assert self._avisos_ocs(client, auth_headers) == []

    def test_falha_na_sincronizacao_alerta(self, client, auth_headers, ocs_quebrado):
        _configurar(client, auth_headers)
        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)

        avisos = self._avisos_ocs(client, auth_headers)
        assert avisos, "a falha não gerou aviso no sino"
        falha = next(a for a in avisos if a["tipo"] == "ocs_falha")
        assert falha["nivel"] == "erro"
        assert "Falha na sincronização" in falha["titulo"]
        assert "Connection refused" in falha["detalhe"]
        assert falha["painel"] == "ocs", "o aviso deve levar para a aba do OCS"

    def test_falha_repetida_conta_as_vezes(self, client, auth_headers, ocs_quebrado):
        _configurar(client, auth_headers)
        for _ in range(3):
            client.post("/api/v1/ocs/sincronizar", headers=auth_headers)

        falha = next(a for a in self._avisos_ocs(client, auth_headers) if a["tipo"] == "ocs_falha")
        assert "3 vezes" in falha["titulo"]

    def test_falha_entra_no_historico(self, client, auth_headers, ocs_quebrado):
        """A falha precisa ficar registrada, não só avisada."""
        _configurar(client, auth_headers)
        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)

        h = client.get("/api/v1/ocs/historico", headers=auth_headers).json()
        assert h["total"] == 1
        assert h["itens"][0]["sucesso"] is False
        assert h["itens"][0]["erros"] == 1

    def test_sucesso_depois_da_falha_limpa_o_aviso(self, client, auth_headers, monkeypatch):
        """Resolver o problema tem que tirar o alerta do sino."""
        chamadas = {"n": 0}

        def as_vezes_falha(cfg):
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise RuntimeError("Connection refused")
            return [maquina()["maquina"]]

        def detalhes_ok(cfg, mid):
            return maquina()["detalhes"]

        monkeypatch.setattr(ocs_service, "listar_maquinas", as_vezes_falha)
        monkeypatch.setattr(ocs_service, "detalhes", detalhes_ok)

        _configurar(client, auth_headers)
        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)
        assert self._avisos_ocs(client, auth_headers), "deveria ter avisado da falha"

        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)
        assert not [a for a in self._avisos_ocs(client, auth_headers) if a["tipo"] == "ocs_falha"], \
            "o aviso de falha deveria sair depois de um sucesso"

    def test_integracao_desligada_nao_alerta(self, client, auth_headers, ocs_quebrado):
        """Erro guardado de uma integração já desligada não pode alarmar sempre."""
        _configurar(client, auth_headers)
        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)
        assert self._avisos_ocs(client, auth_headers)

        client.put("/api/v1/ocs/config", json={"ativo": False}, headers=auth_headers)
        assert self._avisos_ocs(client, auth_headers) == []

    def test_sincronizacao_atrasada_alerta(self, client, auth_headers, ocs):
        from datetime import datetime, timedelta, timezone

        from app.database import get_db
        from app.services.config_service import obter_config_ocs

        _configurar(client, auth_headers, sync_automatica=True, sync_intervalo_minutos=15)
        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)

        # "Volta no tempo" a última sincronização em 3 horas (o dobro de 15 min
        # já teria passado há muito tempo).
        sessao = next(client.app.dependency_overrides[get_db]())
        cfg = obter_config_ocs(sessao)
        cfg.ultima_sync_em = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
        sessao.commit()

        avisos = [a for a in self._avisos_ocs(client, auth_headers) if a["tipo"] == "ocs_atrasada"]
        assert avisos, "o atraso não gerou aviso"
        assert avisos[0]["nivel"] == "urgente"

    def test_atraso_pequeno_nao_alerta(self, client, auth_headers, ocs):
        """Passar um pouquinho do intervalo é normal — não vira alarme."""
        _configurar(client, auth_headers, sync_automatica=True, sync_intervalo_minutos=60)
        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)

        assert not [a for a in self._avisos_ocs(client, auth_headers) if a["tipo"] == "ocs_atrasada"]

    def test_maquinas_sem_planta_alertam(self, client, auth_headers, ocs):
        _configurar(client, auth_headers, regras_planta=[])
        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)

        avisos = [a for a in self._avisos_ocs(client, auth_headers) if a["tipo"] == "ocs_sem_planta"]
        assert avisos, "máquinas sem planta deveriam avisar"
        assert avisos[0]["nivel"] == "info"
        assert "1" in avisos[0]["titulo"]

    def test_nao_admin_nao_recebe_aviso_do_ocs(self, client, auth_headers, ocs_quebrado):
        """Integração é assunto do administrador."""
        _configurar(client, auth_headers)
        client.post("/api/v1/ocs/sincronizar", headers=auth_headers)

        client.post("/api/v1/usuarios",
                    json={"nome": "Tec", "email": "tec.aviso@teste.com", "papel": "ti", "senha": "senha123"},
                    headers=auth_headers)
        login = client.post("/api/v1/auth/login", data={"username": "tec.aviso@teste.com", "password": "senha123"})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}

        itens = client.get("/api/v1/notificacoes", headers=h).json()["itens"]
        assert not [i for i in itens if i["tipo"].startswith("ocs")]
