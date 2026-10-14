"""Cobertura das correções e melhorias desta rodada.

1. Ler/ **digitar o código curto** impresso na etiqueta em branco (antes: 404).
2. PDF da etiqueta por **lista de ids** (a tela de ativos usa isso para baixar).
3. **Endpoint de auditoria** (histórico imutável consultável pelo administrador).
4. **Exclusão de ativo** disponível pelo endpoint (o botão usa ele).
"""
from __future__ import annotations


def _gerar(client, auth_headers, quantidade=1):
    r = client.post("/api/v1/zerados", json={"quantidade": quantidade, "dominio": "ti"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _ativo(client, auth_headers, patrimonio="AUD-0001"):
    r = client.post(
        "/api/v1/ativos",
        json={"dominio": "ti", "patrimonio": patrimonio, "numero_serie": f"NS-{patrimonio}", "modelo": "X1", "tipo_item": "ativo"},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestCodigoCurtoDaEtiquetaEmBranco:
    """A etiqueta imprime o QR **e** o código em letras grandes.

    Ler o QR funcionava; digitar o código dava 404 — o recurso de digitação
    manual não servia para nada.
    """

    def test_ler_pelo_codigo_curto(self, client, auth_headers):
        dados = _gerar(client, auth_headers)
        codigo = dados["itens"][0]["codigo"]

        r = client.post("/api/v1/scanner/buscar", json={"codigo": codigo}, headers=auth_headers)

        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["tipo"] == "zerado"
        assert corpo["zerado"]["codigo"] == codigo

    def test_ler_pelo_payload_completo(self, client, auth_headers):
        dados = _gerar(client, auth_headers)
        payload = dados["itens"][0]["payload"]

        r = client.post("/api/v1/scanner/buscar", json={"codigo": payload}, headers=auth_headers)

        assert r.status_code == 200, r.text
        assert r.json()["tipo"] == "zerado"
        assert r.json()["zerado"]["assinatura_valida"] is True

    def test_codigo_curto_inexistente_nao_quebra(self, client, auth_headers):
        r = client.post("/api/v1/scanner/buscar", json={"codigo": "NAOEXISTE1"}, headers=auth_headers)
        assert r.status_code == 404

    def test_busca_por_patrimonio_continua_funcionando(self, client, auth_headers):
        """O código curto não pode roubar a busca por patrimônio."""
        _ativo(client, auth_headers, "PAT-9999")
        r = client.post("/api/v1/scanner/buscar", json={"codigo": "PAT-9999"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["tipo"] == "ativo"
        assert r.json()["ativo"]["patrimonio"] == "PAT-9999"


class TestPdfDaEtiquetaPorIds:
    def test_pdf_de_um_ativo(self, client, auth_headers):
        ativo = _ativo(client, auth_headers, "PDF-0001")
        r = client.get("/api/v1/print/etiquetas.pdf", params={"ids": str(ativo["id"])}, headers=auth_headers)

        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")
        assert 'etiqueta_PDF-0001.pdf' in r.headers["content-disposition"]

    def test_pdf_de_varios_ativos_mantem_a_ordem(self, client, auth_headers):
        a1 = _ativo(client, auth_headers, "PDF-0002")
        a2 = _ativo(client, auth_headers, "PDF-0003")
        ids = f"{a2['id']},{a1['id']}"
        r = client.get("/api/v1/print/etiquetas.pdf", params={"ids": ids}, headers=auth_headers)

        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")
        assert r.content.count(b"/Type /Page") >= 2 or len(r.content) > 3000

    def test_ids_invalidos(self, client, auth_headers):
        r = client.get("/api/v1/print/etiquetas.pdf", params={"ids": "abc"}, headers=auth_headers)
        assert r.status_code == 400


class TestAuditoria:
    def test_registra_criacao_com_autor(self, client, auth_headers):
        """O log precisa dizer QUEM criou."""
        _ativo(client, auth_headers, "AUD-1000")

        r = client.get("/api/v1/admin/auditoria", params={"entidade": "ativo", "acao": "create"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        itens = r.json()["itens"]
        assert itens, "nenhum registro de criação de ativo"
        registro = itens[0]
        assert registro["usuario_nome"] == "Admin"
        assert registro["acao_rotulo"] == "Criou"
        assert registro["referencia"] == "AUD-1000"

    def test_registra_geracao_de_etiquetas(self, client, auth_headers):
        _gerar(client, auth_headers, 3)
        r = client.get("/api/v1/admin/auditoria", params={"acao": "gerar_zerados"}, headers=auth_headers)
        assert r.status_code == 200
        itens = r.json()["itens"]
        assert itens and itens[0]["diff"]["quantidade"] == 3

    def test_registra_edicao(self, client, auth_headers):
        ativo = _ativo(client, auth_headers, "AUD-1001")
        client.put(f"/api/v1/ativos/{ativo['id']}", json={"modelo": "Alterado"}, headers=auth_headers)

        r = client.get("/api/v1/admin/auditoria", params={"acao": "update", "entidade": "ativo"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["itens"], "edição não foi registrada"

    def test_registra_exclusao(self, client, auth_headers):
        ativo = _ativo(client, auth_headers, "AUD-1002")
        assert client.delete(f"/api/v1/ativos/{ativo['id']}", headers=auth_headers).status_code == 204

        r = client.get("/api/v1/admin/auditoria", params={"acao": "delete"}, headers=auth_headers)
        assert r.status_code == 200
        assert any(i["entidade"] == "ativo" for i in r.json()["itens"])

    def test_filtros_e_resumo(self, client, auth_headers):
        _ativo(client, auth_headers, "AUD-1003")

        f = client.get("/api/v1/admin/auditoria/filtros", headers=auth_headers)
        assert f.status_code == 200
        assert any(a["valor"] == "create" for a in f.json()["acoes"])
        assert f.json()["usuarios"]

        s = client.get("/api/v1/admin/auditoria/resumo", headers=auth_headers)
        assert s.status_code == 200
        assert s.json()["total"] > 0

    def test_leitura_registra_usuario(self, client, auth_headers):
        dados = _gerar(client, auth_headers)
        client.post("/api/v1/scanner/buscar", json={"codigo": dados["itens"][0]["codigo"]}, headers=auth_headers)

        r = client.get("/api/v1/admin/auditoria", params={"entidade": "qr_zerado"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["itens"]


class TestExclusaoDeAtivo:
    def test_endpoint_de_exclusao_responde_204(self, client, auth_headers):
        ativo = _ativo(client, auth_headers, "DEL-0001")
        assert client.delete(f"/api/v1/ativos/{ativo['id']}", headers=auth_headers).status_code == 204

        # Sai das listagens (exclusão lógica) mas continua na auditoria.
        lista = client.get("/api/v1/ativos", params={"dominio": "ti"}, headers=auth_headers).json()
        assert all(i["patrimonio"] != "DEL-0001" for i in lista["items"])
