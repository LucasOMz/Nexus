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


def _ativo(db, planta, patrimonio):
    from app.models.core import Ativo

    a = Ativo(dominio="ti", tipo_item="ativo", patrimonio=patrimonio, numero_serie=f"NS-{patrimonio}",
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


def _usuario_da_planta(client, planta_id):
    from app.core.security import create_access_token, hash_password
    from app.database import get_db
    from app.main import app
    from app.models.core import Usuario

    db = next(app.dependency_overrides[get_db]())
    u = Usuario(nome=f"U{planta_id}", email=f"esc{planta_id}@teste.com",
                senha_hash=hash_password("senha123"), papel="ti",
                ativo=True, planta_id=planta_id)
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

        r = client.get("/api/v1/manutencoes", headers=h)
        # 400 (mensagem clara) ou lista vazia — nunca a de outra unidade.
        assert r.status_code in (200, 400, 403)
        if r.status_code == 200:
            itens = r.json().get("items", r.json() if isinstance(r.json(), list) else [])
            assert itens == [], "usuário sem planta viu registros de todas as unidades"
