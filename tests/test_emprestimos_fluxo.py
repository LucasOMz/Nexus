"""Fluxo de empréstimo de ponta a ponta, contra o banco.

Este arquivo existe porque a falta dele deixou passar um erro que só aparece
quando o fluxo roda de verdade: a lógica estava testada, os endpoints não.
"""
from __future__ import annotations

import pytest

from app.models.emprestimo import ChecklistItem


@pytest.fixture
def checklist(client):
    """Dois itens de conferência, criados direto no banco de teste."""
    from tests.conftest import TestingSession

    db = TestingSession()
    db.query(ChecklistItem).delete()
    db.add_all([
        ChecklistItem(rotulo="Liga", ordem=0, na_entrega=True, na_devolucao=True),
        ChecklistItem(rotulo="Cabo presente", ordem=1, na_entrega=True, na_devolucao=True),
    ])
    db.commit()
    db.close()


def _ativo(client, h, patrimonio="EMP-1"):
    r = client.post("/api/v1/ativos", json={
        "dominio": "ti", "patrimonio": patrimonio, "tipo_item": "ativo",
    }, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _reservar(client, h, ativo_id, nome="Fulano"):
    r = client.post("/api/v1/emprestimos", json={
        "ativo_id": ativo_id, "retirado_por_nome": nome,
    }, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


class TestFluxoCompleto:
    def test_ciclo_inteiro(self, client, auth_headers, checklist):
        a = _ativo(client, auth_headers)
        emp = _reservar(client, auth_headers, a["id"])
        assert emp["situacao"] == "reservado"
        assert emp["proximos_passos"], "a reserva precisa oferecer os próximos passos"

        # --- Retirada -----------------------------------------------------
        r = client.post(f"/api/v1/emprestimos/{emp['id']}/retirar", json={
            "itens": [{"rotulo": "Liga", "ok": True}, {"rotulo": "Cabo presente", "ok": True}],
            "confirmar_termo": True,
        }, headers=auth_headers)
        assert r.status_code == 200, f"RETIRADA FALHOU: {r.status_code} {r.text}"
        assert r.json()["situacao"] == "retirado"

        # --- Devolução ----------------------------------------------------
        r = client.post(f"/api/v1/emprestimos/{emp['id']}/devolver", json={
            "itens": [{"rotulo": "Liga", "ok": True}, {"rotulo": "Cabo presente", "ok": False}],
        }, headers=auth_headers)
        assert r.status_code == 200, f"DEVOLUÇÃO FALHOU: {r.status_code} {r.text}"
        corpo = r.json()
        assert corpo["situacao"] == "devolvido"
        assert corpo["tem_avaria"] is True
        assert "Cabo presente" in corpo["laudo"]["avarias"]

        # --- Vistoria -----------------------------------------------------
        r = client.post(f"/api/v1/emprestimos/{emp['id']}/vistoriar", json={
            "abrir_manutencao": True,
        }, headers=auth_headers)
        assert r.status_code == 200, f"VISTORIA FALHOU: {r.status_code} {r.text}"
        assert r.json()["situacao"] == "vistoriado"
        assert r.json()["manutencao_id"], "avaria precisa abrir manutenção"

    def test_checagem_do_checklist_modelo(self, client, auth_headers, checklist):
        r = client.get("/api/v1/emprestimos/checklist/modelo", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert len(r.json()) == 2


class TestRetirada:
    def test_sem_termo_e_recusada(self, client, auth_headers, checklist):
        a = _ativo(client, auth_headers, "EMP-2")
        emp = _reservar(client, auth_headers, a["id"])

        r = client.post(f"/api/v1/emprestimos/{emp['id']}/retirar", json={
            "itens": [{"rotulo": "Liga", "ok": True}],
            "confirmar_termo": False,
        }, headers=auth_headers)
        assert r.status_code == 400
        assert "termo" in r.json()["detail"].lower()

    def test_sem_conferencia_e_recusada(self, client, auth_headers, checklist):
        a = _ativo(client, auth_headers, "EMP-3")
        emp = _reservar(client, auth_headers, a["id"])

        r = client.post(f"/api/v1/emprestimos/{emp['id']}/retirar", json={
            "itens": [], "confirmar_termo": True,
        }, headers=auth_headers)
        assert r.status_code == 400

    def test_ativo_marcado_como_emprestado(self, client, auth_headers, checklist):
        a = _ativo(client, auth_headers, "EMP-4")
        emp = _reservar(client, auth_headers, a["id"])
        client.post(f"/api/v1/emprestimos/{emp['id']}/retirar", json={
            "itens": [{"rotulo": "Liga", "ok": True}], "confirmar_termo": True,
        }, headers=auth_headers)

        d = client.get(f"/api/v1/ativos/{a['id']}", headers=auth_headers).json()
        assert d["status"] == "emprestado"

    def test_devolucao_libera_o_ativo(self, client, auth_headers, checklist):
        a = _ativo(client, auth_headers, "EMP-5")
        emp = _reservar(client, auth_headers, a["id"])
        client.post(f"/api/v1/emprestimos/{emp['id']}/retirar", json={
            "itens": [{"rotulo": "Liga", "ok": True}], "confirmar_termo": True,
        }, headers=auth_headers)
        client.post(f"/api/v1/emprestimos/{emp['id']}/devolver", json={
            "itens": [{"rotulo": "Liga", "ok": True}],
        }, headers=auth_headers)

        d = client.get(f"/api/v1/ativos/{a['id']}", headers=auth_headers).json()
        assert d["status"] == "estoque"


class TestReserva:
    def test_nao_permite_dois_emprestimos_do_mesmo_ativo(self, client, auth_headers):
        a = _ativo(client, auth_headers, "EMP-6")
        _reservar(client, auth_headers, a["id"])
        r = client.post("/api/v1/emprestimos", json={
            "ativo_id": a["id"], "retirado_por_nome": "Outro",
        }, headers=auth_headers)
        assert r.status_code == 400
        assert "aberto" in r.json()["detail"].lower()

    def test_exige_destinatario(self, client, auth_headers):
        a = _ativo(client, auth_headers, "EMP-7")
        r = client.post("/api/v1/emprestimos", json={"ativo_id": a["id"]}, headers=auth_headers)
        assert r.status_code == 400

    def test_cancelar_reserva(self, client, auth_headers):
        a = _ativo(client, auth_headers, "EMP-8")
        emp = _reservar(client, auth_headers, a["id"])
        r = client.post(f"/api/v1/emprestimos/{emp['id']}/cancelar", json={},
                        headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["situacao"] == "cancelado"

    def test_nao_cancela_depois_de_retirado(self, client, auth_headers, checklist):
        a = _ativo(client, auth_headers, "EMP-9")
        emp = _reservar(client, auth_headers, a["id"])
        client.post(f"/api/v1/emprestimos/{emp['id']}/retirar", json={
            "itens": [{"rotulo": "Liga", "ok": True}], "confirmar_termo": True,
        }, headers=auth_headers)

        r = client.post(f"/api/v1/emprestimos/{emp['id']}/cancelar", json={},
                        headers=auth_headers)
        assert r.status_code == 400


class TestBloqueioPorAtraso:
    """A escada do atraso: avisa o usuário → avisa o gestor → bloqueia.

    O bloqueio é a ponta da escada. Sem ele, quem nunca devolve continua
    levando equipamento novo.
    """

    def _reserva_atrasada(self, client, h, dias_atras):
        """Um empréstimo retirado e já vencido há `dias_atras`."""
        from datetime import datetime, timedelta, timezone

        a = _ativo(client, h, f"BLOQ-{dias_atras}")
        venc = (datetime.now(timezone.utc) - timedelta(days=dias_atras)).isoformat()
        emp = client.post("/api/v1/emprestimos", json={
            "ativo_id": a["id"], "usuario_id": 1, "devolucao_prevista": venc,
        }, headers=h).json()
        client.post(f"/api/v1/emprestimos/{emp['id']}/retirar", json={
            "itens": [{"rotulo": "Liga", "ok": True}], "confirmar_termo": True,
        }, headers=h)
        return a, emp

    def test_atraso_curto_nao_bloqueia(self, client, auth_headers, checklist):
        self._reserva_atrasada(client, auth_headers, 2)
        outro = _ativo(client, auth_headers, "BLOQ-NOVO-1")
        r = client.post("/api/v1/emprestimos", json={
            "ativo_id": outro["id"], "usuario_id": 1,
        }, headers=auth_headers)
        assert r.status_code == 201, "2 dias de atraso avisam, mas não bloqueiam"

    def test_atraso_longo_bloqueia(self, client, auth_headers, checklist):
        a, emp = self._reserva_atrasada(client, auth_headers, 20)
        outro = _ativo(client, auth_headers, "BLOQ-NOVO-2")

        r = client.post("/api/v1/emprestimos", json={
            "ativo_id": outro["id"], "usuario_id": 1,
        }, headers=auth_headers)
        assert r.status_code == 400, r.text
        detalhe = r.json()["detail"]
        assert "bloqueado" in detalhe.lower()
        assert str(emp["id"]) in detalhe, "o aviso precisa dizer QUAL empréstimo"

    def test_regularizar_libera(self, client, auth_headers, checklist):
        a, emp = self._reserva_atrasada(client, auth_headers, 20)
        client.post(f"/api/v1/emprestimos/{emp['id']}/devolver", json={
            "itens": [{"rotulo": "Liga", "ok": True}],
        }, headers=auth_headers)

        outro = _ativo(client, auth_headers, "BLOQ-NOVO-3")
        r = client.post("/api/v1/emprestimos", json={
            "ativo_id": outro["id"], "usuario_id": 1,
        }, headers=auth_headers)
        assert r.status_code == 201, "devolvido, o bloqueio cai"

    def test_bloqueio_vale_para_o_mesmo_usuario(self, client, auth_headers, checklist):
        """Outra pessoa não paga pelo atraso de quem deve."""
        self._reserva_atrasada(client, auth_headers, 20)
        outro = _ativo(client, auth_headers, "BLOQ-NOVO-4")
        r = client.post("/api/v1/emprestimos", json={
            "ativo_id": outro["id"], "retirado_por_nome": "Sem login",
        }, headers=auth_headers)
        assert r.status_code == 201
