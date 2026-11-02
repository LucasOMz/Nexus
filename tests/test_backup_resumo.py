"""Resumo do backup — conta só o que está vivo.

## O bug

O resumo fazia `select count(*) from {tabela}` — **incluindo as linhas
excluídas**. Quem apagou 5 das 8 fotos via o backup dizer "8 fotos":

* o número certo para quem olha a tela é **3**
* e a impressão era de que o backup não capturou a exclusão

O dump **continua** trazendo as excluídas — restaurar devolve o estado exato,
inclusive as marcas. O errado era só o **número mostrado**.

## Por que o filtro é condicional

`deleted_at` não existe em todas as tabelas. Aplicar `where deleted_at is
null` em todas quebraria as que não têm a coluna — e o resumo voltaria vazio,
sem aviso. Daí o teste de tabela sem soft delete.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base
from app.models.core import Imagem, Usuario
from app.services import backup_service


def _banco_com_imagens(quantas: int, excluidas: int) -> Path:
    arquivo = Path(tempfile.mkdtemp()) / "resumo.db"
    engine = create_engine(f"sqlite:///{arquivo}", future=True)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()

    for i in range(quantas):
        db.add(Imagem(nome=f"f{i}.png", caminho=f"/x/f{i}.png"))
    db.commit()

    for img in db.query(Imagem).limit(excluidas).all():
        img.deleted_at = datetime.now(timezone.utc)
    db.commit()

    db.close()
    engine.dispose()
    return arquivo


class TestResumoDoBackup:
    def test_conta_apenas_as_vivas(self):
        """8 fotos, 5 excluídas → o resumo diz 3."""
        arquivo = _banco_com_imagens(8, 5)
        resumo = backup_service._resumo_sqlite(str(arquivo))
        assert resumo.get("imagens") == 3

    def test_sem_exclusao_conta_todas(self):
        arquivo = _banco_com_imagens(4, 0)
        resumo = backup_service._resumo_sqlite(str(arquivo))
        assert resumo.get("imagens") == 4

    def test_todas_excluidas_conta_zero(self):
        arquivo = _banco_com_imagens(3, 3)
        resumo = backup_service._resumo_sqlite(str(arquivo))
        assert resumo.get("imagens") == 0

    def test_tabela_sem_soft_delete_ainda_conta(self):
        """O filtro é condicional.

        `usuarios` e a maioria das tabelas têm `deleted_at`, mas nem todas do
        resumo têm. Aplicar o filtro à força devolveria zero — ou erro — nas
        outras.
        """
        arquivo = _banco_com_imagens(1, 0)
        engine = create_engine(f"sqlite:///{arquivo}", future=True)
        db = sessionmaker(bind=engine, future=True)()
        db.add(Usuario(nome="Fulano", email="f@x.com", senha_hash="x", papel="tecnico"))
        db.commit()
        db.close()
        engine.dispose()

        resumo = backup_service._resumo_sqlite(str(arquivo))
        assert resumo.get("usuarios") == 1, resumo
