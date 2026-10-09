"""Transferência de equipamentos entre plantas, com dupla aprovação.

Fluxo: técnico da origem solicita → **quem recebe aprova** → **administrador
aprova** → o ativo muda de planta. Os pendentes aparecem no sino de quem
precisa decidir.
"""
from __future__ import annotations

import pytest

from app.core.rate_limit import login_limiter, scan_limiter


@pytest.fixture(autouse=True)
def _liberar_rate_limit():
    login_limiter._hits.clear()
    scan_limiter._hits.clear()
    yield
    login_limiter._hits.clear()
    scan_limiter._hits.clear()


def _planta(client, auth, nome, sigla):
    return client.post("/api/v1/admin/plantas", json={"nome": nome, "sigla": sigla}, headers=auth).json()["id"]


def _usuario(client, auth, email, planta_id, papel="ti"):
    r = client.post(
        "/api/v1/usuarios",
        json={
            "nome": f"Tec {email}", "email": email, "papel": papel, "senha": "senha123",
            "planta_id": planta_id,
            "permissoes": {
                "inventarios": ["ti", "impressora"],
                "modulos": ["ativos", "movimentacoes"],
                "pode_escrever": True,
            },
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    login = client.post("/api/v1/auth/login", data={"username": email, "password": "senha123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _ativo(client, headers, planta_id, patrimonio):
    h = {**headers, "X-Planta-Id": str(planta_id)}
    return client.post(
        "/api/v1/ativos",
        json={"dominio": "ti", "patrimonio": patrimonio, "modelo": "Latitude", "tipo_item": "ativo"},
        headers=h,
    ).json()


def _solicitar(client, headers, planta_id, ativo_id, destino_id, **extra):
    return client.post(
        "/api/v1/transferencias",
        data={"ativo_id": ativo_id, "planta_destino_id": destino_id, "motivo": "transferencia", **extra},
        headers={**headers, "X-Planta-Id": str(planta_id)},
    )


class TestFluxoDeDuplaAprovacao:
    def _cenario(self, client, auth_headers):
        a = _planta(client, auth_headers, "Bonito", "BON")
        b = _planta(client, auth_headers, "Tatuí", "TAT")
        ha = _usuario(client, auth_headers, "origem@teste.com", a)
        hb = _usuario(client, auth_headers, "destino@teste.com", b)
        ativo = _ativo(client, ha, a, "TR-0001")
        return a, b, ha, hb, ativo

    def test_solicitacao_entra_aguardando_destino(self, client, auth_headers):
        a, b, ha, _, ativo = self._cenario(client, auth_headers)
        r = _solicitar(client, ha, a, ativo["id"], b)

        assert r.status_code == 201, r.text
        corpo = r.json()
        assert corpo["status"] == "aguardando_destino"
        assert corpo["status_rotulo"] == "Aguardando aprovação de quem recebe"
        assert corpo["planta_origem"] == "BON"
        assert corpo["planta_destino"] == "TAT"

    def test_aprovacao_do_destino_leva_para_o_admin(self, client, auth_headers):
        a, b, ha, hb, ativo = self._cenario(client, auth_headers)
        tid = _solicitar(client, ha, a, ativo["id"], b).json()["id"]

        r = client.post(f"/api/v1/transferencias/{tid}/aprovar", headers={**hb, "X-Planta-Id": str(b)})
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "aguardando_admin"
        assert r.json()["aprovado_destino_por"] == "Tec destino@teste.com"

    def test_aprovacao_do_admin_muda_a_planta_do_ativo(self, client, auth_headers):
        a, b, ha, hb, ativo = self._cenario(client, auth_headers)
        tid = _solicitar(client, ha, a, ativo["id"], b).json()["id"]
        client.post(f"/api/v1/transferencias/{tid}/aprovar", headers={**hb, "X-Planta-Id": str(b)})

        r = client.post(f"/api/v1/transferencias/{tid}/aprovar", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "aprovada"

        depois = client.get(f"/api/v1/ativos/{ativo['id']}", headers=auth_headers).json()
        assert depois["planta_id"] == b, "o ativo deveria ter mudado de planta"

    def test_origem_nao_aprova_a_propria_transferencia(self, client, auth_headers):
        """Quem envia não decide a chegada — senão não haveria aprovação."""
        a, b, ha, _, ativo = self._cenario(client, auth_headers)
        tid = _solicitar(client, ha, a, ativo["id"], b).json()["id"]

        r = client.post(f"/api/v1/transferencias/{tid}/aprovar", headers={**ha, "X-Planta-Id": str(a)})
        assert r.status_code == 403

    def test_admin_nao_aprova_duas_etapas_de_uma_vez(self, client, auth_headers):
        """Na primeira etapa ele entra como destino, mas ainda falta a 2ª."""
        a, b, ha, _, ativo = self._cenario(client, auth_headers)
        tid = _solicitar(client, ha, a, ativo["id"], b).json()["id"]

        r1 = client.post(f"/api/v1/transferencias/{tid}/aprovar", headers=auth_headers)
        assert r1.status_code == 200
        assert r1.json()["status"] == "aguardando_admin"

        r2 = client.post(f"/api/v1/transferencias/{tid}/aprovar", headers=auth_headers)
        assert r2.status_code == 200
        assert r2.json()["status"] == "aprovada"

    def test_nao_abre_duas_transferencias_para_o_mesmo_ativo(self, client, auth_headers):
        a, b, ha, _, ativo = self._cenario(client, auth_headers)
        _solicitar(client, ha, a, ativo["id"], b)

        r = _solicitar(client, ha, a, ativo["id"], b)
        assert r.status_code == 409
        assert "andamento" in r.json()["detail"]

    def test_nao_transfere_ativo_de_outra_planta(self, client, auth_headers):
        a, b, ha, hb, ativo = self._cenario(client, auth_headers)
        # `hb` é da planta B e tenta enviar o ativo da planta A.
        r = _solicitar(client, hb, b, ativo["id"], a)
        assert r.status_code == 403

    def test_destino_igual_a_origem_e_recusado(self, client, auth_headers):
        a, _, ha, _, ativo = self._cenario(client, auth_headers)
        r = _solicitar(client, ha, a, ativo["id"], a)
        assert r.status_code == 400


class TestMotivos:
    def test_motivo_outro_exige_descricao(self, client, auth_headers):
        a = _planta(client, auth_headers, "Bonito", "BON")
        b = _planta(client, auth_headers, "Tatuí", "TAT")
        ha = _usuario(client, auth_headers, "motivo@teste.com", a)
        ativo = _ativo(client, ha, a, "TR-MOT")

        r = client.post(
            "/api/v1/transferencias",
            data={"ativo_id": ativo["id"], "planta_destino_id": b, "motivo": "outro"},
            headers={**ha, "X-Planta-Id": str(a)},
        )
        assert r.status_code == 400
        assert "Descreva o motivo" in r.json()["detail"]

    def test_motivo_invalido_e_recusado(self, client, auth_headers):
        a = _planta(client, auth_headers, "Bonito", "BON")
        b = _planta(client, auth_headers, "Tatuí", "TAT")
        ha = _usuario(client, auth_headers, "motivo2@teste.com", a)
        ativo = _ativo(client, ha, a, "TR-MOT2")

        r = client.post(
            "/api/v1/transferencias",
            data={"ativo_id": ativo["id"], "planta_destino_id": b, "motivo": "inventado"},
            headers={**ha, "X-Planta-Id": str(a)},
        )
        assert r.status_code == 400

    def test_lista_de_motivos(self, client, auth_headers):
        r = client.get("/api/v1/transferencias/motivos", headers=auth_headers).json()
        valores = {m["valor"] for m in r}
        assert {"emprestimo", "transferencia", "outro"} <= valores


class TestRecusaECancelamento:
    def _cenario(self, client, auth_headers):
        a = _planta(client, auth_headers, "Bonito", "BON")
        b = _planta(client, auth_headers, "Tatuí", "TAT")
        ha = _usuario(client, auth_headers, "rec.origem@teste.com", a)
        hb = _usuario(client, auth_headers, "rec.destino@teste.com", b)
        ativo = _ativo(client, ha, a, "TR-REC")
        tid = _solicitar(client, ha, a, ativo["id"], b).json()["id"]
        return a, b, ha, hb, ativo, tid

    def test_destino_recusa_com_motivo(self, client, auth_headers):
        _, b, _, hb, ativo, tid = self._cenario(client, auth_headers)
        r = client.post(
            f"/api/v1/transferencias/{tid}/recusar",
            data={"motivo_recusa": "Não temos espaço no rack"},
            headers={**hb, "X-Planta-Id": str(b)},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "recusada"
        assert r.json()["motivo_recusa"] == "Não temos espaço no rack"

        # O ativo NÃO muda de planta numa recusa.
        assert client.get(f"/api/v1/ativos/{ativo['id']}", headers=auth_headers).json()["planta_id"] == ativo["planta_id"]

    def test_recusa_sem_motivo_e_recusada(self, client, auth_headers):
        _, b, _, hb, _, tid = self._cenario(client, auth_headers)
        r = client.post(
            f"/api/v1/transferencias/{tid}/recusar",
            data={"motivo_recusa": "ab"},
            headers={**hb, "X-Planta-Id": str(b)},
        )
        assert r.status_code == 422

    def test_quem_solicitou_pode_cancelar(self, client, auth_headers):
        a, _, ha, _, _, tid = self._cenario(client, auth_headers)
        r = client.post(f"/api/v1/transferencias/{tid}/cancelar", headers={**ha, "X-Planta-Id": str(a)})
        assert r.status_code == 200
        assert r.json()["status"] == "cancelada"

    def test_outro_usuario_nao_cancela(self, client, auth_headers):
        _, b, _, hb, _, tid = self._cenario(client, auth_headers)
        r = client.post(f"/api/v1/transferencias/{tid}/cancelar", headers={**hb, "X-Planta-Id": str(b)})
        assert r.status_code == 403

    def test_nao_decide_duas_vezes(self, client, auth_headers):
        _, b, _, hb, _, tid = self._cenario(client, auth_headers)
        client.post(f"/api/v1/transferencias/{tid}/recusar", data={"motivo_recusa": "Sem espaço"}, headers={**hb, "X-Planta-Id": str(b)})

        r = client.post(f"/api/v1/transferencias/{tid}/aprovar", headers=auth_headers)
        assert r.status_code == 400


class TestNotificacaoDePendencia:
    def test_destino_recebe_aviso_no_sino(self, client, auth_headers):
        a = _planta(client, auth_headers, "Bonito", "BON")
        b = _planta(client, auth_headers, "Tatuí", "TAT")
        ha = _usuario(client, auth_headers, "sino.origem@teste.com", a)
        hb = _usuario(client, auth_headers, "sino.destino@teste.com", b)
        ativo = _ativo(client, ha, a, "TR-SINO")
        _solicitar(client, ha, a, ativo["id"], b)

        itens = client.get("/api/v1/notificacoes", headers={**hb, "X-Planta-Id": str(b)}).json()["itens"]
        aviso = next((i for i in itens if i.get("transferencia_id")), None)
        assert aviso is not None, "quem recebe não foi avisado"
        assert "Aprovar chegada" in aviso["titulo"]
        assert "TR-SINO" in aviso["detalhe"]

    def test_origem_nao_recebe_aviso_de_aprovacao(self, client, auth_headers):
        """Quem enviou não tem nada para aprovar."""
        a = _planta(client, auth_headers, "Bonito", "BON")
        b = _planta(client, auth_headers, "Tatuí", "TAT")
        ha = _usuario(client, auth_headers, "sino2.origem@teste.com", a)
        ativo = _ativo(client, ha, a, "TR-SINO2")
        _solicitar(client, ha, a, ativo["id"], b)

        itens = client.get("/api/v1/notificacoes", headers={**ha, "X-Planta-Id": str(a)}).json()["itens"]
        assert not any(i.get("transferencia_id") for i in itens)

    def test_admin_e_avisado_depois_do_destino(self, client, auth_headers):
        a = _planta(client, auth_headers, "Bonito", "BON")
        b = _planta(client, auth_headers, "Tatuí", "TAT")
        ha = _usuario(client, auth_headers, "sino3.origem@teste.com", a)
        hb = _usuario(client, auth_headers, "sino3.destino@teste.com", b)
        ativo = _ativo(client, ha, a, "TR-SINO3")
        tid = _solicitar(client, ha, a, ativo["id"], b).json()["id"]

        # Antes da aprovação do destino, o admin não tem nada para decidir.
        antes = client.get("/api/v1/notificacoes", headers=auth_headers).json()["itens"]
        assert not any(i.get("transferencia_id") == tid for i in antes)

        client.post(f"/api/v1/transferencias/{tid}/aprovar", headers={**hb, "X-Planta-Id": str(b)})

        depois = client.get("/api/v1/notificacoes", headers=auth_headers).json()["itens"]
        aviso = next((i for i in depois if i.get("transferencia_id") == tid), None)
        assert aviso is not None
        assert "administrador" in aviso["titulo"].lower()


class TestListaDeDestinos:
    """O técnico precisa VER as plantas de destino.

    `/admin/plantas` é restrito ao administrador — usá-lo para montar a lista de
    destinos devolvia 403, a lista vinha vazia e a tela dizia "não há outra
    planta ativa" mesmo havendo várias cadastradas.
    """

    def test_tecnico_ve_as_plantas_para_destino(self, client, auth_headers):
        a = _planta(client, auth_headers, "Bonito", "BON")
        b = _planta(client, auth_headers, "Tatuí", "TAT")
        c = _planta(client, auth_headers, "Recife", "REC")
        h = _usuario(client, auth_headers, "dest.lista@teste.com", a)

        r = client.get("/api/v1/plantas/opcoes", headers=h)
        assert r.status_code == 200, r.text
        siglas = {p["sigla"] for p in r.json()}
        assert {"BON", "TAT", "REC"} <= siglas

        destinos = [p for p in r.json() if p["id"] != a]
        assert len(destinos) >= 2
        assert b in {p["id"] for p in destinos}
        assert c in {p["id"] for p in destinos}

    def test_leitor_tambem_ve_as_plantas(self, client, auth_headers):
        """Não é só o perfil TI: o endpoint é para qualquer usuário logado."""
        a = _planta(client, auth_headers, "Bonito", "BON")
        _planta(client, auth_headers, "Tatuí", "TAT")
        h = _usuario(client, auth_headers, "dest.leitor@teste.com", a, papel="leitor")

        assert client.get("/api/v1/plantas/opcoes", headers=h).status_code == 200

    def test_planta_inativa_nao_aparece_como_destino(self, client, auth_headers):
        a = _planta(client, auth_headers, "Bonito", "BON")
        b = _planta(client, auth_headers, "Tatuí", "TAT")
        h = _usuario(client, auth_headers, "dest.inativa@teste.com", a)

        client.put(
            f"/api/v1/admin/plantas/{b}",
            json={"nome": "Tatuí", "sigla": "TAT", "ativa": False},
            headers=auth_headers,
        )
        siglas = {p["sigla"] for p in client.get("/api/v1/plantas/opcoes", headers=h).json()}
        assert "TAT" not in siglas

    def test_nao_expoe_dados_administrativos(self, client, auth_headers):
        """A lista de destinos traz só o necessário para escolher."""
        a = _planta(client, auth_headers, "Bonito", "BON")
        h = _usuario(client, auth_headers, "dest.campos@teste.com", a)

        item = client.get("/api/v1/plantas/opcoes", headers=h).json()[0]
        assert set(item.keys()) == {"id", "sigla", "nome"}
        assert "cnpj" not in item and "total_ativos" not in item

    def test_transferencia_funciona_com_o_destino_escolhido(self, client, auth_headers):
        """Ponta a ponta: o técnico lista, escolhe e transfere."""
        a = _planta(client, auth_headers, "Bonito", "BON")
        _planta(client, auth_headers, "Tatuí", "TAT")
        ha = _usuario(client, auth_headers, "dest.fim@teste.com", a)
        ativo = _ativo(client, ha, a, "TR-DEST")

        destinos = client.get("/api/v1/plantas/opcoes", headers=ha).json()
        escolhido = next(p for p in destinos if p["id"] != a)

        r = client.post(
            "/api/v1/transferencias",
            data={"ativo_id": ativo["id"], "planta_destino_id": escolhido["id"], "motivo": "emprestimo"},
            headers={**ha, "X-Planta-Id": str(a)},
        )
        assert r.status_code == 201, r.text
        assert r.json()["planta_destino"] == escolhido["sigla"]


class TestVisibilidade:
    def test_planta_so_ve_o_que_lhe_diz_respeito(self, client, auth_headers):
        a = _planta(client, auth_headers, "Bonito", "BON")
        b = _planta(client, auth_headers, "Tatuí", "TAT")
        c = _planta(client, auth_headers, "Recife", "REC")
        ha = _usuario(client, auth_headers, "vis.origem@teste.com", a)
        hc = _usuario(client, auth_headers, "vis.fora@teste.com", c)
        ativo = _ativo(client, ha, a, "TR-VIS")
        _solicitar(client, ha, a, ativo["id"], b)

        # A planta C não participa: não deve ver nada.
        vistos = client.get("/api/v1/transferencias", headers={**hc, "X-Planta-Id": str(c)}).json()
        assert vistos["total"] == 0

        # A origem e o destino veem.
        assert client.get("/api/v1/transferencias", headers={**ha, "X-Planta-Id": str(a)}).json()["total"] == 1
        assert client.get("/api/v1/transferencias", headers=auth_headers).json()["total"] >= 1

    def test_historico_guardado_na_auditoria(self, client, auth_headers):
        a = _planta(client, auth_headers, "Bonito", "BON")
        b = _planta(client, auth_headers, "Tatuí", "TAT")
        ha = _usuario(client, auth_headers, "aud.origem@teste.com", a)
        hb = _usuario(client, auth_headers, "aud.destino@teste.com", b)
        ativo = _ativo(client, ha, a, "TR-AUD")
        tid = _solicitar(client, ha, a, ativo["id"], b).json()["id"]
        client.post(f"/api/v1/transferencias/{tid}/aprovar", headers={**hb, "X-Planta-Id": str(b)})
        client.post(f"/api/v1/transferencias/{tid}/aprovar", headers=auth_headers)

        acoes = [
            linha["acao"]
            for linha in client.get("/api/v1/admin/auditoria", params={"por_pagina": 200}, headers=auth_headers).json()["itens"]
        ]
        assert "transferencia_solicitada" in acoes
        assert "transferencia_aprovada_destino" in acoes
        assert "transferencia_aprovada" in acoes
