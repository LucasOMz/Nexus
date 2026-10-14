"""Busca de ativo por HOSTNAME mostra o hostname no resultado.

## O que motivou

Quem digitava "NTAT" via o ativo `TP98000011212` com o subtítulo
"Latitude 3420 · Dell · TAT" — **sem nenhuma menção ao hostname**. O
resultado estava certo, mas nada indicava POR QUE ele apareceu. A pessoa
duvida do resultado e busca de novo.

O hostname vive na ficha técnica (`AtivoTI` ou `AtivoImpressora`), e não no
ativo. Aqui se garante que ele chegue ao `AtivoOut` como um campo único,
independente do domínio.
"""
from __future__ import annotations

from app.database import get_db
from app.main import app
from app.models.core import Ativo, Planta
from app.models.impressora import AtivoImpressora
from app.models.ti import AtivoTI


def _planta(db, sigla="TAT"):
    p = Planta(nome=f"Planta {sigla}", sigla=sigla)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _ativo_ti(db, planta_id, patrimonio, hostname, modelo="Latitude 3420", marca="Dell"):
    a = Ativo(
        dominio="ti", tipo_item="ativo", patrimonio=patrimonio, numero_serie=f"NS-{patrimonio}",
        modelo=modelo, marca=marca, planta_id=planta_id, status="estoque",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    db.add(AtivoTI(ativo_id=a.id, hostname=hostname))
    db.commit()
    return a


class TestBuscaPorHostname:
    def test_acha_pelo_hostname(self, client, auth_headers):
        db = next(app.dependency_overrides[get_db]())
        planta = _planta(db)
        _ativo_ti(db, planta.id, "TP98000011212", "NTAT")

        r = client.get("/api/v1/ativos?search=NTAT&size=20", headers=auth_headers)
        assert r.status_code == 200, r.text
        itens = r.json()["items"]
        assert len(itens) == 1, f"esperava 1, veio {len(itens)}: {itens}"

    def test_o_resultado_traz_o_hostname(self, client, auth_headers):
        """Este é o ponto: o hostname pesquisado precisa APARECER."""
        db = next(app.dependency_overrides[get_db]())
        planta = _planta(db)
        _ativo_ti(db, planta.id, "TP98000011212", "NTAT")

        r = client.get("/api/v1/ativos?search=NTAT&size=20", headers=auth_headers)
        item = r.json()["items"][0]
        assert item["hostname"] == "NTAT", f"hostname veio como {item.get('hostname')!r}"

    def test_busca_parcial_tambem_traz(self, client, auth_headers):
        """O técnico digita parte do nome: "NTA" deve achar "NTAT"."""
        db = next(app.dependency_overrides[get_db]())
        planta = _planta(db)
        _ativo_ti(db, planta.id, "TP98000011212", "NTAT")

        r = client.get("/api/v1/ativos?search=NTA&size=20", headers=auth_headers)
        itens = r.json()["items"]
        assert len(itens) == 1
        assert itens[0]["hostname"] == "NTAT"

    def test_sem_ficha_o_campo_e_nulo_e_nao_estoura(self, client, auth_headers):
        """Ativo ainda sem ficha técnica: a lista não pode quebrar."""
        db = next(app.dependency_overrides[get_db]())
        planta = _planta(db)
        a = Ativo(
            dominio="ti", tipo_item="ativo", patrimonio="SEM-FICHA", numero_serie="NS-SEM-FICHA",
            planta_id=planta.id, status="estoque",
        )
        db.add(a)
        db.commit()

        r = client.get("/api/v1/ativos?search=SEM-FICHA&size=20", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["items"][0]["hostname"] is None

    def test_hostname_vem_mesmo_com_espacos(self, client, auth_headers):
        """Cadastro com espaço sobrando não pode virar "  NTAT" na tela."""
        db = next(app.dependency_overrides[get_db]())
        planta = _planta(db)
        _ativo_ti(db, planta.id, "TP1", "  NTAT  ")

        r = client.get("/api/v1/ativos?search=NTAT&size=20", headers=auth_headers)
        assert r.json()["items"][0]["hostname"] == "NTAT"

    def test_impressora_tambem_tem_hostname(self, client, auth_headers):
        """O campo é único: vale para impressora, não só para TI."""
        db = next(app.dependency_overrides[get_db]())
        planta = _planta(db, "IMP")
        a = Ativo(
            dominio="impressora", tipo_item="ativo", patrimonio="IMP-001", numero_serie="NS-IMP-001",
            planta_id=planta.id, status="estoque",
        )
        db.add(a)
        db.commit()
        db.refresh(a)
        db.add(AtivoImpressora(ativo_id=a.id, hostname="RTAT0001"))
        db.commit()

        r = client.get("/api/v1/ativos?search=RTAT0001&size=20", headers=auth_headers)
        itens = r.json()["items"]
        assert len(itens) == 1
        assert itens[0]["hostname"] == "RTAT0001"
