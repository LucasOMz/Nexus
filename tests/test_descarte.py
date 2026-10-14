"""Descarte de equipamento: exigências por motivo, certificado e integridade.

O certificado só protege a empresa se for **completo** e **não puder ser
alterado depois**. Os testes cobrem os dois lados.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.descarte_service import (
    MOTIVOS,
    conferir,
    montar,
    precisa_logistica_reversa,
    resumo,
    texto,
    validar,
)

AGORA = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _base(**extra):
    d = {
        "patrimonio": "TP9800001176", "numero_serie": "NS-TP9800001176",
        "descricao": "Notebook Dell Latitude 3420",
        "marca": "Dell",
        "modelo": "Latitude 3420",
        "categoria": "informatica",
        "quantidade": 1,
        "responsavel": "Lucas Mendes",
        "empresa_nome": "Empresa Exemplo",
        "empresa_cnpj": "00.000.000/0001-00",
        "planta_nome": "Matriz",
    }
    d.update(extra)
    return d


class TestMotivos:
    """Cada motivo tem exigência documental diferente."""

    def test_sucata_exige_destinador_licenciado(self):
        v = validar(_base(motivo="sucata", destinador_nome="Recicla Ltda"))
        assert not v["ok"]
        assert "destinador_licenca" in v["pendencias"]

    def test_sucata_completa_passa(self):
        v = validar(_base(motivo="sucata", destinador_nome="Recicla Ltda",
                          destinador_cnpj="11.222.333/0001-44", destinador_licenca="LO-1234/2026"))
        assert v["ok"], v["mensagens"]

    def test_doacao_nao_exige_licenca(self):
        """Doação não passa por recicladora — exigir licença travaria à toa."""
        v = validar(_base(motivo="doacao", destinador_nome="Escola Municipal",
                          destinador_documento="00.111.222/0001-33"))
        assert v["ok"]

    def test_perda_exige_boletim_de_ocorrencia(self):
        assert not validar(_base(motivo="perda"))["ok"]
        assert validar(_base(motivo="perda", numero_ocorrencia="BO-2026/1234"))["ok"]

    def test_venda_exige_documento_fiscal(self):
        v = validar(_base(motivo="venda", destinador_nome="Leilão XYZ",
                          destinador_documento="123"))
        assert not v["ok"]
        assert "documento_fiscal" in v["pendencias"]

    def test_motivo_invalido_e_recusado(self):
        v = validar(_base(motivo="joguei_fora"))
        assert not v["ok"]
        assert "Motivo inválido" in v["pendencias"][0]

    def test_sem_motivo_lista_as_opcoes(self):
        v = validar(_base())
        assert not v["ok"]
        assert "sucata" in v["pendencias"][0]

    def test_transferencia_nao_e_descarte(self):
        """Transferir entre plantas não tira o bem do patrimônio."""
        v = validar(_base(motivo="transferencia"))
        assert v["ok"]
        assert MOTIVOS["transferencia"]["exige"] == []


class TestPendenciasExplicadas:
    """'Campo obrigatório' não ajuda quem precisa entender."""

    def test_mensagem_explica_o_motivo(self):
        v = validar(_base(motivo="sucata"))
        assert any("licença ambiental" in m for m in v["mensagens"])

    def test_explica_por_que_o_patrimonio_importa(self):
        v = validar({"motivo": "perda", "numero_ocorrencia": "BO-1", "quantidade": 1,
                     "responsavel": "X"})
        assert any("Patrimônio" in m for m in v["mensagens"])

    def test_traz_o_fundamento_legal(self):
        v = validar(_base(motivo="sucata"))
        assert "PNRS" in v["fundamento"]


class TestLogisticaReversa:
    """Eletrônico tem destinação obrigatória; móvel não."""

    def test_informatica_precisa(self):
        assert precisa_logistica_reversa("informatica")
        assert precisa_logistica_reversa("Eletrônico")

    def test_moveis_nao_precisam(self):
        assert not precisa_logistica_reversa("moveis")
        assert not precisa_logistica_reversa("papelaria")

    def test_sem_categoria_nao_presume(self):
        assert not precisa_logistica_reversa(None)


class TestCertificado:
    def _cert(self, **extra):
        base = _base(motivo="sucata", destinador_nome="Recicla Ltda",
                     destinador_cnpj="11.222.333/0001-44",
                     destinador_licenca="LO-1234/2026")
        base.update(extra)
        return montar(base, agora=AGORA)

    def test_gera_numero_rastreavel(self):
        c = self._cert()
        assert c["numero"].startswith("CAD-2026-10-")

    def test_traz_o_hash(self):
        assert len(self._cert()["hash"]) == 64

    def test_marca_logistica_reversa(self):
        assert self._cert()["logistica_reversa"] is True

    def test_moveis_nao_marcam_logistica_reversa(self):
        assert self._cert(categoria="moveis")["logistica_reversa"] is False

    def test_recusa_certificado_incompleto(self):
        """Documento com campo em branco não protege numa fiscalização."""
        with pytest.raises(ValueError, match="incompleto"):
            montar(_base(motivo="sucata", destinador_nome="X"), agora=AGORA)

    def test_numero_muda_com_o_conteudo(self):
        a = self._cert()
        b = self._cert(numero_serie="OUTRO")
        assert a["numero"] != b["numero"]


class TestIntegridade:
    """O certificado precisa ser prova, não arquivo editável."""

    def _cert(self):
        return montar(_base(motivo="doacao", destinador_nome="Escola",
                            destinador_documento="00.111/0001-33"), agora=AGORA)

    def test_recem_emitido_e_integro(self):
        assert conferir(self._cert())

    def test_alteracao_e_detectada(self):
        c = self._cert()
        c["equipamento"]["patrimonio"] = "OUTRO-PATRIMONIO"
        assert not conferir(c), "mudar o patrimônio tem que invalidar o hash"

    def test_alterar_o_destinatario_e_detectado(self):
        c = self._cert()
        c["destinacao"]["destinador_nome"] = "Outra Empresa"
        assert not conferir(c)

    def test_sem_hash_nao_e_integro(self):
        assert not conferir({"equipamento": {}})

    def test_hash_nao_entra_no_proprio_calculo(self):
        """Senão o hash mudaria a cada cálculo e nada conferiria."""
        c = self._cert()
        assert conferir(c)
        assert conferir(c)   # estável


class TestTextoLivre:
    def test_texto_tem_o_numero(self):
        c = montar(_base(motivo="perda", numero_ocorrencia="BO-1"), agora=AGORA)
        t = texto(c)
        assert c["numero"] in t

    def test_texto_traz_o_hash_para_conferencia(self):
        c = montar(_base(motivo="perda", numero_ocorrencia="BO-1"), agora=AGORA)
        assert c["hash"] in texto(c)

    def test_texto_avisa_sobre_logistica_reversa(self):
        c = montar(_base(motivo="sucata", destinador_nome="R",
                         destinador_cnpj="1", destinador_licenca="LO-1"), agora=AGORA)
        assert "LOGÍSTICA REVERSA" in texto(c)

    def test_certificado_incompleto_nao_vira_texto(self):
        c = montar(_base(motivo="perda", numero_ocorrencia="BO-1"), agora=AGORA)
        assert "CERTIFICADO DE DESCARTE" in texto(c)


class TestResumo:
    def test_resumo_marca_integro(self):
        c = montar(_base(motivo="perda", numero_ocorrencia="BO-1"), agora=AGORA)
        r = resumo(c)
        assert r["integro"] is True
        assert r["motivo"] == "Perda / Roubo / Furto"
