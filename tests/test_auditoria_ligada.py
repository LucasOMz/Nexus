"""Auditoria imutável ligada ao log real (o passo que faltava).

O motor (`auditoria_cadeia.py`) já existia e estava testado. O que faltava era
**gravar** o hash em cada entrada de `LogAuditoria` e oferecer a verificação.

Aqui se testa a ligação: que o `audit()` encadeia de verdade, que o endpoint
confere, e que a adulteração é detectada apontando a linha exata.
"""
from __future__ import annotations

from app.database import get_db
from app.main import app
from app.models.core import LogAuditoria
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

    def test_exige_admin(self, client):
        r = client.get("/api/v1/admin/auditoria/integridade")
        assert r.status_code == 401


class TestRegistroCanonico:
    """A forma canônica — se ela variar entre gravar e verificar, toda a
    cadeia pareceria adulterada."""

    def test_a_data_ignora_fuso(self):
        """SQLite devolve a data sem fuso; o valor gravado tinha +00:00.

        Sem o `strftime`, o hash acusaria "conteúdo alterado" logo após
        gravar — em toda a cadeia.
        """
        from datetime import datetime, timezone

        com_fuso = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        sem_fuso = datetime(2025, 6, 15, 10, 30, 0)
        a = cadeia.registro(None, "x", "y", None, None, None, com_fuso)
        b = cadeia.registro(None, "x", "y", None, None, None, sem_fuso)
        assert a["created_at"] == b["created_at"]

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
