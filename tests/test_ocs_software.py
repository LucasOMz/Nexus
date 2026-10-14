"""Coleta do software instalado no OCS.

## O que estes testes protegem

A coleta conversa com um servidor externo, e o formato da resposta varia
entre versões do OCS. O que não pode variar é o **resultado no banco**:

- programa desinstalado **sai** do relatório (substituir, não acumular);
- falha numa máquina **não derruba** a coleta inteira;
- o nome é guardado **como veio**, para o padrão poder ser corrigido depois.

O OCS é simulado — nenhum teste toca a rede.
"""
from __future__ import annotations

import pytest

from app.services import ocs_software as o


class ClienteFalso:
    """Substitui o cliente HTTP do OCS.

    Devolve o que for programado por `maquina_id`. Se a chave não existir,
    simula falha — é o caso de máquina que não responde.
    """

    def __init__(self, respostas: dict, falhar: set | None = None):
        self.respostas = respostas
        self.falhar = falhar or set()

    def get(self, caminho):
        # `/ocsapi/v1/computer/{id}/software`
        partes = caminho.strip("/").split("/")
        maquina = partes[3]
        if maquina in self.falhar:
            raise RuntimeError("máquina não respondeu")

        class R:
            status_code = 200

            def __init__(self, dados):
                self._d = dados

            def json(self):
                return self._d

        return R(self.respostas.get(maquina, []))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def cfg():
    return object()


@pytest.fixture
def db_session(client):
    from app.database import get_db
    from app.main import app

    return next(app.dependency_overrides[get_db]())


def _maquina(db, ocs_id, patrimonio):
    from app.models.core import Ativo, Planta
    from app.models.ti import AtivoTI

    planta = db.query(Planta).first()
    a = Ativo(dominio="ti", tipo_item="ativo", patrimonio=patrimonio, numero_serie=f"NS-{patrimonio}",
              planta_id=planta.id if planta else None, status="estoque")
    db.add(a)
    db.flush()
    db.add(AtivoTI(ativo_id=a.id, ocs_id=ocs_id, hostname=f"H{ocs_id}"))
    db.commit()
    return a


def _software(db, nome, padroes):
    from app.models.software import Software

    s = Software(nome=nome, padroes=padroes)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


class TestExtracaoDoNome:
    """O OCS varia o rótulo entre versões e entre agentes."""

    @pytest.mark.parametrize("item", [
        {"name": "Google Chrome"},
        {"NAME": "Google Chrome"},
        {"Name": "Google Chrome"},
        {"pubname": "Google Chrome"},
        {"software": "Google Chrome"},
    ])
    def test_le_as_variacoes(self, item):
        assert o._nome(item) == "Google Chrome"

    def test_nome_vazio_e_ignorado(self):
        assert o._nome({"name": "   "}) is None
        assert o._nome({}) is None

    def test_versao_e_fabricante(self):
        item = {"name": "X", "version": "1.2", "publisher": "ACME"}
        assert o._versao(item) == "1.2"
        assert o._fabricante(item) == "ACME"


class TestListar:
    def test_tolera_falha_da_maquina(self, cfg, monkeypatch):
        """Uma máquina que não responde não pode derrubar a coleta.

        Devolve **`None`**, e não `[]`: falha de comunicação é diferente de
        resposta válida com zero programas. A distinção decide se o snapshot
        anterior é preservado ou apagado — ver `listar_softwares`.
        """
        monkeypatch.setattr(o.ocs_service, "_cliente",
                            lambda c: ClienteFalso({}, falhar={"9"}))
        assert o.listar_softwares(cfg, "9") is None

    def test_aceita_lista_direta(self, cfg, monkeypatch):
        monkeypatch.setattr(o.ocs_service, "_cliente",
                            lambda c: ClienteFalso({"1": [{"name": "X"}]}))
        assert o.listar_softwares(cfg, "1") == [{"name": "X"}]

    def test_aceita_embrulhado(self, cfg, monkeypatch):
        """Algumas versões devolvem `{"software": [...]}`."""
        monkeypatch.setattr(o.ocs_service, "_cliente",
                            lambda c: ClienteFalso({"1": {"software": [{"name": "X"}]}}))
        assert o.listar_softwares(cfg, "1") == [{"name": "X"}]

    def test_formato_inesperado_devolve_vazio(self, cfg, monkeypatch):
        monkeypatch.setattr(o.ocs_service, "_cliente",
                            lambda c: ClienteFalso({"1": "lixo"}))
        assert o.listar_softwares(cfg, "1") == []


class TestColeta:
    def test_grava_e_reconhece(self, db_session, cfg, monkeypatch):
        _maquina(db_session, "1", "PC-1")
        s = _software(db_session, "Chrome", "chrome*")

        monkeypatch.setattr(o.ocs_service, "_cliente", lambda c: ClienteFalso({
            "1": [{"name": "Google Chrome", "version": "120.0"}],
        }))

        r = o.coletar(db_session, cfg)
        assert r.instalados == 1
        assert r.reconhecidos == 1

        from app.models.software import SoftwareInstalado

        reg = db_session.query(SoftwareInstalado).first()
        assert reg.nome == "Google Chrome"      # o nome CRU, como veio
        assert reg.software_id == s.id
        assert reg.versao == "120.0"

    def test_nao_reconhecido_fica_sem_vinculo(self, db_session, cfg, monkeypatch):
        _maquina(db_session, "1", "PC-1")
        _software(db_session, "Chrome", "chrome*")

        monkeypatch.setattr(o.ocs_service, "_cliente", lambda c: ClienteFalso({
            "1": [{"name": "WinRAR 6.24"}],
        }))

        r = o.coletar(db_session, cfg)
        assert r.instalados == 1
        assert r.reconhecidos == 0

        from app.models.software import SoftwareInstalado

        assert db_session.query(SoftwareInstalado).first().software_id is None

    def test_substitui_e_nao_acumula(self, db_session, cfg, monkeypatch):
        """Programa desinstalado precisa SAIR do relatório.

        Se as coletas somassem, a conformidade acusaria instalações que não
        existem mais — e o número só cresceria a cada rodada.
        """
        _maquina(db_session, "1", "PC-1")
        from app.models.software import SoftwareInstalado

        monkeypatch.setattr(o.ocs_service, "_cliente", lambda c: ClienteFalso({
            "1": [{"name": "Chrome"}, {"name": "WinRAR"}],
        }))
        o.coletar(db_session, cfg)
        assert db_session.query(SoftwareInstalado).count() == 2

        # O WinRAR foi desinstalado, e o Chrome subiu de versão.
        monkeypatch.setattr(o.ocs_service, "_cliente", lambda c: ClienteFalso({
            "1": [{"name": "Chrome"}],
        }))
        o.coletar(db_session, cfg)

        restantes = db_session.query(SoftwareInstalado).all()
        assert len(restantes) == 1, "as coletas acumularam"
        assert restantes[0].nome == "Chrome"

    def test_nao_duplica_o_mesmo_programa(self, db_session, cfg, monkeypatch):
        """O OCS repete atualizações lado a lado (`Chrome` e `Chrome 120`)."""
        _maquina(db_session, "1", "PC-1")
        monkeypatch.setattr(o.ocs_service, "_cliente", lambda c: ClienteFalso({
            "1": [{"name": "Chrome", "version": "120"},
                  {"name": "Chrome", "version": "120"}],
        }))

        r = o.coletar(db_session, cfg)
        assert r.instalados == 1

    def test_uma_maquina_falhando_nao_para_as_outras(self, db_session, cfg, monkeypatch):
        _maquina(db_session, "1", "PC-1")
        _maquina(db_session, "2", "PC-2")
        _maquina(db_session, "3", "PC-3")

        monkeypatch.setattr(o.ocs_service, "_cliente", lambda c: ClienteFalso(
            {"1": [{"name": "A"}], "3": [{"name": "C"}]}, falhar={"2"},
        ))

        r = o.coletar(db_session, cfg)
        assert r.maquinas == 3
        assert r.com_software == 2
        assert r.falhas == 1
        assert r.instalados == 2

    def test_limite_para_testar_antes_do_parque(self, db_session, cfg, monkeypatch):
        for i in range(5):
            _maquina(db_session, str(i), f"PC-{i}")

        monkeypatch.setattr(o.ocs_service, "_cliente",
                            lambda c: ClienteFalso({str(i): [{"name": "X"}] for i in range(5)}))

        r = o.coletar(db_session, cfg, limite=2)
        assert r.maquinas == 2

    def test_maquina_sem_ativo_nao_entra(self, db_session, cfg, monkeypatch):
        """Sem o ativo correspondente não há onde pendurar o software."""
        _maquina(db_session, "1", "PC-1")
        monkeypatch.setattr(o.ocs_service, "_cliente",
                            lambda c: ClienteFalso({"1": [{"name": "X"}]}))

        r = o.coletar(db_session, cfg)
        assert r.maquinas == 1


class TestReconhecimento:
    def test_corrigir_o_padrao_alcanca_o_que_ja_foi_coletado(self, db_session, cfg, monkeypatch):
        """Sem isto, a correção só valeria na PRÓXIMA coleta — e o operador
        concluiria que o ajuste não funcionou."""
        _maquina(db_session, "1", "PC-1")
        s = _software(db_session, "Office", "padrao-que-nao-casa")

        monkeypatch.setattr(o.ocs_service, "_cliente",
                            lambda c: ClienteFalso({"1": [{"name": "Microsoft Office 2021"}]}))
        o.coletar(db_session, cfg)

        from app.models.software import SoftwareInstalado

        assert db_session.query(SoftwareInstalado).first().software_id is None

        # O operador percebe o erro e corrige o padrão.
        s.padroes = "office*2021"
        db_session.commit()

        mudados = o.aplicar_reconhecimento(db_session)
        assert mudados == 1
        assert db_session.query(SoftwareInstalado).first().software_id == s.id

    def test_sem_softwares_cadastrados_nao_faz_nada(self, db_session):
        assert o.aplicar_reconhecimento(db_session) == 0


class TestResumo:
    def test_taxa_de_reconhecimento(self, db_session, cfg, monkeypatch):
        """É o indicador de saúde: baixa significa padrões fracos."""
        _maquina(db_session, "1", "PC-1")
        _software(db_session, "Chrome", "chrome*")

        monkeypatch.setattr(o.ocs_service, "_cliente", lambda c: ClienteFalso({
            "1": [{"name": "Google Chrome"}, {"name": "WinRAR"}, {"name": "7-Zip"}],
        }))
        o.coletar(db_session, cfg)

        r = o.resumo_do_banco(db_session)
        assert r["instalados"] == 3
        assert r["reconhecidos"] == 1
        assert r["sem_reconhecimento"] == 2
        assert r["taxa_reconhecimento"] == pytest.approx(0.333, abs=0.01)

    def test_banco_vazio_nao_divide_por_zero(self, db_session):
        r = o.resumo_do_banco(db_session)
        assert r["taxa_reconhecimento"] == 0.0
        assert r["instalados"] == 0
