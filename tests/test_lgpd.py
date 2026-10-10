"""LGPD: retenção e expurgo.

O motor (`plataforma.RETENCAO`, `prazo_de`, `plano_de_expurgo`, `anonimizar`)
já existia e estava testado. O que faltava era aplicar sobre dados reais.

Duas coisas precisam estar certas:

1. **O expurgo não roda sem confirmação.** Apagar não tem volta.
2. **Anonimizar corta o vínculo com a pessoa.** Marcar um campo de texto e
   deixar o `usuario_id` intacto não anonimiza nada.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.main import app
from app.models.core import LogAuditoria, Movimentacao
from app.services import plataforma


def _db(client):
    return next(app.dependency_overrides[get_db]())


def _log(db, quando, **campos):
    log = LogAuditoria(
        usuario_id=campos.get("usuario_id", 1),
        acao=campos.get("acao", "create"), entidade="ativo",
        ip=campos.get("ip", "10.0.0.1"),
        created_at=quando,
    )
    db.add(log)
    db.commit()
    return log


class TestPolitica:
    def test_lista_a_politica(self, client, auth_headers):
        r = client.get("/api/v1/admin/lgpd/retencao", headers=auth_headers)
        assert r.status_code == 200, r.text
        tipos = {i["tipo"] for i in r.json()["itens"]}
        assert "auditoria" in tipos

    def test_cada_item_traz_o_motivo(self, client, auth_headers):
        """A política sem o porquê vira número que ninguém sabe defender."""
        r = client.get("/api/v1/admin/lgpd/retencao", headers=auth_headers)
        for item in r.json()["itens"]:
            assert item["motivo"], f"{item['tipo']} sem motivo"
            assert item["dias"] is not None

    def test_aponta_o_que_a_politica_preve_sem_tabela(self, client, auth_headers):
        """Aparecer com zero sugeriria 'nada vencido', quando o certo é
        'não se aplica'."""
        r = client.get("/api/v1/admin/lgpd/retencao", headers=auth_headers)
        assert "reportes" in r.json()["sem_tabela"]

    def test_nada_vencido_no_inicio(self, client, auth_headers):
        _db(client)
        r = client.get("/api/v1/admin/lgpd/retencao", headers=auth_headers)
        assert r.json()["total_vencido"] == 0
        assert "Nada passou" in r.json()["mensagem"]

    def test_conta_o_vencido(self, client, auth_headers):
        db = _db(client)
        # A política da auditoria é de 5 anos.
        _log(db, datetime.now(timezone.utc) - timedelta(days=2000))
        _log(db, datetime.now(timezone.utc) - timedelta(days=10))

        r = client.get("/api/v1/admin/lgpd/retencao", headers=auth_headers)
        item = [i for i in r.json()["itens"] if i["tipo"] == "auditoria"][0]
        assert item["total"] == 2
        assert item["vencidos"] == 1

    def test_exige_admin(self, client):
        assert client.get("/api/v1/admin/lgpd/retencao").status_code == 401

    def test_diz_qual_o_proximo_expurgo(self, client, auth_headers):
        _db(client)
        r = client.get("/api/v1/admin/lgpd/proximo", headers=auth_headers)
        assert r.status_code == 200
        assert "mensagem" in r.json()


class TestExpurgo:
    def test_exige_confirmacao(self, client, auth_headers):
        """Apagar não tem volta — um clique duplo não pode disparar isto."""
        r = client.post("/api/v1/admin/lgpd/expurgar", headers=auth_headers)
        assert r.status_code == 400
        assert "confirmo" in r.json()["detail"]

    def test_nao_apaga_o_que_esta_no_prazo(self, client, auth_headers):
        db = _db(client)
        _log(db, datetime.now(timezone.utc) - timedelta(days=10))

        r = client.post("/api/v1/admin/lgpd/expurgar?confirmo=true", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert db.query(LogAuditoria).count() == 1

    def test_anonimiza_o_que_passou_do_prazo(self, client, auth_headers):
        """A auditoria é anonimizada, não apagada: a linha que registra quem
        excluiu um ativo é prova, e apagá-la destruiria a prova."""
        db = _db(client)
        _log(db, datetime.now(timezone.utc) - timedelta(days=2000), usuario_id=7)

        r = client.post("/api/v1/admin/lgpd/expurgar?confirmo=true", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["anonimizados"] == 1
        # A linha continua existindo.
        assert db.query(LogAuditoria).count() == 1

    def test_o_vinculo_com_a_pessoa_sai(self, client, auth_headers):
        """O bug que este teste existe para pegar.

        `anonimizar` só marca `usuario_id_original = None`. Se o `usuario_id`
        ficasse, a trilha continuaria ligada à pessoa e a anonimização não
        teria acontecido.
        """
        db = _db(client)
        log = _log(db, datetime.now(timezone.utc) - timedelta(days=2000), usuario_id=7)

        client.post("/api/v1/admin/lgpd/expurgar?confirmo=true", headers=auth_headers)
        db.refresh(log)
        assert log.usuario_id is None, "o vínculo com a pessoa continua"
        assert log.ip == "[anonimizado]"

    def test_o_fato_sobrevive(self, client, auth_headers):
        """Anonimizar tira QUEM, não O QUÊ.

        É o que concilia LGPD com auditoria: sem isso, a escolha seria entre
        apagar a prova ou violar a lei.
        """
        db = _db(client)
        log = _log(db, datetime.now(timezone.utc) - timedelta(days=2000), acao="delete")

        client.post("/api/v1/admin/lgpd/expurgar?confirmo=true", headers=auth_headers)
        db.refresh(log)
        assert log.acao == "delete"
        assert log.entidade == "ativo"
        assert log.created_at is not None

    def test_o_limite_e_respeitado(self, client, auth_headers):
        """O expurgo roda em transação: apagar tudo de uma vez travaria o
        banco numa base grande."""
        db = _db(client)
        for _ in range(5):
            _log(db, datetime.now(timezone.utc) - timedelta(days=2000))

        r = client.post("/api/v1/admin/lgpd/expurgar?confirmo=true&limite=2",
                        headers=auth_headers)
        assert r.json()["anonimizados"] == 2

    def test_rodar_de_novo_pega_o_resto(self, client, auth_headers):
        db = _db(client)
        for _ in range(4):
            _log(db, datetime.now(timezone.utc) - timedelta(days=2000))

        client.post("/api/v1/admin/lgpd/expurgar?confirmo=true&limite=2", headers=auth_headers)
        client.post("/api/v1/admin/lgpd/expurgar?confirmo=true&limite=2", headers=auth_headers)
        assert db.query(LogAuditoria).filter(LogAuditoria.usuario_id.isnot(None)).count() == 0

    def test_exige_admin(self, client):
        r = client.post("/api/v1/admin/lgpd/expurgar?confirmo=true")
        assert r.status_code == 401


class TestPoliticaNaoApagaHistoricoPatrimonial:
    def test_movimentacao_nao_e_apagada(self, client, auth_headers):
        """`acao = manter`: o histórico patrimonial precisa sobreviver à
        auditoria, mesmo depois do prazo de guarda.

        O prazo é de guarda MÍNIMA, não de descarte — quem lê "3650 dias"
        pode entender o contrário.
        """
        assert plataforma.RETENCAO["movimentacoes"]["acao"] == "manter"

    def test_manutencao_nao_e_apagada(self, client, auth_headers):
        assert plataforma.RETENCAO["manutencoes"]["acao"] == "manter"

    def test_auditoria_e_anonimizada_nao_apagada(self):
        assert plataforma.RETENCAO["auditoria"]["acao"] == "anonimizar"

    def test_so_apagar_apaga(self, client, auth_headers):
        db = _db(client)
        antigo = datetime.now(timezone.utc) - timedelta(days=4000)
        db.add(Movimentacao(ativo_id=None, tipo="ajuste", created_at=antigo))
        db.commit()

        client.post("/api/v1/admin/lgpd/expurgar?confirmo=true", headers=auth_headers)
        # Continua lá, apesar de muito além do prazo.
        assert db.query(Movimentacao).count() == 1
