"""Software na busca global — o nome sim, a chave NUNCA.

## O risco que este arquivo vigia

A chave de licença tem **um** caminho de saída no sistema:

    GET /licencas/{id}/revelar

Ele exige permissão própria (`licencas.ver_chave`) e grava auditoria a cada
chamada. Quem leu a chave é uma pergunta que precisa ter resposta.

**Indexar a chave na busca destruiria isso.** Bastaria digitar quatro
caracteres — de qualquer tela, sem permissão, e **sem deixar rastro**. O
gargalo único viraria um cano aberto.

Por isso há um teste que procura o valor da chave na resposta inteira.
"""
from __future__ import annotations

import pytest

from app.core import segredos

CHAVE = "ZZZZ-9999-YYYY-1234"


@pytest.fixture(autouse=True)
def _com_chave_mestra(monkeypatch):
    """Sem a chave mestra não há como cadastrar licença — e é o certo:
    o sistema não guarda a chave em claro só porque falta configuração."""
    monkeypatch.setenv(segredos.VARIAVEL, "chave-mestra-de-teste")
    yield


def _software(client, auth_headers, nome="Microsoft Office 2021",
              fabricante="Microsoft", padroes=None):
    corpo = {"nome": nome, "fabricante": fabricante}
    if padroes:
        corpo["padroes"] = padroes
    return client.post("/api/v1/softwares", json=corpo, headers=auth_headers).json()


def _licenca(client, auth_headers, software_id, chave=CHAVE, tipo="volume"):
    return client.post("/api/v1/licencas",
                       json={"software_id": software_id, "tipo": tipo,
                             "seats": 10, "chave": chave},
                       headers=auth_headers).json()


def _buscar(client, auth_headers, termo):
    r = client.get(f"/api/v1/busca?q={termo}", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r


def _itens(d: dict, grupo: str) -> list[dict]:
    """Os achados de um grupo.

    `grupos` é uma **lista** de `{"nome", "itens"}`, e não um dicionário — a
    ordem dos grupos é significativa na tela, e um dicionário não a garante
    em todas as versões de Python.
    """
    for g in d.get("grupos") or []:
        if g.get("nome") == grupo:
            return g.get("itens") or []
    return []


class TestAchaSoftware:
    def test_acha_pelo_nome(self, client, auth_headers):
        _software(client, auth_headers, "Microsoft Office 2021")
        d = _buscar(client, auth_headers, "office").json()
        assert _itens(d, "Software"), "o software não apareceu na busca"

    def test_acha_pelo_fabricante(self, client, auth_headers):
        _software(client, auth_headers, "Office", fabricante="Microsoft")
        d = _buscar(client, auth_headers, "microsoft").json()
        assert _itens(d, "Software"), "não achou pelo fabricante"

    def test_acha_por_parte_do_nome(self, client, auth_headers):
        """A busca é por trecho: ninguém digita o nome inteiro."""
        _software(client, auth_headers, "Adobe Acrobat Pro DC")
        d = _buscar(client, auth_headers, "acrob").json()
        assert _itens(d, "Software")

    def test_traz_o_fabricante_como_detalhe(self, client, auth_headers):
        _software(client, auth_headers, "AutoCAD 2024", fabricante="Autodesk")
        d = _buscar(client, auth_headers, "autocad").json()
        achado = _itens(d, "Software")[0]
        assert achado["titulo"] == "AutoCAD 2024"
        assert achado["detalhe"] == "Autodesk"

    def test_aponta_para_a_tela(self, client, auth_headers):
        _software(client, auth_headers, "7-Zip")
        d = _buscar(client, auth_headers, "7-zip").json()
        assert _itens(d, "Software")[0]["rota"] == "#/software"

    def test_termo_curto_nao_busca(self, client, auth_headers):
        """Uma letra traria o inventário inteiro."""
        _software(client, auth_headers, "Office")
        d = _buscar(client, auth_headers, "o").json()
        assert not _itens(d, "Software")


class TestAChaveNaoVaza:
    """O teste que justifica este arquivo."""

    def test_buscar_pela_chave_nao_devolve_nada(self, client, auth_headers):
        sw = _software(client, auth_headers, "Office")
        _licenca(client, auth_headers, sw["id"])

        # O termo é o próprio valor da chave.
        d = _buscar(client, auth_headers, "ZZZZ").json()

        # Nenhum achado. O `termo` ecoa de volta — é o que o usuário digitou,
        # e não um vazamento do sistema; por isso ele sai da comparação.
        assert d["grupos"] == []
        assert d["total"] == 0
        assert "1234" not in str(d["grupos"])

    def test_a_resposta_da_busca_nao_contem_a_chave(self, client, auth_headers):
        """Procura o valor na resposta INTEIRA, menos o eco do termo.

        Um vazamento pode vir de um campo inesperado — este teste não depende
        de saber de onde.
        """
        sw = _software(client, auth_headers, "Office")
        _licenca(client, auth_headers, sw["id"])

        for termo in ("office", "microsoft", "volume"):
            d = _buscar(client, auth_headers, termo).json()
            texto = str(d["grupos"])
            assert CHAVE not in texto, f"a chave vazou buscando por '{termo}'"
            assert "ZZZZ" not in texto
            assert "9999" not in texto

    def test_o_achado_nao_traz_campo_de_chave(self, client, auth_headers):
        sw = _software(client, auth_headers, "Office")
        _licenca(client, auth_headers, sw["id"])

        d = _buscar(client, auth_headers, "office").json()
        for achado in _itens(d, "Software"):
            campos = set(achado)
            assert not {c for c in campos if "chave" in c}, (
                f"campo de chave no resultado da busca: {campos}"
            )


class TestNaoQuebrouOBasico:
    def test_os_grupos_antigos_continuam(self, client, auth_headers):
        r = client.get("/api/v1/busca?q=teste", headers=auth_headers)
        assert r.status_code == 200
        d = r.json()
        assert "termo" in d
        assert isinstance(d.get("grupos"), list)

    def test_busca_vazia_nao_estoura(self, client, auth_headers):
        r = client.get("/api/v1/busca?q=", headers=auth_headers)
        assert r.status_code == 200
