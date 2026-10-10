"""Ciclo de empréstimo: etapas, escalonamento de atraso e checklist.

Funções puras — os testes não dependem do relógio nem de banco.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.emprestimo_service import (
    CHECKLIST_PADRAO,
    DIAS_AVISO_GESTOR,
    DIAS_AVISO_USUARIO,
    DIAS_BLOQUEIO,
    avaliar_devolucao,
    escalonamento,
    pode_transicionar,
    proximos_passos,
    resumo_do_ciclo,
    validar_transicao,
)

AGORA = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _em(dias: int) -> str:
    return (AGORA + timedelta(days=dias)).date().isoformat()


class TestEtapas:
    """Reserva → Retirada → Uso → Devolução → Vistoria."""

    def test_fluxo_completo(self):
        assert pode_transicionar("reservado", "retirado")
        assert pode_transicionar("retirado", "devolvido")
        assert pode_transicionar("devolvido", "vistoriado")

    def test_nao_pula_etapa(self):
        """Reservado não vira devolvido sem passar pela retirada."""
        assert not pode_transicionar("reservado", "devolvido")
        assert not pode_transicionar("reservado", "vistoriado")

    def test_encerrado_nao_volta(self):
        assert not pode_transicionar("vistoriado", "retirado")
        assert not pode_transicionar("cancelado", "retirado")

    def test_reserva_pode_ser_cancelada(self):
        assert pode_transicionar("reservado", "cancelado")

    def test_retirado_nao_pode_ser_cancelado(self):
        """Já saiu da mão do sistema: o caminho é a devolução."""
        assert not pode_transicionar("retirado", "cancelado")

    def test_retirada_exige_termo(self):
        r = validar_transicao("reservado", "retirado", tem_termo=False, tem_checklist=True)
        assert not r["ok"]
        assert "termo" in r["motivo"].lower()

    def test_retirada_exige_conferencia(self):
        r = validar_transicao("reservado", "retirado", tem_termo=True, tem_checklist=False)
        assert not r["ok"]
        assert "estado" in r["motivo"].lower() or "confira" in r["motivo"].lower()

    def test_retirada_completa_passa(self):
        r = validar_transicao("reservado", "retirado", tem_termo=True, tem_checklist=True)
        assert r["ok"]

    def test_devolucao_exige_conferencia_mas_nao_termo(self):
        assert not validar_transicao("retirado", "devolvido", tem_checklist=False)["ok"]
        assert validar_transicao("retirado", "devolvido", tem_checklist=True)["ok"]

    def test_vistoria_nao_exige_nada(self):
        assert validar_transicao("devolvido", "vistoriado")["ok"]

    def test_transicao_invalida_explica(self):
        r = validar_transicao("reservado", "vistoriado")
        assert not r["ok"]
        assert "reservado" in r["motivo"] and "vistoriado" in r["motivo"]

    def test_proximos_passos_de_reservado(self):
        p = proximos_passos("reservado")
        destinos = {x["situacao"] for x in p}
        assert destinos == {"retirado", "cancelado"}

    def test_proximos_passos_de_encerrado_e_vazio(self):
        assert proximos_passos("vistoriado") == []


class TestEscalonamento:
    """Avisa o usuário → avisa o gestor → bloqueia novo empréstimo."""

    def test_em_dia(self):
        e = escalonamento(_em(5), agora=AGORA)
        assert e["nivel"] == 0
        assert not e["bloqueia_novo_emprestimo"]

    def test_um_dia_avisa_o_usuario(self):
        e = escalonamento(_em(-1), agora=AGORA)
        assert e["nivel"] == 1
        assert e["avisar"] == ["usuario"]

    def test_sete_dias_avisa_o_gestor(self):
        e = escalonamento(_em(-DIAS_AVISO_GESTOR), agora=AGORA)
        assert e["nivel"] == 2
        assert "gestor" in e["avisar"]

    def test_quinze_dias_bloqueia(self):
        e = escalonamento(_em(-DIAS_BLOQUEIO), agora=AGORA)
        assert e["nivel"] == 3
        assert e["bloqueia_novo_emprestimo"]

    def test_escalada_e_progressiva(self):
        """O nível nunca cai conforme o atraso cresce."""
        niveis = [escalonamento(_em(-d), agora=AGORA)["nivel"]
                  for d in (0, DIAS_AVISO_USUARIO, DIAS_AVISO_GESTOR, DIAS_BLOQUEIO, 90)]
        assert niveis == sorted(niveis)

    def test_conta_os_dias(self):
        e = escalonamento(_em(-10), agora=AGORA)
        assert e["dias_atraso"] == 10

    def test_sem_prazo_nao_inventa_atraso(self):
        e = escalonamento(None, agora=AGORA)
        assert e["nivel"] == 0
        assert e["situacao"] == "sem_prazo"

    def test_ja_bloqueado_continua_bloqueado(self):
        e = escalonamento(_em(30), agora=AGORA, ja_bloqueado=True)
        assert e["nivel"] == 3
        assert e["bloqueia_novo_emprestimo"]


class TestChecklist:
    """Comparar entrega e devolução é o que revela avaria."""

    OK = {k: True for k in
          ["Liga e inicializa", "Tela sem trinca ou mancha", "Teclado completo e funcional",
           "Carcaça sem trinca", "Carregador e cabo presentes", "Bateria segura carga",
           "Sem sinais de queda ou líquido"]}

    def test_tudo_igual_nao_abre_manutencao(self):
        r = avaliar_devolucao(self.OK, dict(self.OK))
        assert r["avarias"] == []
        assert not r["abrir_manutencao"]
        assert r["situacao"] == "conforme"

    def test_item_ok_que_voltou_quebrado_e_avaria(self):
        dev = dict(self.OK)
        dev["Tela sem trinca ou mancha"] = False
        r = avaliar_devolucao(self.OK, dev)
        assert "Tela sem trinca ou mancha" in r["avarias"]
        assert r["abrir_manutencao"]
        assert r["situacao"] == "avaria"

    def test_ja_estava_quebrado_nao_e_avaria(self):
        """Não se cobra do usuário o que já estava quebrado na entrega."""
        entrega = dict(self.OK)
        entrega["Carcaça sem trinca"] = False
        dev = dict(entrega)
        r = avaliar_devolucao(entrega, dev)
        assert r["avarias"] == []
        assert not r["abrir_manutencao"]

    def test_conserto_durante_o_uso_nao_e_avaria(self):
        entrega = dict(self.OK)
        entrega["Bateria segura carga"] = False
        dev = dict(self.OK)
        dev["Bateria segura carga"] = True
        r = avaliar_devolucao(entrega, dev)
        assert r["avarias"] == []
        assert "Bateria segura carga" in r["melhorou"]

    def test_varias_avarias(self):
        dev = dict(self.OK)
        dev["Tela sem trinca ou mancha"] = False
        dev["Sem sinais de queda ou líquido"] = False
        r = avaliar_devolucao(self.OK, dev)
        assert len(r["avarias"]) == 2
        assert "2 item(ns)" in r["mensagem"]

    def test_sem_entrega_registrada_pede_vistoria(self):
        """Voltou com problema e não se sabe como saiu: alguém precisa olhar."""
        dev = dict(self.OK)
        dev["Teclado completo e funcional"] = False
        r = avaliar_devolucao({}, dev)
        assert r["precisa_vistoria"]
        assert "Teclado completo e funcional" in r["sem_base_de_comparacao"]

    def test_vistoria_quando_ha_avaria(self):
        dev = dict(self.OK)
        dev["Carcaça sem trinca"] = False
        assert avaliar_devolucao(self.OK, dev)["precisa_vistoria"]

    def test_checklist_incompleto_nao_quebra(self):
        r = avaliar_devolucao({}, {})
        assert r["avarias"] == []
        assert r["situacao"] == "conforme"


class TestResumoDoCiclo:
    def test_reserva_sem_termo_tem_pendencia(self):
        r = resumo_do_ciclo("reservado", _em(3), tem_termo=False, agora=AGORA)
        assert any("Termo" in p for p in r["pendencias"])
        assert not r["encerrado"]

    def test_retirado_com_termo_sem_checklist(self):
        r = resumo_do_ciclo("retirado", _em(3), tem_termo=True,
                            tem_checklist_entrega=False, agora=AGORA)
        assert any("entrega" in p for p in r["pendencias"])

    def test_devolvido_aguarda_vistoria(self):
        r = resumo_do_ciclo("devolvido", _em(-1), agora=AGORA)
        assert any("vistoria" in p for p in r["pendencias"])

    def test_vistoriado_encerrado_sem_pendencia(self):
        r = resumo_do_ciclo("vistoriado", _em(-1), tem_termo=True,
                            tem_checklist_entrega=True, agora=AGORA)
        assert r["encerrado"]
        assert r["pendencias"] == []

    def test_traz_o_alerta_de_atraso(self):
        r = resumo_do_ciclo("retirado", _em(-20), tem_termo=True,
                            tem_checklist_entrega=True, agora=AGORA)
        assert r["alerta"]["nivel"] == 3
        assert r["alerta"]["bloqueia_novo_emprestimo"]


class TestChecklistConfiguravel:
    """Os itens conferidos não são fixos no código.

    Quem administra cadastra o que faz sentido para a categoria: conferir
    "bateria segura carga" num switch não serve para nada.
    """

    ITENS = ["Liga", "Sem trinca", "Cabo presente"]

    def test_usa_os_itens_configurados(self):
        entrega = dict.fromkeys(self.ITENS, True)
        dev = dict(entrega)
        dev["Cabo presente"] = False

        r = avaliar_devolucao(entrega, dev, itens=self.ITENS)
        assert r["avarias"] == ["Cabo presente"]

    def test_nao_avalia_item_fora_da_lista(self):
        """Se o item não está no checklist, ele não entra no laudo."""
        entrega = {"Liga": True}
        dev = {"Liga": True, "Bateria segura carga": False}
        r = avaliar_devolucao(entrega, dev, itens=["Liga"])
        assert r["avarias"] == []

    def test_lista_vazia_nao_quebra(self):
        r = avaliar_devolucao({}, {}, itens=[])
        assert r["situacao"] == "conforme"

    def test_sem_lista_usa_o_padrao(self):
        r = avaliar_devolucao(dict.fromkeys(CHECKLIST_PADRAO, True),
                              dict.fromkeys(CHECKLIST_PADRAO, True))
        assert r["avarias"] == []
