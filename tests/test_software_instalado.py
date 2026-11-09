"""Agrupamento e drill-down do software instalado.

## O que estes testes travam

* A lista principal mostra **um item por programa**, nao um por versao.
* `Chrome 119` e `Chrome 120` na mesma maquina contam **1 maquina, 2 versoes**.
* Nome com caixa diferente conta como o mesmo programa.
* O detalhe separa as versoes e lista as maquinas de cada uma.

## Como o banco e acessado

Estes testes precisam **gravar** `SoftwareInstalado`, e nao existe rota para
isso (o agente e quem escreve). A sessao vem da **mesma sobrescrita de
dependencia que o `client` usa** — escrever num banco paralelo e consultar em
outro devolveria sempre vazio.
"""
from __future__ import annotations

from app.database import get_db
from app.main import app
from app.models import Ativo, Planta
from app.models.enums import Dominio, StatusAtivo, TipoItem
from app.services import software_agente


def _sessao():
    """Abre uma sessão no banco que o `client` está usando."""
    gerador = app.dependency_overrides[get_db]()
    return next(gerador)


def _maquina(db, serie: str, planta_id: int | None = None) -> Ativo:
    a = Ativo(
        planta_id=planta_id or 1,
        dominio=Dominio.TI,
        tipo_item=TipoItem.ATIVO,
        status=StatusAtivo.ESTOQUE,
        numero_serie=serie,
        patrimonio="PAT-" + serie,
    )
    db.add(a)
    db.commit()
    return a


class TestListaAgrupada:
    def test_um_item_por_programa(self, client, auth_headers):
        db = _sessao()
        a = _maquina(db, "A")
        b = _maquina(db, "B")

        software_agente.registrar_software(db, a.id, [
            {"nome": "Google Chrome", "versao": "119"},
            {"nome": "Google Chrome", "versao": "120"},
            {"nome": "7-Zip", "versao": "23"},
        ])
        software_agente.registrar_software(db, b.id, [
            {"nome": "Google Chrome", "versao": "120"},
        ])

        r = client.get("/api/v1/softwares/instalados", headers=auth_headers)
        assert r.status_code == 200, r.text
        itens = {x["nome"]: x for x in r.json()}

        assert len(itens) == 2, itens.keys()
        assert itens["Google Chrome"]["versoes"] == 2
        assert itens["Google Chrome"]["pcs"] == 2
        assert itens["7-Zip"]["versoes"] == 1
        db.close()

    def test_caixa_diferente_conta_como_um(self, client, auth_headers):
        db = _sessao()
        a = _maquina(db, "C")
        b = _maquina(db, "D")

        software_agente.registrar_software(db, a.id, [
            {"nome": "Google Chrome", "versao": "120"},
        ])
        software_agente.registrar_software(db, b.id, [
            {"nome": "google chrome", "versao": "120"},
        ])

        r = client.get("/api/v1/softwares/instalados", headers=auth_headers)
        itens = {x["nome"].lower(): x for x in r.json()}

        assert len(itens) == 1, itens.keys()
        assert itens["google chrome"]["pcs"] == 2
        db.close()

    def test_busca_filtra(self, client, auth_headers):
        db = _sessao()
        a = _maquina(db, "E")

        software_agente.registrar_software(db, a.id, [
            {"nome": "Google Chrome", "versao": "120"},
            {"nome": "7-Zip", "versao": "23"},
        ])

        r = client.get("/api/v1/softwares/instalados?busca=chrome", headers=auth_headers)
        assert [x["nome"] for x in r.json()] == ["Google Chrome"]
        db.close()


class TestDetalhe:
    def test_separa_versoes_e_lista_pcs(self, client, auth_headers):
        db = _sessao()
        a = _maquina(db, "F")
        b = _maquina(db, "G")
        c = _maquina(db, "H")

        software_agente.registrar_software(db, a.id, [
            {"nome": "Google Chrome", "versao": "119"},
        ])
        software_agente.registrar_software(db, b.id, [
            {"nome": "Google Chrome", "versao": "120"},
        ])
        software_agente.registrar_software(db, c.id, [
            {"nome": "Google Chrome", "versao": "120"},
        ])

        r = client.get("/api/v1/softwares/instalados/Google%20Chrome",
                       headers=auth_headers)
        assert r.status_code == 200, r.text
        corpo = r.json()

        versoes = {v["versao"]: v for v in corpo["versoes"]}
        assert set(versoes) == {"119", "120"}, versoes.keys()
        assert len(versoes["119"]["pcs"]) == 1
        assert len(versoes["120"]["pcs"]) == 2
        assert versoes["119"]["pcs"][0]["patrimonio"] == "PAT-F"
        db.close()

    def test_nome_inexistente_devolve_vazio(self, client, auth_headers):
        r = client.get("/api/v1/softwares/instalados/NaoExiste", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["versoes"] == []

    def test_maquina_de_outra_planta_nao_aparece(self, client, auth_headers):
        """Quem tem planta vê só a dele — o mesmo isolamento dos cadastros."""
        db = _sessao()
        db.add(Planta(nome="Outra", sigla="OUT", ativa=True))
        db.commit()

        minha = _maquina(db, "I", 1)
        outra = _maquina(db, "J", 2)

        software_agente.registrar_software(db, minha.id, [
            {"nome": "Chrome", "versao": "120"},
        ])
        software_agente.registrar_software(db, outra.id, [
            {"nome": "Chrome", "versao": "120"},
        ])

        r = client.get("/api/v1/softwares/instalados/Chrome",
                       headers={**auth_headers, "X-Planta-Id": "1"})
        assert r.status_code == 200, r.text
        assert len(r.json()["versoes"][0]["pcs"]) == 1
        db.close()
