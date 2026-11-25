"""Fase 1 (#5) — escopo de planta em manutenções e movimentações.

## O que estava aberto

Nenhum dos dois routers usava `aplicar_filtro` nem `planta_ativa`. As listas
traziam registros de **todas** as unidades, e o detalhe buscava por id sem
conferir nada:

    db.get(Manutencao, manut_id)     # qualquer planta
    db.get(Movimentacao, mov_id)     # qualquer planta

Era o achado que o parecer marcou como "de análise anterior" — o mais antigo,
e o que ficou mais tempo exposto enquanto o módulo novo já estava corrigido.
"""
from __future__ import annotations

import pytest


def _planta(db, sigla):
    from app.models.core import Planta

    p = Planta(nome=f"Unidade {sigla}", sigla=sigla)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _ativo(db, planta, patrimonio, dominio="ti"):
    from app.models.core import Ativo

    a = Ativo(dominio=dominio, tipo_item="ativo", patrimonio=patrimonio, numero_serie=f"NS-{patrimonio}",
              planta_id=planta.id, status="estoque")
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _manutencao(db, ativo):
    from app.models.core import Manutencao

    m = Manutencao(ativo_id=ativo.id, descricao="Teste", status="aberta")
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def _movimentacao(db, ativo):
    from app.models.core import Movimentacao

    m = Movimentacao(ativo_id=ativo.id, tipo="entrada", quantidade=1)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@pytest.fixture
def db_session(client):
    from app.database import get_db
    from app.main import app

    return next(app.dependency_overrides[get_db]())


def _usuario_da_planta(client, planta_id, permissoes=None, *, perfil="escopo"):
    from app.core.security import create_access_token, hash_password
    from app.database import get_db
    from app.main import app
    from app.models.core import Usuario

    db = next(app.dependency_overrides[get_db]())
    u = Usuario(nome=f"U{planta_id}", email=f"{perfil}{planta_id}@teste.com",
                senha_hash=hash_password("senha123"), papel="ti",
                ativo=True, planta_id=planta_id, permissoes=permissoes)
    db.add(u)
    db.commit()
    db.refresh(u)
    return {"Authorization": f"Bearer {create_access_token(u.id, u.papel.value, u.email)}"}


class TestManutencoes:
    def test_a_lista_nao_traz_outra_planta(self, client, db_session):
        a = _planta(db_session, "A")
        b = _planta(db_session, "B")
        _manutencao(db_session, _ativo(db_session, a, "A-1"))
        _manutencao(db_session, _ativo(db_session, b, "B-1"))

        h = _usuario_da_planta(client, a.id)
        r = client.get("/api/v1/manutencoes", headers=h)
        assert r.status_code == 200, r.text

        itens = r.json().get("items", r.json() if isinstance(r.json(), list) else [])
        patrimonios = [i.get("ativo_patrimonio") or i.get("patrimonio") for i in itens]
        assert not any(p and p.startswith("B-") for p in patrimonios), (
            "a lista trouxe manutenção de outra unidade"
        )

    def test_o_detalhe_de_outra_planta_da_404(self, client, db_session):
        a = _planta(db_session, "A")
        b = _planta(db_session, "B")
        alheia = _manutencao(db_session, _ativo(db_session, b, "B-2"))

        h = _usuario_da_planta(client, a.id)
        r = client.get(f"/api/v1/manutencoes/{alheia.id}", headers=h)
        assert r.status_code == 404, "viu a manutenção de outra unidade"

    def test_a_propria_planta_funciona(self, client, db_session):
        a = _planta(db_session, "A")
        minha = _manutencao(db_session, _ativo(db_session, a, "A-2"))

        h = _usuario_da_planta(client, a.id)
        r = client.get(f"/api/v1/manutencoes/{minha.id}", headers=h)
        assert r.status_code == 200, "não achou a própria manutenção"

    def test_administrador_ve_todas(self, client, auth_headers, db_session):
        b = _planta(db_session, "B")
        alheia = _manutencao(db_session, _ativo(db_session, b, "B-3"))

        r = client.get(f"/api/v1/manutencoes/{alheia.id}", headers=auth_headers)
        assert r.status_code == 200, "o administrador deveria ver todas as unidades"

    def test_abertura_respeita_planta_do_ativo(self, client, db_session):
        a = _planta(db_session, "A")
        b = _planta(db_session, "B")
        ativo_a = _ativo(db_session, a, "A-1")
        ativo_b = _ativo(db_session, b, "B-1")
        headers = _usuario_da_planta(client, a.id)

        caminho = "/api/v1/manutencoes"
        assert client.post(caminho, json={"ativo_id": ativo_b.id}, headers=headers).status_code == 404
        assert client.post(caminho, json={"ativo_id": ativo_a.id}, headers=headers).status_code == 201

    def test_anexos_seguem_a_planta_da_manutencao(self, client, auth_headers, db_session):
        a = _planta(db_session, "A")
        b = _planta(db_session, "B")
        manut = _manutencao(db_session, _ativo(db_session, b, "B-1"))
        headers_a = _usuario_da_planta(client, a.id)
        headers_b = _usuario_da_planta(client, b.id)
        caminho = f"/api/v1/manutencoes/{manut.id}/anexos"
        arquivo = {"file": ("laudo.txt", b"Laudo de teste", "text/plain")}

        assert client.post(caminho, files=arquivo, headers=headers_a).status_code == 404
        upload = client.post(caminho, files=arquivo, headers=headers_b)
        assert upload.status_code == 200, upload.text
        anexo_id = upload.json()["id"]
        download = f"{caminho}/{anexo_id}/download"
        assert client.get(caminho, headers=headers_a).status_code == 404
        assert client.get(download, headers=headers_a).status_code == 404
        assert client.get(download, headers=headers_b).content == b"Laudo de teste"

        admin_a = {**auth_headers, "X-Planta-Id": str(a.id)}
        assert client.get(download, headers=admin_a).status_code == 404
        assert client.get(download, headers=auth_headers).status_code == 200

        from io import BytesIO

        from reportlab.pdfgen.canvas import Canvas

        pdf = BytesIO()
        documento = Canvas(pdf)
        documento.drawString(50, 750, "Laudo de teste")
        documento.save()
        assert client.post(
            caminho, files={"file": ("laudo.pdf", b"%PDF-1.7\n", "application/pdf")}, headers=headers_b,
        ).status_code == 400
        upload_pdf = client.post(
            caminho, files={"file": ("laudo.pdf", pdf.getvalue(), "application/octet-stream")}, headers=headers_b,
        )
        assert upload_pdf.status_code == 200, upload_pdf.text
        arquivo_pdf = client.get(f"{caminho}/{upload_pdf.json()['id']}/download", headers=headers_b)
        assert arquivo_pdf.content == pdf.getvalue()
        assert arquivo_pdf.headers["content-type"] == "application/pdf"
        assert arquivo_pdf.headers["content-disposition"].startswith("attachment")

    def test_exclusao_exige_permissao_propria(self, client, db_session):
        a = _planta(db_session, "A")
        b = _planta(db_session, "B")
        manut = _manutencao(db_session, _ativo(db_session, a, "A-1"))
        outro = _manutencao(db_session, _ativo(db_session, b, "B-1"))
        caminho = f"/api/v1/manutencoes/{manut.id}"
        editor = _usuario_da_planta(client, a.id)

        assert client.patch(caminho, json={"descricao": "Em revisão"}, headers=editor).status_code == 200
        assert client.delete(caminho, headers=editor).status_code == 403

        exclusao = _usuario_da_planta(
            client, a.id, {"pode_escrever": False, "pode_excluir": True}, perfil="exclusao",
        )
        assert client.patch(caminho, json={"descricao": "Em revisão"}, headers=exclusao).status_code == 403
        assert client.delete(f"/api/v1/manutencoes/{outro.id}", headers=exclusao).status_code == 404
        assert client.delete(caminho, headers=exclusao).status_code == 204
        assert client.get(f"{caminho}/anexos", headers=exclusao).status_code == 404


class TestAtivosPorPlanta:
    def test_operacoes_e_registros_filhos_respeitam_a_planta(self, client, db_session):
        a = _planta(db_session, "A")
        b = _planta(db_session, "B")
        impressora = _ativo(db_session, b, "B-1", dominio="impressora")
        headers_a = _usuario_da_planta(client, a.id, {"pode_excluir": True})
        headers_b = _usuario_da_planta(client, b.id)
        caminho = f"/api/v1/ativos/{impressora.id}"
        suprimento = {"tipo": "toner"}

        assert client.patch(f"{caminho}/status", json={"status": "em_uso"}, headers=headers_a).status_code == 404
        assert client.patch(f"{caminho}/status", json={"status": "em_uso"}, headers=headers_b).status_code == 200
        for recurso in ("termos", "leituras", "suprimentos"):
            assert client.get(f"{caminho}/{recurso}", headers=headers_a).status_code == 404
            assert client.get(f"{caminho}/{recurso}", headers=headers_b).status_code == 200

        leitura = {"contador": 100}
        assert client.post(f"{caminho}/leituras", json=leitura, headers=headers_a).status_code == 404
        assert client.post(f"{caminho}/leituras", json=leitura, headers=headers_b).status_code == 201
        monitor = f"/api/v1/monitor/impressoras/{impressora.id}"
        assert client.get(f"{monitor}/alertas", headers=headers_a).status_code == 404
        assert client.post(f"{monitor}/coletar", headers=headers_a).status_code == 404
        assert client.get(f"{monitor}/situacao", headers=headers_a).status_code == 404
        sem_monitor = _usuario_da_planta(client, b.id, {"modulos": ["mapa"]}, perfil="mapa")
        assert client.get(f"{monitor}/situacao", headers=sem_monitor).status_code == 403

        atribuicao = client.post(f"{caminho}/atribuir", json={"usuario_id": 1}, headers=headers_b)
        assert atribuicao.status_code == 200, atribuicao.text
        termo = client.get(f"{caminho}/termos", headers=headers_b).json()[0]
        pdf = f"{caminho}/termos/{termo['id']}/pdf"
        assert client.get(pdf, headers=headers_a).status_code == 404
        assert client.get(pdf, headers=headers_b).content.startswith(b"%PDF")

        cadastro = client.post(f"{caminho}/suprimentos", json=suprimento, headers=headers_b)
        assert cadastro.status_code == 201, cadastro.text
        suprimento_id = cadastro.json()["id"]
        assert client.delete(f"/api/v1/ativos/suprimentos/{suprimento_id}", headers=headers_a).status_code == 404
        assert client.delete(caminho, headers=headers_a).status_code == 404
        assert client.get(caminho, headers=headers_b).status_code == 200

    def test_indicadores_respeitam_planta_inclusive_no_alias(self, client, auth_headers, db_session):
        a = _planta(db_session, "A")
        b = _planta(db_session, "B")
        _ativo(db_session, a, "A-1")
        _ativo(db_session, b, "B-1")
        headers_a = _usuario_da_planta(client, a.id)

        for caminho in ("/api/v1/ativos/stats", "/api/v1/dashboard/stats"):
            local = client.get(caminho, headers=headers_a)
            admin = client.get(caminho, headers=auth_headers)
            assert local.json()["total"] == 1
            assert admin.json()["total"] == 2


class TestMovimentacoes:
    def test_o_detalhe_de_outra_planta_da_404(self, client, db_session):
        a = _planta(db_session, "A")
        b = _planta(db_session, "B")
        alheia = _movimentacao(db_session, _ativo(db_session, b, "B-4"))

        h = _usuario_da_planta(client, a.id)
        r = client.get(f"/api/v1/movimentacoes/{alheia.id}", headers=h)
        assert r.status_code == 404

    def test_a_propria_planta_funciona(self, client, db_session):
        a = _planta(db_session, "A")
        minha = _movimentacao(db_session, _ativo(db_session, a, "A-3"))

        h = _usuario_da_planta(client, a.id)
        r = client.get(f"/api/v1/movimentacoes/{minha.id}", headers=h)
        assert r.status_code == 200

    def test_a_lista_nao_traz_outra_planta(self, client, db_session):
        a = _planta(db_session, "A")
        b = _planta(db_session, "B")
        _movimentacao(db_session, _ativo(db_session, a, "A-4"))
        _movimentacao(db_session, _ativo(db_session, b, "B-5"))

        h = _usuario_da_planta(client, a.id)
        r = client.get("/api/v1/movimentacoes", headers=h)
        assert r.status_code == 200
        itens = r.json().get("items", r.json() if isinstance(r.json(), list) else [])
        assert len(itens) < 2 or not any(
            (i.get("ativo_patrimonio") or "").startswith("B-") for i in itens
        )


class TestSemPlanta:
    def test_usuario_sem_planta_e_barrado(self, client, db_session):
        """Sem planta, `planta` seria `None` e o filtro não seria aplicado —
        a pessoa veria TUDO, o oposto do desejado."""
        from app.core.security import create_access_token, hash_password
        from app.models.core import Usuario

        u = Usuario(nome="Sem", email="semplanta@teste.com",
                    senha_hash=hash_password("senha123"), papel="ti",
                    ativo=True, planta_id=None)
        db_session.add(u)
        db_session.commit()
        db_session.refresh(u)
        h = {"Authorization": f"Bearer {create_access_token(u.id, u.papel.value, u.email)}"}

        planta = _planta(db_session, "A")
        _manutencao(db_session, _ativo(db_session, planta, "A-1"))

        for caminho in ("/api/v1/manutencoes", "/api/v1/ativos", "/api/v1/monitor/impressoras"):
            assert client.get(caminho, headers=h).status_code == 400
