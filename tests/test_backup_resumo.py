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

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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


def test_pasta_sem_gravacao_mostra_o_historico_e_bloqueia_novo_backup(client, auth_headers, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "backup_dir", str(tmp_path))
    nome = "backup_exemplo.dump"
    (tmp_path / nome).write_bytes(b"backup existente")
    (tmp_path / "backup_exemplo.json").write_text(
        json.dumps({"arquivo": nome, "criado_em": "2026-01-01T00:00:00+00:00"}), encoding="utf-8",
    )

    def negar_gravacao(**_):
        raise PermissionError("Acesso negado no teste.")

    monkeypatch.setattr(backup_service, "tempfile", SimpleNamespace(TemporaryFile=negar_gravacao))
    resposta = client.get("/api/v1/admin/backups", headers=auth_headers)
    assert resposta.status_code == 200, resposta.text
    painel = resposta.json()
    assert painel["status"]["gravavel"] is False
    assert painel["status"]["ok"] is False
    assert "NEXUS_BACKUP_DIR" in painel["status"]["mensagem"]
    assert [b["arquivo"] for b in painel["itens"]] == [nome]

    resposta = client.post("/api/v1/admin/backups", headers=auth_headers, json={"motivo": "manual"})
    assert resposta.status_code == 500
    assert "NEXUS_BACKUP_DIR" in resposta.json()["detail"]
    assert (tmp_path / nome).read_bytes() == b"backup existente"


def test_restauracao_sqlite_remove_sessoes_da_copia(tmp_path, monkeypatch):
    from datetime import timedelta

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    from app import database
    from app.config import settings
    from app.models import Base, SessaoUsuario, Usuario
    from app.services import sessoes

    arquivo = tmp_path / "backup.db"
    destino = tmp_path / "destino.db"
    origem = create_engine(f"sqlite:///{arquivo}")
    motor = create_engine(f"sqlite:///{destino}")
    monkeypatch.setattr(database, "engine", motor)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=motor))
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{destino}")
    monkeypatch.setattr(backup_service, "criar_backup", lambda motivo: {"motivo": motivo})
    monkeypatch.setattr(backup_service, "validar_backup", lambda nome: {"ok": True})
    monkeypatch.setattr(backup_service, "_resolver", lambda nome: (arquivo, {}))
    try:
        Base.metadata.create_all(origem)
        with Session(origem) as db:
            usuario = Usuario(nome="Operador restaurado", email="restaurado@teste.com", senha_hash="teste")
            db.add(usuario)
            db.flush()
            sessoes.registrar(db, "sessao-antiga", usuario.id, timedelta(minutes=5), "refresh-antigo")
            db.commit()
        origem.dispose()

        assert backup_service.restaurar_backup(arquivo.name)["ok"]
        with database.SessionLocal() as db:
            assert db.query(Usuario).one().email == "restaurado@teste.com"
            assert db.query(SessaoUsuario).count() == 0
        with Session(origem) as db:
            assert db.query(SessaoUsuario).count() == 1
    finally:
        database.engine.dispose()
        origem.dispose()
