"""Auditoria imutável ligada ao log real (o passo que faltava).

O motor (`auditoria_cadeia.py`) já existia e estava testado. O que faltava era
**gravar** o hash em cada entrada de `LogAuditoria` e oferecer a verificação.

Aqui se testa a ligação: que o `audit()` encadeia de verdade, que o endpoint
confere, e que a adulteração é detectada apontando a linha exata.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.database import get_db
from app.main import app
from app.models import Base
from app.models.core import Ativo, LogAuditoria, Usuario
from app.services import audit_service
from app.services import auditoria_cadeia as cadeia
from app.services.audit_service import audit


def _db(client):
    return next(app.dependency_overrides[get_db]())


def _gravar(db, quantas=3, **campos):
    for i in range(quantas):
        audit(db, None, campos.get("acao", "create"), "ativo",
              entidade_id=i, ip="10.0.0.1", diff={"i": i})
    db.commit()


class TestGravacao:
    def test_toda_entrada_nova_tem_hash(self, client):
        db = _db(client)
        _gravar(db, 3)
        logs = db.query(LogAuditoria).order_by(LogAuditoria.id).all()
        assert all(x.hash for x in logs), "entrada sem assinatura"

    def test_a_primeira_aponta_para_o_genesis(self, client):
        db = _db(client)
        _gravar(db, 1)
        primeira = db.query(LogAuditoria).order_by(LogAuditoria.id).first()
        assert primeira.hash_anterior == cadeia.GENESIS

    def test_cada_uma_aponta_para_a_anterior(self, client):
        """O encadeamento é o que torna a adulteração detectável."""
        db = _db(client)
        _gravar(db, 5)
        logs = db.query(LogAuditoria).order_by(LogAuditoria.id).all()
        for i in range(1, len(logs)):
            assert logs[i].hash_anterior == logs[i - 1].hash, f"quebrou em {i}"

    def test_hashes_sao_distintos(self, client):
        """Duas entradas iguais em conteúdo ainda diferem (id e ordem)."""
        db = _db(client)
        _gravar(db, 3)
        hashes = [x.hash for x in db.query(LogAuditoria).all()]
        assert len(set(hashes)) == len(hashes)

    def test_varias_auditorias_no_mesmo_request(self, client):
        """O `flush` existe por isto: sem ele, duas entradas encadeariam no
        mesmo hash anterior e a cadeia nasceria quebrada."""
        db = _db(client)
        _gravar(db, 4)
        logs = db.query(LogAuditoria).order_by(LogAuditoria.id).all()
        assert logs[1].hash_anterior == logs[0].hash
        assert logs[3].hash_anterior == logs[2].hash

    def test_savepoints_preservam_a_ordem_e_descartam_auditoria_revertida(self, client):
        with _db(client) as db:
            audit(db, None, "primeiro", "ativo")
            with db.begin_nested():
                audit(db, None, "segundo", "ativo")
            savepoint = db.begin_nested()
            audit(db, None, "revertido", "ativo")
            savepoint.rollback()
            audit(db, None, "terceiro", "ativo")
            assert db.query(LogAuditoria).count() == 0
            db.commit()
            assert list(db.scalars(select(LogAuditoria.acao).order_by(LogAuditoria.id))) == [
                "primeiro", "segundo", "terceiro",
            ]

    def test_rollback_descarta_auditorias_pendentes(self, client):
        with _db(client) as db:
            audit(db, None, "cancelado", "ativo")
            db.rollback()
            audit(db, None, "confirmado", "ativo")
            db.commit()
            assert list(db.scalars(select(LogAuditoria.acao))) == ["confirmado"]

    def test_falha_na_auditoria_bloqueia_operacao_e_gera_log(self, client, auth_headers, monkeypatch, caplog):
        def falhar(*_):
            raise ValueError("conteúdo sensível de teste")

        monkeypatch.setattr(audit_service, "calcular_hash", falhar)
        resposta = client.post("/api/v1/ativos", headers=auth_headers, json={
            "dominio": "ti", "patrimonio": "TESTE-AUDITORIA", "numero_serie": "SN-AUDITORIA",
        })
        assert resposta.status_code == 500
        assert "auditoria" in resposta.json()["detail"]
        assert "Falha na auditoria" in caplog.text
        assert "conteúdo sensível de teste" not in caplog.text
        with _db(client) as db:
            assert db.query(Ativo).filter_by(patrimonio="TESTE-AUDITORIA").count() == 0
            assert db.query(LogAuditoria).count() == 0

    def test_o_diff_entra_no_hash(self, client):
        """Alterar o diff (o que a pessoa fez) precisa ser detectado."""
        db = _db(client)
        _gravar(db, 1)
        antes = db.query(LogAuditoria).first().hash
        db.rollback()
        audit(db, None, "create", "ativo", entidade_id=99, diff={"outro": True})
        db.commit()
        depois = db.query(LogAuditoria).order_by(LogAuditoria.id.desc()).first().hash
        assert antes != depois


class TestEndpoointDeIntegridade:
    def _integridade(self, client, headers, **params):
        q = "&".join(f"{k}={v}" for k, v in params.items())
        r = client.get(f"/api/v1/admin/auditoria/integridade{('?' + q) if q else ''}",
                       headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    def test_cadeia_integra(self, client, auth_headers):
        db = _db(client)
        _gravar(db, 5)
        d = self._integridade(client, auth_headers)
        assert d["integra"] is True
        assert d["verificados"] == 5
        assert "íntegra" in d["mensagem"]

    def test_sem_entradas_nao_estoura(self, client, auth_headers):
        _db(client)
        d = self._integridade(client, auth_headers)
        assert d["integra"] is True
        assert d["total"] == 0

    def test_adulterar_o_conteudo_e_detectado(self, client, auth_headers):
        db = _db(client)
        _gravar(db, 5)
        logs = db.query(LogAuditoria).order_by(LogAuditoria.id).all()
        # Troca o que a pessoa fez, mantendo o hash antigo — é o ataque que
        # um log comum não pega.
        logs[2].acao = "read"
        db.commit()

        d = self._integridade(client, auth_headers)
        assert d["integra"] is False
        assert d["motivo"] == "conteudo alterado"
        assert d["indice"] == 2
        assert d["confirmados"] == 2, "as anteriores estavam íntegras"

    def test_a_resposta_diz_QUAL_entrada_rompeu(self, client, auth_headers):
        """Apontar onde é o que torna a verificação útil numa investigação."""
        db = _db(client)
        _gravar(db, 4)
        logs = db.query(LogAuditoria).order_by(LogAuditoria.id).all()
        logs[1].entidade = "usuario"
        db.commit()

        d = self._integridade(client, auth_headers)
        assert d["integra"] is False
        assert d["entrada"] is not None
        assert d["entrada"]["id"] == logs[1].id

    def test_remover_uma_linha_e_detectado(self, client, auth_headers):
        """Apagar a linha que incrimina é o ataque que a cadeia impede."""
        db = _db(client)
        _gravar(db, 5)
        logs = db.query(LogAuditoria).order_by(LogAuditoria.id).all()
        db.delete(logs[2])
        db.commit()

        d = self._integridade(client, auth_headers)
        assert d["integra"] is False
        assert d["motivo"] == "encadeamento quebrado"

    def test_conta_as_entradas_sem_assinatura(self, client, auth_headers):
        """A tela precisa dizer que a cobertura não é tudo.

        Instalação que já existia tem log gravado antes deste recurso; essas
        linhas não participam da cadeia, e esconder isso daria falsa
        sensação de cobertura total.
        """
        db = _db(client)
        _gravar(db, 3)
        # Simula uma entrada antiga: sem hash nenhum.
        db.add(LogAuditoria(usuario_id=None, acao="legado", entidade="ativo"))
        db.commit()

        d = self._integridade(client, auth_headers)
        assert d["integra"] is True
        assert d["sem_assinatura"] == 1
        assert d["total"] == 4

    def test_verificacao_parcial_pelo_limite(self, client, auth_headers):
        db = _db(client)
        _gravar(db, 10)
        d = self._integridade(client, auth_headers, limite=5)
        assert d["verificados"] == 5
        assert d["total"] == 10
        assert d["parcial"] is True
        assert d["sem_assinatura"] == 0

    def test_historico_apenas_legado_informa_quantidade_real(self, client, auth_headers):
        with _db(client) as db:
            db.add(LogAuditoria(acao="legado", entidade="ativo"))
            db.commit()
        d = self._integridade(client, auth_headers)
        assert d["total"] == d["sem_assinatura"] == 1
        assert d["verificados"] == 0

    def test_exige_admin(self, client):
        r = client.get("/api/v1/admin/auditoria/integridade")
        assert r.status_code == 401


def test_postgres_preserva_cadeia_entre_transacoes_simultaneas():
    url = os.getenv("NEXUS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Configure NEXUS_TEST_POSTGRES_URL para testar com PostgreSQL descartável.")
    schema = f"nexus_qa_{uuid4().hex}"
    servidor = create_engine(url)
    motor = create_engine(url, connect_args={"options": f"-c search_path={schema} -c timezone=America/Sao_Paulo"})
    encontro = Barrier(8, timeout=10)

    def gravar(numero):
        with Session(motor) as db:
            # Simula uma operação de negócio que alterou outra tabela antes do commit.
            db.add(Usuario(nome=f"Usuário {numero}", email=f"teste{numero}@local", senha_hash="teste"))
            db.flush()
            for ordem in range(2):
                audit(db, None, "create", "usuario", entidade_id=numero, diff={"ordem": ordem})
            encontro.wait()
            db.commit()

    try:
        with servidor.begin() as conexao:
            conexao.execute(CreateSchema(schema))
        Base.metadata.create_all(motor)
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(gravar, range(8)))
        with Session(motor) as db:
            logs = list(db.scalars(select(LogAuditoria).order_by(LogAuditoria.id)))
            assert len(logs) == 16
            registros = [
                {**cadeia.registro_do_log(row), "hash": row.hash, "hash_anterior": row.hash_anterior} for row in logs
            ]
            resultado = cadeia.verificar(registros)
            assert resultado["integra"] is True, resultado
            assert db.query(Usuario).count() == 8
    finally:
        motor.dispose()
        with servidor.begin() as conexao:
            conexao.execute(DropSchema(schema, if_exists=True, cascade=True))
        servidor.dispose()


class TestRegistroCanonico:
    """A forma canônica — se ela variar entre gravar e verificar, toda a
    cadeia pareceria adulterada."""

    def test_a_data_e_normalizada_para_utc(self):
        from datetime import datetime, timedelta, timezone

        com_fuso = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        sem_fuso = datetime(2025, 6, 15, 10, 30, 0)
        fuso_local = datetime(2025, 6, 15, 7, 30, 0, tzinfo=timezone(timedelta(hours=-3)))
        a = cadeia.registro(None, "x", "y", None, None, None, com_fuso)
        b = cadeia.registro(None, "x", "y", None, None, None, sem_fuso)
        assert a["created_at"] == b["created_at"]
        assert a["created_at"] == cadeia.registro(None, "x", "y", None, None, None, fuso_local)["created_at"]

    def test_os_segundos_bastam(self):
        from datetime import datetime

        a = cadeia.registro(None, "x", "y", None, None, None, datetime(2025, 1, 1, 10, 0, 0))
        b = cadeia.registro(None, "x", "y", None, None, None, datetime(2025, 1, 1, 10, 0, 0, 999999))
        assert a["created_at"] == b["created_at"]

    def test_o_id_faz_parte(self, client):
        """Duas entradas idênticas em conteúdo diferem pelo id — e sem ele
        a verificação acusaria alteração onde não houve."""
        db = _db(client)
        _gravar(db, 2)
        logs = db.query(LogAuditoria).order_by(LogAuditoria.id).all()
        assert cadeia.registro_do_log(logs[0])["id"] == logs[0].id
        assert logs[0].hash != logs[1].hash

    def test_registro_do_log_reconstroi_o_mesmo_dicionario(self, client):
        """É o que a verificação usa — precisa bater com o da gravação."""
        db = _db(client)
        _gravar(db, 1)
        log = db.query(LogAuditoria).first()
        r = cadeia.registro_do_log(log)
        assert cadeia.calcular_hash(r, log.hash_anterior) == log.hash
