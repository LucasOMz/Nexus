"""SNMP de impressora: interpretação das respostas.

Testa a TRADUÇÃO, não a rede. É o que torna este módulo verificável sem uma
impressora acessível — e é onde estão as decisões que erram na prática: os
códigos especiais da MIB, o índice dos suprimentos, a estimativa de duração.
"""
from __future__ import annotations

from app.services.snmp_service import (
    OIDS,
    alertas_de_suprimento,
    classificar_suprimento,
    estimar_duracao,
    extrair_suprimentos,
    mapear,
    percentual_suprimento,
)


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
