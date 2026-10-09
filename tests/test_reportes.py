"""Reporte de erro — canal de retorno da implantação.

Regras: **qualquer** usuário envia (título + descrição + print opcional);
**só o administrador** vê a lista. O recurso pode ser desligado pelo `.env`.
"""
from __future__ import annotations

import io

import pytest

from app.core.rate_limit import login_limiter, scan_limiter

# PNG 1x1 válido, para o upload do print.
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c6360000002000154a24f5f0000000049454e44ae426082"
)


@pytest.fixture(autouse=True)
def _liberar_rate_limit():
    login_limiter._hits.clear()
    scan_limiter._hits.clear()
    yield
    login_limiter._hits.clear()
    scan_limiter._hits.clear()


def _leitor(client, auth_headers, email="rep@teste.com"):
    client.post(
        "/api/v1/usuarios",
        json={"nome": "Reporter", "email": email, "papel": "leitor", "senha": "senha123"},
        headers=auth_headers,
    )
    login = client.post("/api/v1/auth/login", data={"username": email, "password": "senha123"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _enviar(client, headers, **extra):
    dados = {"titulo": "Erro no filtro", "descricao": "Ao filtrar, a lista some.", "tela": "Ativos", **extra}
    files = None
    if dados.pop("com_print", False):
        files = {"arquivo": ("print.png", io.BytesIO(PNG_1PX), "image/png")}
    return client.post("/api/v1/reportes", data=dados, files=files, headers=headers)


class TestEnvioDeReporte:
    def test_qualquer_usuario_pode_enviar(self, client, auth_headers):
        h = _leitor(client, auth_headers)
        r = _enviar(client, h)

        assert r.status_code == 201, r.text
        corpo = r.json()
        assert corpo["titulo"] == "Erro no filtro"
        assert corpo["status"] == "aberto"
        assert corpo["status_rotulo"] == "Aberto"
        assert corpo["usuario_nome"] == "Reporter"
        assert corpo["tem_imagem"] is False

    def test_envio_com_print(self, client, auth_headers):
        h = _leitor(client, auth_headers, "rep.print@teste.com")
        r = _enviar(client, h, com_print=True)

        assert r.status_code == 201, r.text
        assert r.json()["tem_imagem"] is True

    def test_titulo_curto_demais_e_recusado(self, client, auth_headers):
        h = _leitor(client, auth_headers, "rep.curto@teste.com")
        r = _enviar(client, h, titulo="ab")
        assert r.status_code == 422

    def test_descricao_vazia_e_recusada(self, client, auth_headers):
        h = _leitor(client, auth_headers, "rep.vazio@teste.com")
        r = _enviar(client, h, descricao="")
        assert r.status_code == 422

    def test_arquivo_que_nao_e_imagem_e_recusado(self, client, auth_headers):
        h = _leitor(client, auth_headers, "rep.txt@teste.com")
        r = client.post(
            "/api/v1/reportes",
            data={"titulo": "Teste", "descricao": "Descrição do problema"},
            files={"arquivo": ("nota.txt", io.BytesIO(b"nao e imagem"), "text/plain")},
            headers=h,
        )
        assert r.status_code == 400
        assert "imagem" in r.json()["detail"].lower()

    def test_envio_e_auditado(self, client, auth_headers):
        _enviar(client, _leitor(client, auth_headers, "rep.aud@teste.com"))

        logs = client.get("/api/v1/admin/auditoria", params={"acao": "reporte_erro"}, headers=auth_headers).json()["itens"]
        assert logs, "o envio não foi auditado"
        assert logs[0]["usuario_nome"] == "Reporter"


class TestListagemSomenteAdmin:
    def test_leitor_nao_ve_a_lista(self, client, auth_headers):
        h = _leitor(client, auth_headers, "rep.nolist@teste.com")
        _enviar(client, h)

        assert client.get("/api/v1/reportes", headers=h).status_code == 403

    def test_admin_ve_todos_com_autor(self, client, auth_headers):
        _enviar(client, _leitor(client, auth_headers, "rep.admin@teste.com"))

        r = client.get("/api/v1/reportes", headers=auth_headers)
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["total"] >= 1
        item = corpo["itens"][0]
        assert item["usuario_nome"] == "Reporter"
        assert item["usuario_email"] == "rep.admin@teste.com"
        assert item["tela"] == "Ativos"
        assert corpo["por_status"]["aberto"] >= 1

    def test_filtro_por_situacao(self, client, auth_headers):
        _enviar(client, _leitor(client, auth_headers, "rep.filtro@teste.com"))

        abertos = client.get("/api/v1/reportes", params={"status": "aberto"}, headers=auth_headers).json()
        resolvidos = client.get("/api/v1/reportes", params={"status": "resolvido"}, headers=auth_headers).json()

        assert abertos["total"] >= 1
        assert all(i["status"] == "aberto" for i in abertos["itens"])
        assert resolvidos["total"] == 0

    def test_print_acessivel_ao_autor_e_ao_admin(self, client, auth_headers):
        h = _leitor(client, auth_headers, "rep.img@teste.com")
        rid = _enviar(client, h, com_print=True).json()["id"]

        assert client.get(f"/api/v1/reportes/{rid}/imagem", headers=h).status_code == 200
        assert client.get(f"/api/v1/reportes/{rid}/imagem", headers=auth_headers).status_code == 200

    def test_outro_usuario_nao_ve_o_print(self, client, auth_headers):
        h1 = _leitor(client, auth_headers, "rep.dono@teste.com")
        rid = _enviar(client, h1, com_print=True).json()["id"]
        h2 = _leitor(client, auth_headers, "rep.outro@teste.com")

        assert client.get(f"/api/v1/reportes/{rid}/imagem", headers=h2).status_code == 403

    def test_reportar_sem_print_nao_tem_imagem(self, client, auth_headers):
        h = _leitor(client, auth_headers, "rep.noprint@teste.com")
        rid = _enviar(client, h).json()["id"]
        assert client.get(f"/api/v1/reportes/{rid}/imagem", headers=h).status_code == 404


class TestTriagemPeloAdmin:
    def test_admin_muda_situacao_e_anota(self, client, auth_headers):
        h = _leitor(client, auth_headers, "rep.tri@teste.com")
        rid = _enviar(client, h).json()["id"]

        r = client.patch(
            f"/api/v1/reportes/{rid}",
            data={"status": "resolvido", "observacao_admin": "Corrigido na versão 2.19"},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["status_rotulo"] == "Resolvido"
        assert r.json()["observacao_admin"] == "Corrigido na versão 2.19"

    def test_situacao_invalida_e_recusada(self, client, auth_headers):
        h = _leitor(client, auth_headers, "rep.inv@teste.com")
        rid = _enviar(client, h).json()["id"]

        r = client.patch(f"/api/v1/reportes/{rid}", data={"status": "inventado"}, headers=auth_headers)
        assert r.status_code == 400

    def test_leitor_nao_muda_situacao(self, client, auth_headers):
        h = _leitor(client, auth_headers, "rep.sem@teste.com")
        rid = _enviar(client, h).json()["id"]
        assert client.patch(f"/api/v1/reportes/{rid}", data={"status": "resolvido"}, headers=h).status_code == 403

    def test_admin_exclui(self, client, auth_headers):
        h = _leitor(client, auth_headers, "rep.del@teste.com")
        rid = _enviar(client, h).json()["id"]

        assert client.delete(f"/api/v1/reportes/{rid}", headers=auth_headers).status_code == 204
        assert client.get(f"/api/v1/reportes/{rid}/imagem", headers=auth_headers).status_code == 404

    def test_leitor_nao_exclui(self, client, auth_headers):
        h = _leitor(client, auth_headers, "rep.del2@teste.com")
        rid = _enviar(client, h).json()["id"]
        assert client.delete(f"/api/v1/reportes/{rid}", headers=h).status_code == 403


class TestMeusReportes:
    """O autor acompanha o que enviou e em que situação está.

    A situação é definida pelo administrador na triagem — é o retorno que o
    usuário recebe.
    """

    def test_usuario_ve_os_proprios_reportes(self, client, auth_headers):
        h = _leitor(client, auth_headers, "meus.a@teste.com")
        _enviar(client, h, titulo="Meu primeiro erro")

        r = client.get("/api/v1/reportes/meus", headers=h)
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["total"] == 1
        assert corpo["itens"][0]["titulo"] == "Meu primeiro erro"
        assert corpo["itens"][0]["status"] == "aberto"

    def test_sem_reportes_retorna_lista_vazia(self, client, auth_headers):
        h = _leitor(client, auth_headers, "meus.vazio@teste.com")
        r = client.get("/api/v1/reportes/meus", headers=h).json()
        assert r["total"] == 0
        assert r["itens"] == []

    def test_nao_ve_reporte_de_outro_usuario(self, client, auth_headers):
        h1 = _leitor(client, auth_headers, "meus.dono@teste.com")
        _enviar(client, h1, titulo="Erro do dono")
        h2 = _leitor(client, auth_headers, "meus.outro@teste.com")

        r = client.get("/api/v1/reportes/meus", headers=h2).json()
        assert r["total"] == 0, "não pode ver reporte de outra pessoa"

    def test_status_acompanha_a_triagem_do_admin(self, client, auth_headers):
        """O ponto central: o autor vê a situação que o administrador definiu."""
        h = _leitor(client, auth_headers, "meus.status@teste.com")
        rid = _enviar(client, h).json()["id"]

        # Ainda aberto.
        assert client.get("/api/v1/reportes/meus", headers=h).json()["itens"][0]["status_rotulo"] == "Aberto"

        # O administrador move para "em análise".
        client.patch(f"/api/v1/reportes/{rid}", data={"status": "em_analise"}, headers=auth_headers)
        item = client.get("/api/v1/reportes/meus", headers=h).json()["itens"][0]
        assert item["status"] == "em_analise"
        assert item["status_rotulo"] == "Em análise"

        # E depois para "resolvido".
        client.patch(f"/api/v1/reportes/{rid}", data={"status": "resolvido"}, headers=auth_headers)
        item = client.get("/api/v1/reportes/meus", headers=h).json()["itens"][0]
        assert item["status_rotulo"] == "Resolvido"

    def test_resumo_conta_por_situacao(self, client, auth_headers):
        h = _leitor(client, auth_headers, "meus.resumo@teste.com")
        r1 = _enviar(client, h, titulo="Erro um").json()["id"]
        _enviar(client, h, titulo="Erro dois")
        client.patch(f"/api/v1/reportes/{r1}", data={"status": "resolvido"}, headers=auth_headers)

        corpo = client.get("/api/v1/reportes/meus", headers=h).json()
        assert corpo["total"] == 2
        assert corpo["por_status"]["resolvido"] == 1
        assert corpo["por_status"]["aberto"] == 1

    def test_anotacao_interna_nao_vaza_para_o_autor(self, client, auth_headers):
        """O campo é do administrador; o autor vê a situação, não a nota interna."""
        h = _leitor(client, auth_headers, "meus.nota@teste.com")
        rid = _enviar(client, h).json()["id"]
        client.patch(
            f"/api/v1/reportes/{rid}",
            data={"status": "resolvido", "observacao_admin": "Culpa do cache do navegador"},
            headers=auth_headers,
        )

        item = client.get("/api/v1/reportes/meus", headers=h).json()["itens"][0]
        assert "observacao_admin" not in item, "a anotação interna não pode aparecer para o autor"

        # Mas o administrador continua vendo.
        item_admin = client.get("/api/v1/reportes", headers=auth_headers).json()["itens"][0]
        assert item_admin["observacao_admin"] == "Culpa do cache do navegador"

    def test_autor_ve_o_proprio_print(self, client, auth_headers):
        h = _leitor(client, auth_headers, "meus.print@teste.com")
        rid = _enviar(client, h, com_print=True).json()["id"]

        item = client.get("/api/v1/reportes/meus", headers=h).json()["itens"][0]
        assert item["tem_imagem"] is True
        assert client.get(f"/api/v1/reportes/{rid}/imagem", headers=h).status_code == 200

    def test_admin_tambem_tem_os_proprios(self, client, auth_headers):
        _enviar(client, auth_headers, titulo="Erro do admin")
        r = client.get("/api/v1/reportes/meus", headers=auth_headers).json()
        assert any(i["titulo"] == "Erro do admin" for i in r["itens"])


class TestDesativacao:
    """O recurso é temporário: precisa dar para desligar com uma variável."""

    def test_disponivel_quando_ligado(self, client, auth_headers):
        assert client.get("/api/v1/reportes/disponivel", headers=auth_headers).json()["ativo"] is True

    def test_desligado_recusa_novos_envios(self, client, auth_headers, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "reporte_erro_ativo", False)
        h = _leitor(client, auth_headers, "rep.off@teste.com")

        assert client.get("/api/v1/reportes/disponivel", headers=h).json()["ativo"] is False
        assert _enviar(client, h).status_code == 404

    def test_desligado_mantem_o_historico_para_o_admin(self, client, auth_headers, monkeypatch):
        """Desligar não pode apagar o que já foi reportado."""
        from app.config import settings

        h = _leitor(client, auth_headers, "rep.hist@teste.com")
        _enviar(client, h)

        monkeypatch.setattr(settings, "reporte_erro_ativo", False)
        r = client.get("/api/v1/reportes", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["ativo"] is False
        assert r.json()["total"] >= 1
