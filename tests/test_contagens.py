"""Inventário cíclico (contagem).

O que estes testes protegem é o **relatório de divergências** — a razão de a
contagem existir. Sem ele, escanear 6.000 itens não prova nada a uma auditoria.
"""
from __future__ import annotations

import pytest

from app.core.security import create_access_token
from app.models.core import Usuario
from app.models.enums import PapelUsuario


@pytest.fixture
def admin(client):
    """Token do administrador que o conftest já cria.

    A aprovação da contagem decide sobre patrimônio, então exige o papel de
    administrador — não basta estar autenticado. A sessão vem do conftest
    porque os testes rodam num banco em memória próprio.
    """
    from tests.conftest import TestingSession

    db = TestingSession()
    u = db.query(Usuario).filter(Usuario.email == "admin@teste.com").first()
    token = create_access_token(u.id, PapelUsuario.ADMIN.value)
    db.close()
    return {"Authorization": f"Bearer {token}"}


def _ativo(client, h, patrimonio, **extra):
    corpo = {"dominio": "ti", "patrimonio": patrimonio, "tipo_item": "ativo", **extra}
    r = client.post("/api/v1/ativos", json=corpo, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _contagem(client, h, **extra):
    corpo = {"nome": "Contagem de teste", **extra}
    r = client.post("/api/v1/contagens", json=corpo, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _ler(client, h, cid, codigo):
    return client.post(f"/api/v1/contagens/{cid}/ler", json={"codigo": codigo}, headers=h)


class TestAbertura:
    def test_cria_contagem(self, client, auth_headers):
        c = _contagem(client, auth_headers)
        assert c["id"]
        assert c["status"] == "aberta"

    def test_lista_contagens(self, client, auth_headers):
        _contagem(client, auth_headers, nome="Primeira")
        r = client.get("/api/v1/contagens", headers=auth_headers).json()
        assert r["total"] >= 1

    def test_dominio_invalido_e_recusado(self, client, auth_headers):
        r = client.post("/api/v1/contagens",
                        json={"nome": "X", "dominio": "inventado"}, headers=auth_headers)
        assert r.status_code == 400

    def test_escopo_por_dominio(self, client, auth_headers):
        _ativo(client, auth_headers, "ESC-TI-1")
        c = _contagem(client, auth_headers, dominio="impressora")
        r = client.get(f"/api/v1/contagens/{c['id']}/divergencias", headers=auth_headers).json()
        # A contagem é de impressoras: nenhum ativo de TI deve ser cobrado nela.
        assert not any(d["patrimonio"] == "ESC-TI-1" for d in r["nao_encontrados"])


class TestLeitura:
    def test_leitura_por_patrimonio(self, client, auth_headers):
        a = _ativo(client, auth_headers, "LE-1")
        c = _contagem(client, auth_headers)

        r = _ler(client, auth_headers, c["id"], "LE-1")
        assert r.status_code == 201, r.text
        corpo = r.json()
        assert corpo["item"]["resultado"] == "conforme"
        assert corpo["item"]["ativo_id"] == a["id"]
        assert "Conforme" in corpo["mensagem"]

    def test_leitura_por_hostname(self, client, auth_headers):
        """O técnico digita o nome da máquina na rede, não a etiqueta."""
        a = _ativo(client, auth_headers, "LE-2")
        client.put(f"/api/v1/ativos/{a['id']}",
                   json={"ti": {"hostname": "LEHOST02"}}, headers=auth_headers)

        c = _contagem(client, auth_headers)
        r = _ler(client, auth_headers, c["id"], "LEHOST02")
        assert r.status_code == 201, r.text
        assert r.json()["item"]["ativo_id"] == a["id"]

    def test_leitura_por_numero_de_serie(self, client, auth_headers):
        a = _ativo(client, auth_headers, "LE-3", numero_serie="SERIE-XYZ-9")
        c = _contagem(client, auth_headers)
        assert _ler(client, auth_headers, c["id"], "SERIE-XYZ-9").json()["item"]["ativo_id"] == a["id"]

    def test_codigo_desconhecido_vira_nao_cadastrado(self, client, auth_headers):
        """Achado fora do cadastro é registrado, não descartado."""
        c = _contagem(client, auth_headers)
        r = _ler(client, auth_headers, c["id"], "CODIGO-QUE-NAO-EXISTE")
        assert r.status_code == 201, r.text
        corpo = r.json()
        assert corpo["item"]["resultado"] == "nao_cadastrado"
        assert corpo["item"]["ativo_id"] is None
        assert "Não cadastrado" in corpo["mensagem"]

    def test_leitura_repetida_e_sinalizada(self, client, auth_headers):
        _ativo(client, auth_headers, "LE-4")
        c = _contagem(client, auth_headers)

        assert _ler(client, auth_headers, c["id"], "LE-4").json()["repetido"] is False
        segunda = _ler(client, auth_headers, c["id"], "LE-4").json()
        assert segunda["repetido"] is True
        assert "Já lido" in segunda["mensagem"]

    def test_contador_de_lidos_avanca(self, client, auth_headers):
        _ativo(client, auth_headers, "LE-5")
        _ativo(client, auth_headers, "LE-6")
        c = _contagem(client, auth_headers)

        assert _ler(client, auth_headers, c["id"], "LE-5").json()["total_lidos"] == 1
        assert _ler(client, auth_headers, c["id"], "LE-6").json()["total_lidos"] == 2

    def test_primeira_leitura_muda_o_status(self, client, auth_headers):
        _ativo(client, auth_headers, "LE-7")
        c = _contagem(client, auth_headers)
        _ler(client, auth_headers, c["id"], "LE-7")

        d = client.get(f"/api/v1/contagens/{c['id']}", headers=auth_headers).json()
        assert d["status"] == "em_contagem"

    def test_lista_de_itens(self, client, auth_headers):
        _ativo(client, auth_headers, "LE-8")
        c = _contagem(client, auth_headers)
        _ler(client, auth_headers, c["id"], "LE-8")

        itens = client.get(f"/api/v1/contagens/{c['id']}/itens", headers=auth_headers).json()
        assert len(itens) == 1
        assert itens[0]["codigo_lido"] == "LE-8"
        assert itens[0]["lido_por_nome"], "o histórico precisa dizer quem leu"


class TestDivergencias:
    def test_nao_encontrado(self, client, auth_headers):
        _ativo(client, auth_headers, "DV-1")
        c = _contagem(client, auth_headers)

        r = client.get(f"/api/v1/contagens/{c['id']}/divergencias", headers=auth_headers).json()
        assert any(d["patrimonio"] == "DV-1" for d in r["nao_encontrados"])

    def test_encontrado_sai_da_lista(self, client, auth_headers):
        _ativo(client, auth_headers, "DV-2")
        c = _contagem(client, auth_headers)
        _ler(client, auth_headers, c["id"], "DV-2")

        r = client.get(f"/api/v1/contagens/{c['id']}/divergencias", headers=auth_headers).json()
        assert not any(d["patrimonio"] == "DV-2" for d in r["nao_encontrados"])
        assert r["conformes"] >= 1

    def test_percentual_de_conformidade(self, client, auth_headers):
        _ativo(client, auth_headers, "DV-3")
        _ativo(client, auth_headers, "DV-4")
        c = _contagem(client, auth_headers)
        _ler(client, auth_headers, c["id"], "DV-3")

        r = client.get(f"/api/v1/contagens/{c['id']}/divergencias", headers=auth_headers).json()
        assert r["esperados"] >= 2
        assert 0 < r["percentual"] < 100

    def test_nao_cadastrado_aparece_no_relatorio(self, client, auth_headers):
        c = _contagem(client, auth_headers)
        _ler(client, auth_headers, c["id"], "FANTASMA-1")

        r = client.get(f"/api/v1/contagens/{c['id']}/divergencias", headers=auth_headers).json()
        assert any(d["codigo_lido"] == "FANTASMA-1" for d in r["nao_cadastrados"])

    def test_repetidos_aparecem(self, client, auth_headers):
        _ativo(client, auth_headers, "DV-5")
        c = _contagem(client, auth_headers)
        _ler(client, auth_headers, c["id"], "DV-5")
        _ler(client, auth_headers, c["id"], "DV-5")

        r = client.get(f"/api/v1/contagens/{c['id']}/divergencias", headers=auth_headers).json()
        assert r["repetidos"], "leitura em duplicidade precisa ser apontada"


class TestFechamento:
    def test_finalizar_encerra_a_leitura(self, client, auth_headers):
        c = _contagem(client, auth_headers)
        r = client.post(f"/api/v1/contagens/{c['id']}/finalizar", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["status"] == "finalizada"

        # Depois de finalizada não se lê mais.
        assert _ler(client, auth_headers, c["id"], "QUALQUER").status_code == 400

    def test_nao_finaliza_duas_vezes(self, client, auth_headers):
        c = _contagem(client, auth_headers)
        client.post(f"/api/v1/contagens/{c['id']}/finalizar", headers=auth_headers)
        r = client.post(f"/api/v1/contagens/{c['id']}/finalizar", headers=auth_headers)
        assert r.status_code == 400

    def test_aprovar_exige_finalizar_antes(self, client, auth_headers, admin):
        c = _contagem(client, auth_headers)
        r = client.post(f"/api/v1/contagens/{c['id']}/aprovar", json={}, headers=admin)
        assert r.status_code == 400

    def test_aprovar_sem_baixar_preserva_os_ativos(self, client, auth_headers, admin):
        a = _ativo(client, auth_headers, "AP-1")
        c = _contagem(client, auth_headers)
        client.post(f"/api/v1/contagens/{c['id']}/finalizar", headers=auth_headers)

        r = client.post(f"/api/v1/contagens/{c['id']}/aprovar",
                        json={"baixar_nao_encontrados": False}, headers=admin)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "aprovada"
        assert r.json()["baixados"] == 0

        # O ativo continua ativo: ausência é indício, não prova.
        assert client.get(f"/api/v1/ativos/{a['id']}", headers=auth_headers).status_code == 200

    def test_aprovar_baixando_os_nao_encontrados(self, client, auth_headers, admin):
        a = _ativo(client, auth_headers, "AP-2")
        c = _contagem(client, auth_headers)
        client.post(f"/api/v1/contagens/{c['id']}/finalizar", headers=auth_headers)

        r = client.post(f"/api/v1/contagens/{c['id']}/aprovar",
                        json={"baixar_nao_encontrados": True}, headers=admin)
        assert r.status_code == 200, r.text
        assert r.json()["baixados"] >= 1

        # Soft delete: sai das listas, mas o registro permanece para auditoria.
        assert client.get(f"/api/v1/ativos/{a['id']}", headers=auth_headers).status_code == 404

    def test_aprovado_nao_aceita_nova_leitura(self, client, auth_headers, admin):
        c = _contagem(client, auth_headers)
        client.post(f"/api/v1/contagens/{c['id']}/finalizar", headers=auth_headers)
        client.post(f"/api/v1/contagens/{c['id']}/aprovar", json={}, headers=admin)

        assert _ler(client, auth_headers, c["id"], "X").status_code == 400

    def test_cancelar_preserva_as_leituras(self, client, auth_headers):
        _ativo(client, auth_headers, "CX-1")
        c = _contagem(client, auth_headers)
        _ler(client, auth_headers, c["id"], "CX-1")

        r = client.post(f"/api/v1/contagens/{c['id']}/cancelar", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["status"] == "cancelada"

        itens = client.get(f"/api/v1/contagens/{c['id']}/itens", headers=auth_headers).json()
        assert len(itens) == 1, "cancelar não apaga o que foi lido"


class TestIsolamento:
    def test_contagem_inexistente_da_404(self, client, auth_headers):
        assert client.get("/api/v1/contagens/999999", headers=auth_headers).status_code == 404

    def test_leitura_em_contagem_inexistente_da_404(self, client, auth_headers):
        assert _ler(client, auth_headers, 999999, "X").status_code == 404


class TestTamanhoDoEscopo:
    """A tela precisa saber quantos itens o escopo abrange."""

    def test_criar_informa_o_tamanho_do_escopo(self, client, auth_headers):
        _ativo(client, auth_headers, "ESC-N-1")
        _ativo(client, auth_headers, "ESC-N-2")

        c = _contagem(client, auth_headers, dominio="ti")
        assert c["esperados"] >= 2

    def test_escopo_vazio_informa_zero(self, client, auth_headers):
        # Nenhuma impressora cadastrada: o escopo de impressoras está vazio.
        c = _contagem(client, auth_headers, dominio="impressora")
        assert c["esperados"] == 0

    def test_detalhe_traz_o_tamanho(self, client, auth_headers):
        _ativo(client, auth_headers, "ESC-N-3")
        c = _contagem(client, auth_headers, dominio="ti")

        d = client.get(f"/api/v1/contagens/{c['id']}", headers=auth_headers).json()
        assert d["esperados"] >= 1
