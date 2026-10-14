"""Excluir um ativo e recadastrar o mesmo patrimônio precisa funcionar.

## O bug relatado

    1. Excluir o ativo "TI-001"      → some da lista
    2. Cadastrar "TI-001" de novo    → 409
       "Já existe um registro com esse valor."

**A mensagem contradiz a tela.** O usuário acabou de ver que não há nada ali.

## De onde vinha

- A checagem da aplicação filtra `deleted_at IS NULL` — **estava certa**;
- A constraint `UNIQUE` do banco **não distingue** vivos de excluídos.

Ou seja: a aplicação dizia "pode", o banco dizia "não pode". E como o soft
delete nunca libera o valor, **o patrimônio ficava preso para sempre**.

## Por que não bastou remover o `unique` do modelo

Porque isso não muda os bancos que já existem — e no SQLite o índice
automático que implementa `UNIQUE` numa coluna **não pode ser removido**,
seria preciso recriar a tabela. A solução aqui libera o valor renomeando o
registro excluído, e funciona em banco já instalado.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def db_session(client):
    from app.database import get_db
    from app.main import app

    return next(app.dependency_overrides[get_db]())


class TestRecadastroAposExclusao:
    def _criar(self, client, auth_headers, patrimonio):
        return client.post("/api/v1/ativos", json={
            "dominio": "ti",
            "tipo_item": "ativo",
            "patrimonio": patrimonio, "numero_serie": f"NS-{patrimonio}",
            "modelo": "Latitude 3420",
            "marca": "Dell",
            "status": "estoque",
        }, headers=auth_headers)

    def test_excluir_e_recadastrar(self, client, auth_headers):
        """O caminho exato do relato."""
        r = self._criar(client, auth_headers, "RECAD-001")
        if r.status_code == 409:
            pytest.skip("patrimônio já usado por outro teste")
        assert r.status_code == 201, r.text
        ativo_id = r.json()["id"]

        d = client.delete(f"/api/v1/ativos/{ativo_id}", headers=auth_headers)
        assert d.status_code in (200, 204), d.text

        # O que falhava.
        r2 = self._criar(client, auth_headers, "RECAD-001")
        assert r2.status_code == 201, (
            f"não deu para recadastrar o mesmo patrimônio:\n{r2.text}"
        )
        assert r2.json()["id"] != ativo_id, "devolveu o registro antigo"

    def test_o_excluido_nao_bloqueia_mas_continua_existindo(self, client, auth_headers):
        """O registro excluído é preservado — só deixa de segurar o nome.

        Apagar de verdade perderia o histórico. O soft delete existe para
        isso, e a correção não pode custar esse histórico.
        """
        from app.database import get_db
        from app.main import app
        from app.models.core import Ativo

        r = self._criar(client, auth_headers, "RECAD-002")
        if r.status_code == 409:
            pytest.skip("patrimônio já usado")
        ativo_id = r.json()["id"]
        client.delete(f"/api/v1/ativos/{ativo_id}", headers=auth_headers)

        r2 = self._criar(client, auth_headers, "RECAD-002")
        assert r2.status_code == 201, r2.text

        db = next(app.dependency_overrides[get_db]())
        antigo = db.get(Ativo, ativo_id)
        assert antigo is not None, "o registro excluído foi apagado de verdade"
        assert antigo.deleted_at is not None
        # Renomeado, com o patrimônio original preservado no começo.
        assert antigo.patrimonio.startswith("RECAD-002")
        assert f"#{ativo_id}" in antigo.patrimonio

    def test_o_patrimonio_ainda_e_unico_entre_vivos(self, client, auth_headers):
        """A proteção de verdade não pode ter sido afrouxada.

        Dois ativos VIVOS com o mesmo patrimônio continuam sendo erro.
        """
        r = self._criar(client, auth_headers, "RECAD-003")
        if r.status_code == 409:
            pytest.skip("patrimônio já usado")
        assert r.status_code == 201

        r2 = self._criar(client, auth_headers, "RECAD-003")
        assert r2.status_code == 409, "aceitou dois ativos vivos com o mesmo patrimônio"

    def test_limite_da_coluna_e_respeitado(self, db_session):
        """O PostgreSQL RECUSA o que passa de `VARCHAR(80)`; o SQLite aceita.

        Sem encurtar, o problema só apareceria em produção — e com outra cara.
        """
        from datetime import datetime, timezone

        from app.models.core import Ativo
        from app.services import unicidade

        longo = "P" * 80
        antigo = Ativo(dominio="ti", tipo_item="ativo", patrimonio=longo, numero_serie=f"NS-{longo}",
                       status="estoque", deleted_at=datetime.now(timezone.utc))
        db_session.add(antigo)
        db_session.commit()

        n = unicidade.liberar(db_session, Ativo, "patrimonio", longo, limite=80)
        assert n == 1
        db_session.refresh(antigo)
        assert len(antigo.patrimonio) <= 80, (
            f"o novo valor tem {len(antigo.patrimonio)} caracteres — "
            "o PostgreSQL recusaria"
        )

    def test_sem_excluido_nao_mexe_em_nada(self, db_session):
        from app.models.core import Ativo
        from app.services import unicidade

        n = unicidade.liberar(db_session, Ativo, "patrimonio", "NAO-EXISTE", limite=80)
        assert n == 0
