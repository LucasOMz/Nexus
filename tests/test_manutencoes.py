"""Testes de manutenções e transições de status do ativo."""
from __future__ import annotations


def _criar_ativo(client, auth_headers, patrimonio="TI-M"):
    return client.post("/api/v1/ativos", json={"dominio": "ti", "patrimonio": patrimonio, "numero_serie": f"NS-{patrimonio}"}, headers=auth_headers).json()["id"]


def test_abrir_manutencao_muda_status(client, auth_headers):
    ativo_id = _criar_ativo(client, auth_headers)
    res = client.post("/api/v1/manutencoes", json={"ativo_id": ativo_id, "descricao": "Tela quebrada"}, headers=auth_headers)
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "aberta"
    ativo = client.get(f"/api/v1/ativos/{ativo_id}", headers=auth_headers).json()
    assert ativo["status"] == "manutencao"


def test_concluir_restaura_estoque(client, auth_headers):
    ativo_id = _criar_ativo(client, auth_headers)
    manut_id = client.post("/api/v1/manutencoes", json={"ativo_id": ativo_id}, headers=auth_headers).json()["id"]
    res = client.patch(f"/api/v1/manutencoes/{manut_id}", json={"status": "concluida", "comentario_conclusao": "Servico executado"}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "concluida"
    ativo = client.get(f"/api/v1/ativos/{ativo_id}", headers=auth_headers).json()
    assert ativo["status"] == "estoque"


class TestManutencaoPelaLeitura:
    """Abrir manutenção direto da tela de LEITURA.

    O ativo chega identificado pela leitura (QR ou patrimônio), então o
    formulário não pede para escolher o ativo — e a ordem precisa aparecer na
    guia Manutenções como qualquer outra.
    """

    def _ler(self, client, auth_headers, codigo):
        r = client.post("/api/v1/scanner/buscar", json={"codigo": codigo}, headers=auth_headers)
        assert r.status_code == 200, r.text
        return r.json()

    def test_abre_manutencao_a_partir_da_leitura(self, client, auth_headers):
        ativo_id = _criar_ativo(client, auth_headers, "LEIT-001")

        # 1) A leitura identifica o ativo.
        leitura = self._ler(client, auth_headers, "LEIT-001")
        assert leitura["tipo"] == "ativo"
        assert leitura["ativo"]["id"] == ativo_id

        # 2) Abre a manutenção com o ativo que veio da leitura.
        r = client.post(
            "/api/v1/manutencoes",
            json={"ativo_id": leitura["ativo"]["id"], "descricao": "Não liga", "tecnico": "Carlos"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        manut_id = r.json()["id"]

        # 3) Aparece na guia Manutenções.
        lista = client.get("/api/v1/manutencoes", headers=auth_headers).json()
        itens = lista["items"] if isinstance(lista, dict) else lista
        assert any(m["id"] == manut_id for m in itens), "a ordem não apareceu na lista"

        # 4) E o ativo fica em manutenção.
        ativo = client.get(f"/api/v1/ativos/{ativo_id}", headers=auth_headers).json()
        assert ativo["status"] == "manutencao"

    def test_manutencao_pela_leitura_registra_o_autor(self, client, auth_headers):
        _criar_ativo(client, auth_headers, "LEIT-002")
        leitura = self._ler(client, auth_headers, "LEIT-002")
        client.post(
            "/api/v1/manutencoes",
            json={"ativo_id": leitura["ativo"]["id"], "descricao": "Pela leitura"},
            headers=auth_headers,
        )
        logs = client.get(
            "/api/v1/admin/auditoria",
            params={"entidade": "manutencao", "acao": "create"},
            headers=auth_headers,
        ).json()["itens"]
        assert logs, "a abertura não foi registrada na auditoria"
        assert logs[0]["usuario_nome"] == "Admin"

    def test_leitura_por_patrimonio_serve_para_abrir(self, client, auth_headers):
        """Funciona também digitando o patrimônio, sem o QR."""
        _criar_ativo(client, auth_headers, "LEIT-003")
        leitura = self._ler(client, auth_headers, "LEIT-003")
        assert leitura["ativo"]["patrimonio"] == "LEIT-003"
        assert leitura["ativo"]["origem"] == "patrimonio"


class TestQuemConcluiuAManutencao:
    """Ao fechar a ordem, o sistema grava QUEM concluiu, pelo usuário logado.

    Não é digitado: vem da sessão. Assim a responsabilidade pela conclusão
    fica registrada mesmo que o campo "Técnico" esteja em branco ou seja de
    uma empresa terceirizada.
    """

    def _abrir(self, client, auth_headers, patrimonio):
        ativo_id = _criar_ativo(client, auth_headers, patrimonio)
        r = client.post(
            "/api/v1/manutencoes",
            json={"ativo_id": ativo_id, "descricao": "Preventiva"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        return r.json()

    def test_ordem_aberta_nao_tem_concluinte(self, client, auth_headers):
        m = self._abrir(client, auth_headers, "CONC-001")
        assert m["concluido_por_nome"] is None
        assert m["concluido_por_id"] is None

    def test_concluir_grava_o_usuario_logado(self, client, auth_headers):
        m = self._abrir(client, auth_headers, "CONC-002")

        r = client.patch(f"/api/v1/manutencoes/{m['id']}", json={"status": "concluida", "comentario_conclusao": "Servico executado"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["status"] == "concluida"
        assert corpo["concluido_por_id"] is not None
        assert corpo["concluido_por_nome"] == "Admin"

    def test_concluinte_aparece_na_listagem(self, client, auth_headers):
        m = self._abrir(client, auth_headers, "CONC-003")
        client.patch(f"/api/v1/manutencoes/{m['id']}", json={"status": "concluida", "comentario_conclusao": "Servico executado"}, headers=auth_headers)

        itens = client.get("/api/v1/manutencoes", params={"size": 200}, headers=auth_headers).json()["items"]
        alvo = next(i for i in itens if i["id"] == m["id"])
        assert alvo["concluido_por_nome"] == "Admin"

    def test_reabrir_limpa_o_concluinte(self, client, auth_headers):
        """Reabrir a ordem não pode manter um concluinte que não concluiu."""
        m = self._abrir(client, auth_headers, "CONC-004")
        client.patch(f"/api/v1/manutencoes/{m['id']}", json={"status": "concluida", "comentario_conclusao": "Servico executado"}, headers=auth_headers)

        r = client.patch(f"/api/v1/manutencoes/{m['id']}", json={"status": "em_andamento"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["concluido_por_nome"] is None
        assert r.json()["data_conclusao"] is None

    def test_usuario_diferente_registra_o_proprio_nome(self, client, auth_headers):
        """Cada pessoa que conclui fica registrada com o SEU nome."""
        m = self._abrir(client, auth_headers, "CONC-005")

        r = client.post(
            "/api/v1/usuarios",
            json={
                "nome": "Wagner", "email": "wagner@teste.com", "papel": "ti", "senha": "senha123",
                "permissoes": {"inventarios": ["ti"], "modulos": ["ativos", "manutencoes"], "pode_escrever": True},
            },
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        login = client.post("/api/v1/auth/login", data={"username": "wagner@teste.com", "password": "senha123"})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}

        r = client.patch(f"/api/v1/manutencoes/{m['id']}", json={"status": "concluida", "comentario_conclusao": "Servico executado"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["concluido_por_nome"] == "Wagner"

    def test_cancelar_tambem_registra(self, client, auth_headers):
        m = self._abrir(client, auth_headers, "CONC-006")
        r = client.patch(f"/api/v1/manutencoes/{m['id']}", json={"status": "cancelada"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["concluido_por_nome"] == "Admin"


class TestComentarioObrigatorioNaConclusao:
    """Não dá para concluir sem dizer o que foi feito.

    A regra vale no BACKEND, não só na tela: a janela pode ser contornada por
    uma chamada direta à API, e o comentário é o registro do serviço prestado.
    """

    def _abrir(self, client, auth_headers, patrimonio):
        ativo_id = _criar_ativo(client, auth_headers, patrimonio)
        r = client.post(
            "/api/v1/manutencoes",
            json={"ativo_id": ativo_id, "descricao": "Corretiva"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        return r.json()

    def test_concluir_sem_comentario_e_recusado(self, client, auth_headers):
        m = self._abrir(client, auth_headers, "COMT-001")

        r = client.patch(f"/api/v1/manutencoes/{m['id']}", json={"status": "concluida"}, headers=auth_headers)
        assert r.status_code == 400
        assert "comentário" in r.json()["detail"].lower()

        # E a ordem continua ABERTA — a recusa não deixa estado pela metade.
        atual = client.get(f"/api/v1/manutencoes/{m['id']}", headers=auth_headers).json()
        assert atual["status"] != "concluida"
        assert atual["concluido_por_nome"] is None

    def test_comentario_so_com_espacos_e_recusado(self, client, auth_headers):
        m = self._abrir(client, auth_headers, "COMT-002")
        r = client.patch(
            f"/api/v1/manutencoes/{m['id']}",
            json={"status": "concluida", "comentario_conclusao": "   "},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_comentario_vazio_e_recusado(self, client, auth_headers):
        m = self._abrir(client, auth_headers, "COMT-003")
        r = client.patch(
            f"/api/v1/manutencoes/{m['id']}",
            json={"status": "concluida", "comentario_conclusao": ""},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_concluir_com_comentario_guarda_o_texto(self, client, auth_headers):
        m = self._abrir(client, auth_headers, "COMT-004")
        texto = "Trocado o rolete de tração e feito teste de impressão."

        r = client.patch(
            f"/api/v1/manutencoes/{m['id']}",
            json={"status": "concluida", "comentario_conclusao": texto},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["comentario_conclusao"] == texto
        assert r.json()["concluido_por_nome"] == "Admin"

    def test_comentario_reaparece_na_listagem(self, client, auth_headers):
        m = self._abrir(client, auth_headers, "COMT-005")
        client.patch(
            f"/api/v1/manutencoes/{m['id']}",
            json={"status": "concluida", "comentario_conclusao": "Limpeza interna"},
            headers=auth_headers,
        )
        itens = client.get("/api/v1/manutencoes", params={"size": 200}, headers=auth_headers).json()["items"]
        alvo = next(i for i in itens if i["id"] == m["id"])
        assert alvo["comentario_conclusao"] == "Limpeza interna"

    def test_espacos_nas_bordas_sao_removidos(self, client, auth_headers):
        m = self._abrir(client, auth_headers, "COMT-006")
        r = client.patch(
            f"/api/v1/manutencoes/{m['id']}",
            json={"status": "concluida", "comentario_conclusao": "  Troca de fusor  "},
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["comentario_conclusao"] == "Troca de fusor"

    def test_reabrir_limpa_o_comentario(self, client, auth_headers):
        m = self._abrir(client, auth_headers, "COMT-007")
        client.patch(
            f"/api/v1/manutencoes/{m['id']}",
            json={"status": "concluida", "comentario_conclusao": "Resolvido"},
            headers=auth_headers,
        )
        r = client.patch(f"/api/v1/manutencoes/{m['id']}", json={"status": "em_andamento"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["comentario_conclusao"] is None

    def test_cancelar_nao_exige_comentario(self, client, auth_headers):
        """A exigência é para CONCLUIR; cancelar continua livre."""
        m = self._abrir(client, auth_headers, "COMT-008")
        r = client.patch(f"/api/v1/manutencoes/{m['id']}", json={"status": "cancelada"}, headers=auth_headers)
        assert r.status_code == 200, r.text
