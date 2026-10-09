"""Testes da reconciliação com o OCS.

A comparação é uma função pura, então estes testes usam dados sintéticos: não
dependem de um servidor OCS no ar. Era o ponto — uma tela de reconciliação que
só pode ser testada contra produção não é confiável.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.ocs_reconciliacao import comparar

AGORA = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _inventario(**extra):
    base = {
        "ativo_id": 1,
        "patrimonio": "TP-1",
        "hostname": "DTAT0001",
        "ip": "10.0.0.10",
        "mac_address": "00:1A:2B:3C:4D:5E",
        "ocs_id": "42",
        "ocs_ultimo_contato": AGORA.isoformat(),
    }
    base.update(extra)
    return base


def _rede(**extra):
    base = {
        "ocs_id": "42",
        "hostname": "DTAT0001",
        "ip": "10.0.0.10",
        "mac_address": "00:1A:2B:3C:4D:5E",
    }
    base.update(extra)
    return base


def _comparar(inventario, dispositivos, dias=30):
    return comparar(inventario, dispositivos, dias_sem_contato=dias, agora=AGORA)


class TestFantasmas:
    """Na rede, fora do inventário."""

    def test_maquina_desconhecida_e_fantasma(self):
        r = _comparar([], [_rede(ocs_id="99", hostname="DESCONHECIDA")])
        assert len(r["fantasmas"]) == 1
        assert r["fantasmas"][0]["hostname"] == "DESCONHECIDA"

    def test_maquina_casada_nao_e_fantasma(self):
        r = _comparar([_inventario()], [_rede()])
        assert r["fantasmas"] == []

    def test_casa_pelo_hostname_quando_falta_ocs_id(self):
        """Ativo cadastrado à mão, sem ocs_id, mas com o mesmo hostname."""
        inv = _inventario(ocs_id=None)
        r = _comparar([inv], [_rede()])
        assert r["fantasmas"] == [], "casar pelo hostname evita fantasma falso"

    def test_casa_pelo_mac_com_formato_diferente(self):
        inv = _inventario(ocs_id=None, hostname=None)
        r = _comparar([inv], [_rede(ocs_id=None, hostname=None, mac_address="00-1a-2b-3c-4d-5e")])
        assert r["fantasmas"] == []

    def test_traz_dados_para_o_cadastro(self):
        r = _comparar([], [_rede(ocs_id="99", hostname="NOVA", ip="10.0.0.77",
                                 numero_serie="SN123", so="Windows 11")])
        f = r["fantasmas"][0]
        assert f["ip"] == "10.0.0.77"
        assert f["numero_serie"] == "SN123"


class TestPerdidos:
    """No inventário, sumidos da rede."""

    def test_sem_contato_alem_do_limite(self):
        antigo = (AGORA - timedelta(days=45)).isoformat()
        r = _comparar([_inventario(ocs_ultimo_contato=antigo)], [])
        assert len(r["perdidos"]) == 1
        assert "45 dias" in r["perdidos"][0]["motivo"]

    def test_contato_recente_nao_e_perdido(self):
        r = _comparar([_inventario()], [])
        assert r["perdidos"] == []

    def test_nunca_visto_aparece(self):
        r = _comparar([_inventario(ocs_ultimo_contato=None)], [])
        assert len(r["perdidos"]) == 1
        assert r["perdidos"][0]["motivo"] == "nunca visto"

    def test_ativo_sem_ocs_e_sem_hostname_e_ignorado(self):
        """Do que o OCS nunca soube, ele não pode ser cobrado."""
        inv = _inventario(ocs_id=None, hostname=None)
        r = _comparar([inv], [])
        assert r["perdidos"] == []

    def test_voltou_a_aparecer_nao_e_perdido(self):
        """Estava velho no banco, mas o OCS o viu agora."""
        antigo = (AGORA - timedelta(days=90)).isoformat()
        r = _comparar([_inventario(ocs_ultimo_contato=antigo)], [_rede()])
        assert r["perdidos"] == []

    def test_limite_e_respeitado(self):
        recente = (AGORA - timedelta(days=10)).isoformat()
        assert _comparar([_inventario(ocs_ultimo_contato=recente)], [], dias=5)["perdidos"]
        assert not _comparar([_inventario(ocs_ultimo_contato=recente)], [], dias=30)["perdidos"]


class TestDivergencias:
    """Casados, mas com dados diferentes."""

    def test_ip_diferente(self):
        r = _comparar([_inventario()], [_rede(ip="10.0.0.99")])
        campos = [d["campo"] for d in r["divergencias"]]
        assert "ip" in campos

    def test_hostname_diferente(self):
        r = _comparar([_inventario()], [_rede(hostname="NOVO-NOME", ocs_id="42")])
        assert any(d["campo"] == "hostname" for d in r["divergencias"])

    def test_mac_com_formato_diferente_nao_e_divergencia(self):
        """'00:1A:2B' e '00-1a-2b' são o mesmo endereço."""
        r = _comparar([_inventario()], [_rede(mac_address="00-1A-2B-3C-4D-5E")])
        assert not any(d["campo"] == "mac_address" for d in r["divergencias"])

    def test_campo_vazio_no_inventario_nao_e_divergencia(self):
        """Informação que falta não é conflito — senão o relatório afoga."""
        r = _comparar([_inventario(ip=None)], [_rede(ip="10.0.0.99")])
        assert not any(d["campo"] == "ip" for d in r["divergencias"])

    def test_mostra_os_dois_lados(self):
        r = _comparar([_inventario()], [_rede(ip="10.0.0.99")])
        d = [x for x in r["divergencias"] if x["campo"] == "ip"][0]
        assert d["no_inventario"] == "10.0.0.10"
        assert d["na_rede"] == "10.0.0.99"

    def test_iguais_nao_geram_divergencia(self):
        r = _comparar([_inventario()], [_rede()])
        assert r["divergencias"] == []


class TestResumo:
    def test_conta_cada_categoria(self):
        inventario = [
            _inventario(ativo_id=1, ocs_id="1", hostname="A"),
            _inventario(ativo_id=2, ocs_id="2", hostname="B",
                        ocs_ultimo_contato=(AGORA - timedelta(days=60)).isoformat()),
            _inventario(ativo_id=3, ocs_id="3", hostname="C"),
        ]
        rede = [
            _rede(ocs_id="1", hostname="A"),
            _rede(ocs_id="3", hostname="C", ip="10.0.0.99"),
            _rede(ocs_id="9", hostname="FANTASMA"),
        ]
        r = _comparar(inventario, rede)
        assert r["resumo"]["fantasmas"] == 1
        assert r["resumo"]["perdidos"] == 1
        assert r["resumo"]["divergencias"] == 1
        assert r["resumo"]["no_inventario"] == 3

    def test_inventario_vazio_nao_quebra(self):
        r = _comparar([], [])
        assert r["resumo"]["fantasmas"] == 0
        assert r["resumo"]["perdidos"] == 0

    def test_rede_vazia_nao_marca_todo_mundo_como_perdido(self):
        """A lista vazia do OCS não pode virar alarme falso.

        Se o OCS estiver fora do ar (ou a consulta falhar), a lista vem vazia.
        Marcar todo o inventário como perdido nesse momento seria pior que não
        avisar: o relatório perderia a credibilidade na primeira queda.

        Quem protege disso é o `ocs_ultimo_contato` com limite de dias — e não
        a ausência na lista de agora.
        """
        r = _comparar([_inventario()], [])
        assert r["resumo"]["na_rede"] == 0
        assert r["perdidos"] == [], "contato recente não é perdido, mesmo com a rede vazia"

        # Mas se o contato estiver velho, aí sim aparece.
        antigo = (AGORA - timedelta(days=60)).isoformat()
        r2 = _comparar([_inventario(ocs_ultimo_contato=antigo)], [])
        assert len(r2["perdidos"]) == 1

    def test_data_invalida_e_tratada_como_sem_contato(self):
        r = _comparar([_inventario(ocs_ultimo_contato="data-que-nao-existe")], [])
        assert len(r["perdidos"]) == 1
