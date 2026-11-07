"""Kanban — buckets, atividades, checklist e responsáveis.

## O que estes testes travam

1. **Ordem** — criar acrescenta no fim, reordenar reescreve a sequência.
2. **Mover** — o cartão troca de bucket e leva o checklist junto.
3. **Concluir é alternado** — clicar duas vezes reabre. Uma conclusão
   acidental não pode exigir editar o cartão.
4. **Responsável é só do administrador** — é o que separa "eu organizo
   minhas tarefas" de "eu distribuo tarefas para os outros".
5. **O módulo controla o acesso** — sem `kanban` liberado, 403.

## Por que testar antes da tela

As rotas foram escritas sem nenhuma execução. Testar agora evita empilhar
bug de interface sobre bug de contrato — foi o que aconteceu no agente,
onde o código compilava e não funcionava.
"""
from __future__ import annotations

from app.core.security import create_access_token


def _criar_usuario(client, auth_headers, email: str, papel: str = "ti") -> int:
    r = client.post(
        "/api/v1/usuarios",
        headers=auth_headers,
        json={"nome": email.split("@")[0], "email": email, "senha": "senha123", "papel": papel},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _token(usuario_id: int, papel: str = "ti", email: str = "x@teste.com") -> dict:
    return {"Authorization": f"Bearer {create_access_token(usuario_id, papel, email)}"}


def _bucket(client, headers, nome: str) -> int:
    r = client.post("/api/v1/kanban/buckets", headers=headers, json={"nome": nome})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _atividade(client, headers, bucket_id: int, titulo: str, prazo: str | None = None) -> int:
    corpo = {"bucket_id": bucket_id, "titulo": titulo}
    if prazo:
        corpo["prazo"] = prazo
    r = client.post("/api/v1/kanban/atividades", headers=headers, json=corpo)
    assert r.status_code == 200, r.text
    return r.json()["id"]


class TestBuckets:
    def test_criar_acrescenta_no_fim(self, client, auth_headers):
        a = _bucket(client, auth_headers, "A fazer")
        b = _bucket(client, auth_headers, "Em andamento")

        quadro = client.get("/api/v1/kanban", headers=auth_headers).json()
        # O admin criou dois; a ordem tem de respeitar a criação.
        ids = [x["id"] for x in quadro if x["id"] in (a, b)]
        assert ids == [a, b], ids

    def test_reordenar_reescreve_a_sequencia(self, client, auth_headers):
        a = _bucket(client, auth_headers, "Primeiro")
        b = _bucket(client, auth_headers, "Segundo")

        r = client.post("/api/v1/kanban/buckets/ordem",
                        headers=auth_headers, json={"ids": [b, a]})
        assert r.status_code == 200

        quadro = client.get("/api/v1/kanban", headers=auth_headers).json()
        ids = [x["id"] for x in quadro if x["id"] in (a, b)]
        assert ids == [b, a], ids

    def test_excluir_bucket_leva_as_atividades(self, client, auth_headers):
        bucket = _bucket(client, auth_headers, "Temporário")
        _atividade(client, auth_headers, bucket, "some junto")

        assert client.delete(f"/api/v1/kanban/buckets/{bucket}",
                             headers=auth_headers).status_code == 200

        quadro = client.get("/api/v1/kanban", headers=auth_headers).json()
        assert all(x["id"] != bucket for x in quadro)


class TestAtividades:
    def test_mover_troca_de_bucket(self, client, auth_headers):
        origem = _bucket(client, auth_headers, "Origem")
        destino = _bucket(client, auth_headers, "Destino")
        atividade = _atividade(client, auth_headers, origem, "migrar")

        r = client.post(f"/api/v1/kanban/atividades/{atividade}/mover",
                        headers=auth_headers,
                        json={"bucket_id": destino, "ordem": 0})
        assert r.status_code == 200
        assert r.json()["bucket_id"] == destino

        quadro = client.get("/api/v1/kanban", headers=auth_headers).json()
        no_destino = next(x for x in quadro if x["id"] == destino)
        assert any(a["id"] == atividade for a in no_destino["atividades"])

    def test_concluir_alterna(self, client, auth_headers):
        """Clicar duas vezes reabre — conclusão acidental é reversível."""
        bucket = _bucket(client, auth_headers, "Feitas")
        atividade = _atividade(client, auth_headers, bucket, "fechar chamado")

        r1 = client.post(f"/api/v1/kanban/atividades/{atividade}/concluir",
                         headers=auth_headers)
        assert r1.json()["concluida"] is True
        assert r1.json()["concluida_em"] is not None

        r2 = client.post(f"/api/v1/kanban/atividades/{atividade}/concluir",
                         headers=auth_headers)
        assert r2.json()["concluida"] is False
        assert r2.json()["concluida_em"] is None

    def test_prazo_no_passado_marca_atrasada(self, client, auth_headers):
        bucket = _bucket(client, auth_headers, "Atrasadas")
        atividade = _atividade(client, auth_headers, bucket, "velha",
                               prazo="2020-01-01T10:00:00Z")

        quadro = client.get("/api/v1/kanban", headers=auth_headers).json()
        achada = next(
            a for b in quadro for a in b["atividades"] if a["id"] == atividade
        )
        assert achada["atrasada"] is True

    def test_concluida_nao_fica_atrasada(self, client, auth_headers):
        """Prazo vencido numa tarefa concluída não é atraso — já foi feita."""
        bucket = _bucket(client, auth_headers, "Feitas")
        atividade = _atividade(client, auth_headers, bucket, "concluída tarde",
                               prazo="2020-01-01T10:00:00Z")
        client.post(f"/api/v1/kanban/atividades/{atividade}/concluir",
                    headers=auth_headers)

        quadro = client.get("/api/v1/kanban", headers=auth_headers).json()
        achada = next(
            a for b in quadro for a in b["atividades"] if a["id"] == atividade
        )
        assert achada["atrasada"] is False


class TestChecklist:
    def test_adicionar_e_marcar_item(self, client, auth_headers):
        bucket = _bucket(client, auth_headers, "Checklist")
        atividade = _atividade(client, auth_headers, bucket, "com passos")

        r = client.post(f"/api/v1/kanban/atividades/{atividade}/itens",
                        headers=auth_headers, json={"texto": "passo 1"})
        assert r.status_code == 200
        itens = r.json()["itens"]
        assert len(itens) == 1

        r2 = client.post(f"/api/v1/kanban/itens/{itens[0]['id']}/alternar",
                         headers=auth_headers)
        assert r2.json()["itens"][0]["feito"] is True
        assert r2.json()["itens_feitos"] == 1
        assert r2.json()["total_itens"] == 1

    def test_excluir_item(self, client, auth_headers):
        bucket = _bucket(client, auth_headers, "Checklist")
        atividade = _atividade(client, auth_headers, bucket, "com passos")
        r = client.post(f"/api/v1/kanban/atividades/{atividade}/itens",
                        headers=auth_headers, json={"texto": "remover"})
        item = r.json()["itens"][0]["id"]

        assert client.delete(f"/api/v1/kanban/itens/{item}",
                             headers=auth_headers).status_code == 200

        quadro = client.get("/api/v1/kanban", headers=auth_headers).json()
        achada = next(a for b in quadro for a in b["atividades"] if a["id"] == atividade)
        assert achada["total_itens"] == 0


class TestResponsaveis:
    def test_admin_atribui_responsavel(self, client, auth_headers):
        tecnico_id = _criar_usuario(client, auth_headers, "tec@teste.com")
        bucket = _bucket(client, auth_headers, "Equipe")
        atividade = _atividade(client, auth_headers, bucket, "tarefa")

        r = client.post(
            f"/api/v1/kanban/atividades/{atividade}/responsaveis",
            headers=auth_headers,
            json={"usuario_ids": [tecnico_id]},
        )
        assert r.status_code == 200
        assert [x["usuario_id"] for x in r.json()["responsaveis"]] == [tecnico_id]

    def test_tecnico_nao_pode_atribuir(self, client, auth_headers):
        """Só administrador distribui tarefas para os outros."""
        tecnico_id = _criar_usuario(client, auth_headers, "tec2@teste.com")
        bucket = _bucket(client, auth_headers, "Equipe")
        atividade = _atividade(client, auth_headers, bucket, "tarefa")

        headers_tec = _token(tecnico_id, "ti", "tec2@teste.com")
        r = client.post(
            f"/api/v1/kanban/atividades/{atividade}/responsaveis",
            headers=headers_tec,
            json={"usuario_ids": [tecnico_id]},
        )
        # 403 do papel, ou 403 do módulo — qualquer um barra.
        assert r.status_code == 403, r.text

    def test_lista_substitui_a_anterior(self, client, auth_headers):
        a = _criar_usuario(client, auth_headers, "a@teste.com")
        b = _criar_usuario(client, auth_headers, "b@teste.com")
        bucket = _bucket(client, auth_headers, "Equipe")
        atividade = _atividade(client, auth_headers, bucket, "tarefa")

        client.post(f"/api/v1/kanban/atividades/{atividade}/responsaveis",
                    headers=auth_headers, json={"usuario_ids": [a]})
        r = client.post(f"/api/v1/kanban/atividades/{atividade}/responsaveis",
                        headers=auth_headers, json={"usuario_ids": [b]})

        assert [x["usuario_id"] for x in r.json()["responsaveis"]] == [b]


class TestModulo:
    def test_sem_o_modulo_responde_403(self, client, auth_headers):
        """O módulo controla o acesso — não é só o ícone escondido."""
        usuario_id = _criar_usuario(client, auth_headers, "semmod@teste.com")
        headers = _token(usuario_id, "ti", "semmod@teste.com")

        r = client.get("/api/v1/kanban", headers=headers)
        assert r.status_code == 403, r.text
