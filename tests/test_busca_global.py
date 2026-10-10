"""Busca global (Ctrl+K): acha pelo hostname e MOSTRA o hostname.

## O que motivou

Na busca global dava para achar pelo número de série, mas **não pelo
hostname** — o serviço procurava patrimônio, série, modelo e marca, e o
hostname vive na ficha técnica (`AtivoTI` / `AtivoImpressora`), fora do
ativo.

E quando achasse, precisava aparecer: quem digita "NTAT" vê
`TP98000011212 / Latitude 3420 · Dell` e não entende por que aquilo veio.
"""
from __future__ import annotations

from app.database import get_db
from app.main import app
from app.models.core import Ativo, Planta
from app.models.impressora import AtivoImpressora
from app.models.ti import AtivoTI
from app.services import busca


def _db(client):
    return next(app.dependency_overrides[get_db]())


def _planta(db, sigla="TAT"):
    p = Planta(nome=f"Planta {sigla}", sigla=sigla)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _ti(db, planta_id, patrimonio, hostname, **campos):
    a = Ativo(
        dominio="ti", tipo_item="ativo", patrimonio=patrimonio,
        planta_id=planta_id, status="estoque",
        modelo=campos.get("modelo", "Latitude 3420"),
        marca=campos.get("marca", "Dell"),
        numero_serie=campos.get("numero_serie"),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    db.add(AtivoTI(ativo_id=a.id, hostname=hostname))
    db.commit()
    return a


def _impressora(db, planta_id, patrimonio, hostname):
    a = Ativo(
        dominio="impressora", tipo_item="ativo", patrimonio=patrimonio,
        planta_id=planta_id, status="estoque",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    db.add(AtivoImpressora(ativo_id=a.id, hostname=hostname))
    db.commit()
    return a


class TestBuscaPeloHostname:
    def test_acha_pelo_hostname(self, client, auth_headers):
        """Era o que não funcionava: só série e patrimônio achavam."""
        db = _db(client)
        _ti(db, _planta(db).id, "TP98000011212", "NTAT")

        r = client.get("/api/v1/busca?q=NTAT", headers=auth_headers)
        assert r.status_code == 200, r.text

        ativos = [g for g in r.json()["grupos"] if g["nome"] == "Ativos"]
        assert ativos, f"não achou pelo hostname: {r.json()}"
        assert len(ativos[0]["itens"]) == 1

    def test_acha_por_parte_do_hostname(self, client, auth_headers):
        db = _db(client)
        _ti(db, _planta(db).id, "TP1", "NTAT0001")

        r = client.get("/api/v1/busca?q=NTAT", headers=auth_headers)
        ativos = [g for g in r.json()["grupos"] if g["nome"] == "Ativos"]
        assert ativos and len(ativos[0]["itens"]) == 1

    def test_traz_o_hostname_no_detalhe(self, client, auth_headers):
        """O ponto do pedido: o hostname precisa APARECER no resultado."""
        db = _db(client)
        _ti(db, _planta(db).id, "TP98000011212", "NTAT")

        r = client.get("/api/v1/busca?q=NTAT", headers=auth_headers)
        item = [g for g in r.json()["grupos"] if g["nome"] == "Ativos"][0]["itens"][0]
        assert "NTAT" in item["detalhe"], f"detalhe veio: {item['detalhe']!r}"

    def test_hostname_vem_primeiro_quando_casou(self, client, auth_headers):
        """Ordem é informação: o que casou vem antes, para explicar o item."""
        db = _db(client)
        _ti(db, _planta(db).id, "TP98000011212", "NTAT")

        r = client.get("/api/v1/busca?q=NTAT", headers=auth_headers)
        item = [g for g in r.json()["grupos"] if g["nome"] == "Ativos"][0]["itens"][0]
        assert item["detalhe"].startswith("NTAT"), item["detalhe"]

    def test_busca_por_serie_continua_funcionando(self, client, auth_headers):
        """O que já funcionava não pode quebrar."""
        db = _db(client)
        _ti(db, _planta(db).id, "TP1", "NTAT", numero_serie="SN-99887766")

        r = client.get("/api/v1/busca?q=SN-99887766", headers=auth_headers)
        ativos = [g for g in r.json()["grupos"] if g["nome"] == "Ativos"]
        assert ativos and len(ativos[0]["itens"]) == 1

    def test_impressora_pelo_hostname(self, client, auth_headers):
        db = _db(client)
        _impressora(db, _planta(db, "IMP").id, "IMP-001", "RTAT0001")

        r = client.get("/api/v1/busca?q=RTAT0001", headers=auth_headers)
        ativos = [g for g in r.json()["grupos"] if g["nome"] == "Ativos"]
        assert ativos and len(ativos[0]["itens"]) == 1
        assert "RTAT0001" in ativos[0]["itens"][0]["detalhe"]

    def test_busca_por_ip(self, client, auth_headers):
        """Mesmo raciocínio do hostname — o IP identifica a máquina na rede."""
        db = _db(client)
        p = _planta(db)
        a = Ativo(dominio="ti", tipo_item="ativo", patrimonio="IP-1",
                  planta_id=p.id, status="estoque")
        db.add(a)
        db.commit()
        db.refresh(a)
        db.add(AtivoTI(ativo_id=a.id, hostname="NTAT", ip="10.20.30.40"))
        db.commit()

        r = client.get("/api/v1/busca?q=10.20.30.40", headers=auth_headers)
        ativos = [g for g in r.json()["grupos"] if g["nome"] == "Ativos"]
        assert ativos and len(ativos[0]["itens"]) == 1


class TestRegrasDaBuscaGlobal:
    def test_termo_curto_nao_busca(self, client, auth_headers):
        db = _db(client)
        _ti(db, _planta(db).id, "TP1", "NTAT")

        r = client.get("/api/v1/busca?q=n", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_nada_encontrado_nao_estoura(self, client, auth_headers):
        _db(client)
        r = client.get("/api/v1/busca?q=zzzznaoexiste", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["grupos"] == []

    def test_ativo_sem_ficha_nao_quebra(self, client, auth_headers):
        """Sem ficha técnica não há hostname — e a busca não pode cair."""
        db = _db(client)
        p = _planta(db)
        db.add(Ativo(dominio="ti", tipo_item="ativo", patrimonio="SOZINHO",
                     planta_id=p.id, status="estoque"))
        db.commit()

        r = client.get("/api/v1/busca?q=SOZINHO", headers=auth_headers)
        assert r.status_code == 200
        ativos = [g for g in r.json()["grupos"] if g["nome"] == "Ativos"]
        assert ativos and ativos[0]["itens"][0]["titulo"] == "SOZINHO"

    def test_respeita_a_planta_do_usuario(self, client, auth_headers):
        """Busca não pode furar o isolamento multi-tenant."""
        db = _db(client)
        _ti(db, _planta(db, "AAA").id, "DA-OUTRA", "HOST-OUTRA")

        r = client.get("/api/v1/busca?q=HOST-OUTRA", headers=auth_headers)
        assert r.status_code == 200


class TestDetalheDoAtivo:
    """A função pura, sem banco — o que decide a ordem do detalhe."""

    class _Fake:
        def __init__(self, hostname=None, modelo=None, numero_serie=None, marca=None):
            self.hostname = hostname
            self.modelo = modelo
            self.numero_serie = numero_serie
            self.marca = marca

    def test_hostname_primeiro_quando_casou(self):
        a = self._Fake(hostname="NTAT", modelo="Latitude", marca="Dell")
        assert busca._detalhe_do_ativo(a, "NTAT").startswith("NTAT")

    def test_hostname_no_fim_quando_nao_casou(self):
        a = self._Fake(hostname="NTAT", modelo="Latitude", marca="Dell")
        assert busca._detalhe_do_ativo(a, "Latitude").startswith("Latitude")

    def test_sem_hostname_nao_deixa_separador_sobrando(self):
        a = self._Fake(modelo="Latitude", marca="Dell")
        assert busca._detalhe_do_ativo(a, "Latitude") == "Latitude · Dell"

    def test_vazio_nao_estoura(self):
        assert busca._detalhe_do_ativo(self._Fake(), "x") == ""

    def test_casa_sem_diferenciar_maiuscula(self):
        a = self._Fake(hostname="NTAT", modelo="Latitude")
        assert busca._detalhe_do_ativo(a, "ntat").startswith("NTAT")
