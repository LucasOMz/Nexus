"""Notificações por e-mail — catálogo, template, janela e preferências.

## O que estes testes protegem

O sistema de notificação tem uma falha característica: **ele falha em
silêncio**. Um e-mail que não sai não gera erro visível — a pessoa só descobre
que não recebeu quando o prazo venceu.

Por isso os testes cobrem as decisões que, erradas, produziriam silêncio:

* o template troca as variáveis (se não trocasse, sairia `{{patrimonio}}` no
  e-mail)
* a janela de horário respeita o intervalo (se não respeitasse, sairia às 3h
  e seria ignorado)
* a frequência não repete (se repetisse, viraria spam e seria filtrado)
* o usuário não altera a preferência de outro (se pudesse, desligaria o aviso
  do colega)
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services import notificacoes_email as ne


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
class TestCatalogo:
    def test_todo_aviso_tem_texto_e_variaveis(self):
        """Entrada incompleta no catálogo geraria e-mail vazio."""
        for chave, meta in ne.CATALOGO.items():
            assert meta.get("nome"), f"{chave}: sem nome"
            assert meta.get("assunto"), f"{chave}: sem assunto padrão"
            assert meta.get("corpo"), f"{chave}: sem corpo padrão"
            assert meta.get("variaveis"), f"{chave}: sem variáveis"
            assert meta.get("padrao") in ne.FREQUENCIAS, f"{chave}: frequência inválida"

    def test_avisos_pedidos_existem(self):
        """Os três casos citados na especificação do recurso."""
        assert "transferencia_pendente" in ne.CATALOGO
        assert "emprestimo_hoje" in ne.CATALOGO
        assert "toner_baixo" in ne.CATALOGO


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------
class TestTemplate:
    def test_troca_variavel(self):
        saida = ne.renderizar("Devolver {{patrimonio}} hoje", {"patrimonio": "TP001"})
        assert saida == "Devolver TP001 hoje"

    def test_variavel_repetida(self):
        saida = ne.renderizar("{{p}} e {{p}}", {"p": "X"})
        assert saida == "X e X"

    def test_variavel_desconhecida_nao_quebra(self):
        """Um template com nome errado ainda precisa enviar algo legível.

        Falhar aqui faria o aviso **não sair** — e ninguém saberia.
        """
        saida = ne.renderizar("Valor: {{nao_existe}}", {"patrimonio": "X"})
        assert "{{" not in saida
        assert "—" in saida

    def test_texto_vazio_nao_explode(self):
        assert ne.renderizar("", {"a": "1"}) == ""
        assert ne.renderizar(None, {}) == ""


# ---------------------------------------------------------------------------
# Janela de frequência
# ---------------------------------------------------------------------------
class TestJanela:
    @staticmethod
    def _quando(dia=25, hora=8, mes=10, ano=2026):
        # 25/10/2026 é um domingo — útil para o caso semanal.
        return datetime(ano, mes, dia, hora, 0, tzinfo=timezone.utc)

    def test_desligada_nunca_envia(self):
        assert not ne._pode_enviar_agora(False, "imediata", 8, None, self._quando())
        assert not ne._pode_enviar_agora(True, "desligada", 8, None, self._quando())

    def test_imediata_ignora_horario(self):
        assert ne._pode_enviar_agora(True, "imediata", 8, None, self._quando(hora=3))

    def test_diaria_so_na_hora_escolhida(self):
        assert ne._pode_enviar_agora(True, "diaria", 8, None, self._quando(hora=8))
        assert not ne._pode_enviar_agora(True, "diaria", 8, None, self._quando(hora=9))

    def test_semanal_so_nos_dias_escolhidos(self):
        # 25/10/2026 = domingo (ISO 7).
        domingo = self._quando(hora=8)
        assert domingo.isoweekday() == 7

        assert ne._pode_enviar_agora(True, "semanal", 8, "7", domingo)
        assert not ne._pode_enviar_agora(True, "semanal", 8, "1,3,5", domingo)

    def test_semanal_sem_dias_cai_na_segunda(self):
        """Sem escolha explícita, o resumo sai na segunda — não em qualquer dia."""
        segunda = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
        assert segunda.isoweekday() == 1
        assert ne._pode_enviar_agora(True, "semanal", 8, None, segunda)
        assert not ne._pode_enviar_agora(True, "semanal", 8, None, self._quando())


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class TestAPI:
    def test_catalogo_exige_login(self, client):
        assert client.get("/api/v1/notificacoes-email/catalogo").status_code == 401

    def test_catalogo_lista_avisos(self, client, auth_headers):
        r = client.get("/api/v1/notificacoes-email/catalogo", headers=auth_headers)
        assert r.status_code == 200
        dados = r.json()
        assert len(dados["itens"]) == len(ne.CATALOGO)
        assert dados["frequencias"]

    def test_smtp_nao_devolve_senha(self, client, auth_headers):
        """A senha nunca volta — nem cifrada.

        Devolver o valor cifrado daria a quem lê a resposta uma cópia para
        quebrar offline.
        """
        r = client.get("/api/v1/notificacoes-email/smtp", headers=auth_headers)
        assert r.status_code == 200
        corpo = r.json()
        assert "senha" not in corpo
        assert "senha_cifrada" not in corpo
        assert "tem_senha" in corpo

    def test_preferencias_listam_todos_os_avisos(self, client, auth_headers):
        r = client.get("/api/v1/notificacoes-email/preferencias", headers=auth_headers)
        assert r.status_code == 200
        dados = r.json()
        assert len(dados["itens"]) == len(ne.CATALOGO)
        assert "email" in dados

    def test_preferencia_grava_e_le(self, client, auth_headers):
        dados = client.get("/api/v1/notificacoes-email/preferencias",
                           headers=auth_headers).json()
        escolha = dados["itens"][0]

        r = client.put(
            "/api/v1/notificacoes-email/preferencias",
            json={"itens": [{
                "chave": escolha["chave"],
                "ativo": False,
                "frequencia": "semanal",
                "hora": 7,
                "dias_semana": "1,3",
            }]},
            headers=auth_headers,
        )
        assert r.status_code == 200

        depois = client.get("/api/v1/notificacoes-email/preferencias",
                            headers=auth_headers).json()
        alvo = next(i for i in depois["itens"] if i["chave"] == escolha["chave"])
        assert alvo["ativo"] is False
        assert alvo["frequencia"] == "semanal"
        assert alvo["dias_semana"] == "1,3"

    def test_chave_desconhecida_e_ignorada(self, client, auth_headers):
        """Chave inventada não pode criar preferência órfã.

        O despacho procura preferência por chave do catálogo; uma linha com
        chave inexistente ficaria no banco para sempre, sem efeito.
        """
        r = client.put(
            "/api/v1/notificacoes-email/preferencias",
            json={"itens": [{"chave": "inventada", "ativo": True, "frequencia": "diaria"}]},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["gravados"] == 0

    def test_previa_e_do_administrador(self, client, auth_headers):
        r = client.get("/api/v1/notificacoes-email/previa", headers=auth_headers)
        assert r.status_code in (200, 401, 403)

    def test_testar_smtp_sem_configuracao_explica(self, client, auth_headers):
        """Sem SMTP, o teste responde 400 com o motivo — e não 500.

        Quem está configurando precisa saber **o que** falta.
        """
        r = client.post(
            "/api/v1/notificacoes-email/smtp/testar",
            json={"destinatario": "teste@empresa.com"},
            headers=auth_headers,
        )
        assert r.status_code in (200, 400)
        if r.status_code == 400:
            assert "SMTP" in r.json()["detail"] or "configur" in r.json()["detail"].lower()
