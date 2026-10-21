"""Busca no histórico de empréstimos.

## O que o recurso responde

*"O que a Ana já levou?"* e *"por quais mãos passou este notebook?"* — as duas
perguntas de quem audita empréstimo. A listagem só filtrava por situação, e o
`ativo_id` existia na API mas a tela nunca o enviava.

## O bug que este arquivo teria pego

A primeira versão procurava o número do chamado em `Emprestimo`:

    Emprestimo.numero_chamado.ilike(like)

**Esse campo mora no `Ativo`**, não no empréstimo — é o chamado de manutenção
do equipamento. Qualquer busca levantava `AttributeError` e o servidor
respondia **500**, com a mensagem genérica de "erro interno".

E não era só o termo específico: **a busca inteira quebrava**, porque a coluna
inexistente era avaliada na montagem da consulta, antes de qualquer filtro.

`ruff` não pega isso — `Emprestimo.numero_chamado` é acesso de atributo, não
nome indefinido. Só o teste pega.
"""
from __future__ import annotations

import pytest

from app.models.core import Ativo
from app.models.emprestimo import Emprestimo


class TestBuscaNaoQuebra:
    def test_o_campo_chamado_vive_no_ativo(self):
        """A premissa do bug: `numero_chamado` é do ativo, não do empréstimo.

        Se alguém mover o campo — ou criar um homônimo no empréstimo — este
        teste avisa antes de a busca voltar a quebrar.
        """
        colunas_emprestimo = {c.name for c in Emprestimo.__table__.columns}
        colunas_ativo = {c.name for c in Ativo.__table__.columns}

        assert "numero_chamado" in colunas_ativo, (
            "o número do chamado deixou de existir no Ativo — a busca por "
            "chamado precisa ser reescrita"
        )
        # Não é uma exigência de que NUNCA exista no empréstimo; é o registro
        # de onde ele está hoje.
        assert "numero_chamado" not in colunas_emprestimo

    @pytest.mark.parametrize("termo", ["", "teste", "a", "TI", "ana", "123", "%", "_"])
    def test_busca_responde_200(self, client, auth_headers, termo):
        """Nenhum termo pode derrubar a listagem.

        `%` e `_` são curingas do `LIKE` — digitá-los não pode virar erro.
        """
        r = client.get("/api/v1/emprestimos", params={"search": termo},
                       headers=auth_headers)
        assert r.status_code == 200, r.text
        assert "items" in r.json()

    def test_sem_search_continua_funcionando(self, client, auth_headers):
        r = client.get("/api/v1/emprestimos", headers=auth_headers)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_busca_vazia_e_igual_a_sem_busca(self, client, auth_headers):
        """`search=""` não pode filtrar nada — é o que a tela envia ao limpar."""
        a = client.get("/api/v1/emprestimos", headers=auth_headers).json()
        b = client.get("/api/v1/emprestimos", params={"search": ""},
                       headers=auth_headers).json()
        assert a["total"] == b["total"]


class TestFiltrosCombinam:
    def test_usuario_id_aceito(self, client, auth_headers):
        r = client.get("/api/v1/emprestimos", params={"usuario_id": 1},
                       headers=auth_headers)
        assert r.status_code == 200

    def test_situacao_e_search_juntos(self, client, auth_headers):
        r = client.get("/api/v1/emprestimos",
                       params={"situacao": "retirado", "search": "a"},
                       headers=auth_headers)
        assert r.status_code == 200
        # Todos os devolvidos têm de estar na situação pedida.
        for item in r.json()["items"]:
            assert item["situacao"] == "retirado"

    def test_paginacao_nao_infla_com_a_busca(self, client, auth_headers):
        """A subconsulta existe para a contagem de páginas sair certa.

        Com `join`, um empréstimo poderia aparecer mais de uma vez e o `total`
        mentiria.
        """
        r = client.get("/api/v1/emprestimos",
                       params={"search": "a", "size": 200}, headers=auth_headers)
        assert r.status_code == 200
        dados = r.json()
        ids = [i["id"] for i in dados["items"]]
        assert len(ids) == len(set(ids)), "o mesmo empréstimo apareceu duas vezes"
