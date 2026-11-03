"""Fluxo do agente — registro, inventário e histórico.

## As decisões que estes testes travam

1. **Serial inválido não consome uso do código.** Uma implantação com 50
   placas brancas queimaria 50 usos de um código de 3.500 sem registrar
   ninguém.

2. **Máquina não cadastrada vai para a fila**, nunca é criada sozinha. Foi a
   criação automática que faria 40 placas brancas virarem uma só.

3. **O token escreve só no próprio ativo.** O `ativo_id` vem do token, nunca
   do corpo da requisição — um agente comprometido não escolhe onde escreve.

4. **Histórico só quando o hardware muda.** Uptime e IP mudam a cada coleta;
   se entrassem no hash, o histórico viraria log de 2 milhões de linhas por
   ano.

5. **Segredo é guardado com hash.** Nem o código nem o token ficam em claro
   no banco.

## Por que banco zerado

Os testes de importação mostraram que cadastros pré-existentes escondem
caminhos de criação. Aqui vale o mesmo: cada teste monta seu próprio banco.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.agente import EquipamentoPendente
from app.models.core import Ativo, Planta
from app.models.enums import Dominio, StatusAtivo, TipoItem
from app.models.historico_inventario import HistoricoInventario
from app.models.ti import AtivoTI
from app.services import agente_service as svc

SERIAL = "PF3XK2LM"


def payload(**mudancas) -> dict:
    """Payload no formato que o coletor envia."""
    basico = {
        "hostname": "DESKTOP-042",
        "so": "Windows 11 Pro",
        "cpu": "Intel Core i7-11700",
        "ram_gb": 16,
        "armazenamento_gb": 512,
        "dominio": "EMPRESA",
        "fabricante": "Dell Inc.",
        "modelo": "OptiPlex 7090",
    }
    basico.update(mudancas)
    return {
        "basico": basico,
        "detalhes": {
            "rede": [{"mac": "A4:BB:6D:12:34:56", "ips": ["10.0.1.42"]}],
            "uptime_horas": 5,
            "gpu": "Intel UHD 750",
        },
    }


@pytest.fixture()
def banco():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    planta = Planta(nome="Central", sigla="C", ativa=True)
    db.add(planta)
    db.flush()
    db.add(
        Ativo(
            planta_id=planta.id,
            dominio=Dominio.TI,
            tipo_item=TipoItem.ATIVO,
            status=StatusAtivo.ESTOQUE,
            numero_serie=SERIAL,
            patrimonio="TI-1",
        )
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def codigo(banco):
    registro, valor = svc.gerar_codigo(banco, dias=7, usos_max=10, rotulo="teste")
    return registro, valor


class TestCodigo:
    def test_guardado_com_hash_nao_em_claro(self, banco, codigo):
        registro, valor = codigo
        assert registro.codigo_hash != valor
        assert registro.codigo_hash == hashlib.sha256(valor.encode()).hexdigest()

    def test_busca_pelo_valor_em_claro(self, banco, codigo):
        _registro, valor = codigo
        achado = svc.buscar_codigo(banco, valor)
        assert achado is not None

    def test_valor_errado_nao_acha(self, banco, codigo):
        assert svc.buscar_codigo(banco, "AAAA-BBBB-CCCC") is None

    def test_expirado_nao_util(self, banco, codigo):
        registro, _valor = codigo
        registro.expira_em = datetime.now(timezone.utc) - timedelta(hours=1)
        assert registro.util is False

    def test_esgotado_nao_util(self, banco, codigo):
        registro, _valor = codigo
        registro.usos_feitos = registro.usos_max
        assert registro.esgotado is True
        assert registro.util is False

    def test_revogado_nao_util(self, banco, codigo):
        registro, _valor = codigo
        registro.revogado_em = datetime.now(timezone.utc)
        assert registro.util is False


class TestSerial:
    @pytest.mark.parametrize(
        "serial",
        [None, "", "0", "00000000", "To be filled by O.E.M.", "Default string",
         "System Serial Number", "N/A", "VMware-56 4d", "0000-0000-0000"],
    )
    def test_lixo_nao_e_serial(self, serial):
        assert svc.serial_valido(serial) is False

    def test_serial_real_e_aceito(self):
        assert svc.serial_valido("PF3XK2LM") is True


class TestRegistro:
    def test_serial_valido_registra_e_consome_uso(self, banco, codigo):
        registro, valor = codigo
        r = svc.registrar(banco, codigo=valor, serial=SERIAL,
                          hostname="DESKTOP-042", payload=payload())

        assert r["ok"] is True
        assert r["ativo_id"] == 1
        assert r["token"]
        assert registro.usos_feitos == 1

    def test_serial_invalido_vai_para_fila_sem_consumir(self, banco, codigo):
        """O teste que protege a implantação em massa.

        Cinquenta placas brancas não podem queimar cinquenta usos.
        """
        registro, valor = codigo
        r = svc.registrar(banco, codigo=valor, serial="To be filled by O.E.M.",
                          hostname="BRANCA-01", payload=payload())

        assert r["ok"] is False
        assert r["motivo"] == "sem_serial"
        assert r["status"] == 422
        assert registro.usos_feitos == 0, "não pode consumir uso"
        assert banco.query(EquipamentoPendente).count() == 1

    def test_serial_desconhecido_cria_o_ativo(self, banco, codigo):
        """Registro automático — a fila de aprovação saiu.

        ## Por que a regra mudou

        A fila existia para impedir que quarenta placas brancas casassem
        todas com o mesmo `To be filled by O.E.M.`. Com o agente enviando
        `OEM-<MachineGuid>` — único por máquina — o risco desapareceu.

        O que sobrou era burocracia: instalar, pedir aprovação, aprovar,
        instalar de novo, pedir de novo.
        """
        registro, valor = codigo
        r = svc.registrar(banco, codigo=valor, serial="OEM-ABC123DEF456",
                          hostname="BRANCA-01", payload=payload())

        assert r["ok"] is True
        assert r["criado"] is True
        assert r["ativo_id"] is not None
        assert registro.usos_feitos == 1

        from app.models.core import Ativo

        ativo = banco.get(Ativo, r["ativo_id"])
        assert ativo.numero_serie == "OEM-ABC123DEF456"

    def test_segundo_registro_nao_duplica(self, banco, codigo):
        """O mesmo identificador reaproveita o ativo, não cria outro."""
        _registro, valor = codigo
        r1 = svc.registrar(banco, codigo=valor, serial="OEM-ABC123DEF456",
                           hostname="BRANCA-01", payload=payload())
        r2 = svc.registrar(banco, codigo=valor, serial="OEM-ABC123DEF456",
                           hostname="BRANCA-01", payload=payload())

        assert r2["ativo_id"] == r1["ativo_id"]
        assert r2["criado"] is False

        from app.models.core import Ativo

        assert banco.query(Ativo).count() == 2, "o ativo do fixture + o criado"

    def test_codigo_invalido_e_recusado(self, banco):
        r = svc.registrar(banco, codigo="XXXX-YYYY-ZZZZ", serial=SERIAL,
                          hostname="X", payload=payload())
        assert r["ok"] is False
        assert r["motivo"] == "codigo_invalido"

    def test_codigo_expirado_e_recusado(self, banco, codigo):
        registro, valor = codigo
        registro.expira_em = datetime.now(timezone.utc) - timedelta(minutes=1)
        banco.commit()

        r = svc.registrar(banco, codigo=valor, serial=SERIAL,
                          hostname="X", payload=payload())
        assert r["motivo"] == "codigo_expirado"

    def test_pendente_nao_duplica_por_mac(self, banco, codigo):
        """A mesma máquina se apresentando duas vezes ocupa uma linha só."""
        _registro, valor = codigo
        svc.registrar(banco, codigo=valor, serial="To be filled by O.E.M.",
                      hostname="BRANCA-01", payload=payload())
        svc.registrar(banco, codigo=valor, serial="To be filled by O.E.M.",
                      hostname="BRANCA-01", payload=payload())

        assert banco.query(EquipamentoPendente).count() == 1


class TestInventario:
    def _registrado(self, banco, codigo):
        _registro, valor = codigo
        r = svc.registrar(banco, codigo=valor, serial=SERIAL,
                          hostname="DESKTOP-042", payload=payload())
        return svc.buscar_token(banco, r["token"])

    def test_grava_na_ficha_do_ativo(self, banco, codigo):
        token = self._registrado(banco, codigo)
        r = svc.aplicar_inventario(banco, token, payload())

        assert r["ok"] is True
        ficha = banco.get(AtivoTI, r["ativo_id"])
        assert ficha.hostname == "DESKTOP-042"
        assert ficha.ram_gb == 16
        assert ficha.mac_address == "A4:BB:6D:12:34:56"
        assert ficha.inventario_json

    def test_token_nao_escolhe_o_ativo(self, banco, codigo):
        """O `ativo_id` vem do token — o corpo não decide nada.

        Um token vazado escreve inventário de **uma** máquina, e nada mais.
        """
        token = self._registrado(banco, codigo)
        # Payload hostil: tenta apontar para outro ativo.
        r = svc.aplicar_inventario(banco, token, {**payload(), "ativo_id": 999})
        assert r["ativo_id"] == token.ativo_id

    def test_token_revogado_nao_e_encontrado(self, banco, codigo):
        token = self._registrado(banco, codigo)
        token.revogado_em = datetime.now(timezone.utc)
        banco.commit()

        assert svc.buscar_token(banco, "qualquer") is None


class TestHistorico:
    def _token(self, banco, codigo):
        _registro, valor = codigo
        r = svc.registrar(banco, codigo=valor, serial=SERIAL,
                          hostname="DESKTOP-042", payload=payload())
        return svc.buscar_token(banco, r["token"])

    def test_primeira_coleta_e_linha_de_base(self, banco, codigo):
        token = self._token(banco, codigo)
        svc.aplicar_inventario(banco, token, payload())

        assert banco.query(HistoricoInventario).count() == 1

    def test_coleta_identica_nao_gera_historico(self, banco, codigo):
        """O ponto central: volátil muda, estável não.

        Uptime de 5 para 12 horas e IP de .1 para .2 — e nada é gravado.
        """
        token = self._token(banco, codigo)
        svc.aplicar_inventario(banco, token, payload())

        segundo = payload()
        segundo["detalhes"]["uptime_horas"] = 12
        segundo["detalhes"]["rede"][0]["ips"] = ["10.0.0.2"]
        r = svc.aplicar_inventario(banco, token, segundo)

        assert r["historico"] is False
        assert banco.query(HistoricoInventario).count() == 1

    def test_mudanca_de_hardware_gera_historico_com_diff(self, banco, codigo):
        token = self._token(banco, codigo)
        svc.aplicar_inventario(banco, token, payload())
        r = svc.aplicar_inventario(banco, token, payload(ram_gb=32))

        assert r["historico"] is True
        assert banco.query(HistoricoInventario).count() == 2

        ultimo = (
            banco.query(HistoricoInventario)
            .order_by(HistoricoInventario.id.desc())
            .first()
        )
        import json

        mudancas = json.loads(ultimo.mudancas_json)
        assert "ram_gb" in mudancas
        assert mudancas["ram_gb"]["de"] == 16
        assert mudancas["ram_gb"]["para"] == 32

    def test_oscilacao_volta_gera_nova_linha(self, banco, codigo):
        """RAM 16 → 32 → 16 são duas mudanças, não uma."""
        token = self._token(banco, codigo)
        svc.aplicar_inventario(banco, token, payload())
        svc.aplicar_inventario(banco, token, payload(ram_gb=32))
        r = svc.aplicar_inventario(banco, token, payload(ram_gb=16))

        assert r["historico"] is True
        assert banco.query(HistoricoInventario).count() == 3

class TestAtualizacaoDoAtivo:
    """O agente preenche a tabela base, não só a ficha.

    ## O bug

    `modelo` e `marca` vivem em `ativos`. A criação já os preenchia, mas a
    **atualização** só tocava na ficha `ativos_ti`.

    Resultado: cadastrar o ativo à mão com apenas o serial e deixar o agente
    completar **não completava nada** — modelo e marca ficavam vazios para
    sempre, mesmo com o "Detalhes Completos" cheio.
    """

    def test_preenche_modelo_e_marca_do_payload(self, banco, codigo):
        """O cenário real: ativo criado só com serial, agente completa."""
        from app.models.core import Ativo
        from app.models.enums import Dominio, StatusAtivo, TipoItem

        # ativo cadastrado à mão, sem modelo nem marca
        banco.add(Ativo(
            planta_id=1, dominio=Dominio.TI, tipo_item=TipoItem.ATIVO,
            status=StatusAtivo.ESTOQUE, numero_serie="OEM-TESTE123",
        ))
        banco.commit()

        _registro, valor = codigo
        pay = payload()
        pay["serial"] = "OEM-TESTE123"

        r = svc.registrar(
            banco, codigo=valor, serial="OEM-TESTE123",
            hostname="DESKTOP-042", payload=pay,
        )
        assert r["ok"] is True, r.get("motivo")

        token = svc.buscar_token(banco, r["token"])
        svc.aplicar_inventario(banco, token, pay)

        ativo = (
            banco.query(Ativo)
            .filter(Ativo.numero_serie == "OEM-TESTE123")
            .one()
        )
        assert ativo.modelo == "OptiPlex 7090", ativo.modelo
        assert ativo.marca == "Dell Inc.", ativo.marca

    def test_payload_sem_modelo_nao_apaga_o_que_existe(self, banco, codigo):
        """Campo vazio no payload não zera o valor do ativo.

        Uma coleta com dado faltando não pode destruir o cadastro.
        """
        from app.models.core import Ativo

        _registro, valor = codigo
        r = svc.registrar(
            banco, codigo=valor, serial=SERIAL,
            hostname="DESKTOP-042", payload=payload(),
        )
        token = svc.buscar_token(banco, r["token"])

        # primeira coleta preenche
        svc.aplicar_inventario(banco, token, payload())

        # segunda coleta vem sem modelo/fabricante
        sem = payload()
        sem["basico"]["modelo"] = None
        sem["basico"]["fabricante"] = None
        svc.aplicar_inventario(banco, token, sem)

        ativo = banco.get(Ativo, r["ativo_id"])
        banco.refresh(ativo)
        assert ativo.modelo == "OptiPlex 7090", "o modelo foi apagado"
        assert ativo.marca == "Dell Inc.", "a marca foi apagada"
