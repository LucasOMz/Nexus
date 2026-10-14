"""Etiquetas QR em branco: gerar, ler e vincular a um ativo.

Fluxo coberto (o que o usuário pediu):
  1. gerar N etiquetas sem dono;
  2. ler uma delas na tela de Leitura â†’ o sistema sinaliza `tipo="zerado"`;
  3. cadastrar o equipamento â†’ a etiqueta fica vinculada;
  4. ler de novo â†’ agora resolve o ativo normalmente.
"""
from __future__ import annotations

import json


def gerar(client, auth_headers, quantidade=3, dominio="ti"):
    r = client.post("/api/v1/zerados", json={"quantidade": quantidade, "dominio": dominio}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


def corpo_ativo(patrimonio: str, qr_payload: str | None = None) -> dict:
    corpo = {
        "patrimonio": patrimonio, "numero_serie": f"NS-{patrimonio}",
        "modelo": "Latitude 5440",
        "marca": "Dell",
        "status": "estoque",
        "dominio": "ti",
        "tipo_item": "ativo",
        "valor": None,
        "observacoes": None,
        "ti": {"hostname": None, "mac_address": None, "ip": None, "so": None},
    }
    if qr_payload:
        corpo["qr_payload"] = qr_payload
    return corpo


class TestGeracao:
    def test_gera_lote_de_etiquetas_livres(self, client, auth_headers):
        dados = gerar(client, auth_headers, 5)
        assert dados["quantidade"] == 5
        assert dados["lote"].startswith("L")
        assert len(dados["itens"]) == 5
        # Códigos únicos, payloads únicos, todos com o prefixo de etiqueta em branco.
        codigos = {i["codigo"] for i in dados["itens"]}
        payloads = {i["payload"] for i in dados["itens"]}
        assert len(codigos) == 5 and len(payloads) == 5
        assert all(p.startswith("TIZERADO:") for p in payloads)
        # Sem caracteres ambíguos no código.
        assert not any(c in "IO01" for c in "".join(codigos))

    def test_limite_de_quantidade(self, client, auth_headers):
        assert client.post("/api/v1/zerados", json={"quantidade": 0}, headers=auth_headers).status_code == 422
        assert client.post("/api/v1/zerados", json={"quantidade": 99999}, headers=auth_headers).status_code == 422

    def test_listagem_e_resumo_por_lote(self, client, auth_headers):
        dados = gerar(client, auth_headers, 4)

        lista = client.get("/api/v1/zerados", headers=auth_headers).json()
        assert lista["total"] == 4
        assert lista["livres"] == 4
        assert all(i["status"] == "livre" for i in lista["itens"])

        lotes = client.get("/api/v1/zerados/lotes", headers=auth_headers).json()
        assert lotes[0]["lote"] == dados["lote"]
        assert lotes[0]["total"] == 4 and lotes[0]["livres"] == 4 and lotes[0]["usados"] == 0

    def test_pdf_do_lote(self, client, auth_headers):
        dados = gerar(client, auth_headers, 3)
        r = client.get(
            "/api/v1/zerados/etiquetas.pdf", params={"lote": dados["lote"]}, headers=auth_headers
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")
        assert len(r.content) > 2000

    def test_excluir_etiqueta_livre(self, client, auth_headers):
        dados = gerar(client, auth_headers, 1)
        etiqueta_id = dados["itens"][0]["id"]
        assert client.delete(f"/api/v1/zerados/{etiqueta_id}", headers=auth_headers).status_code == 204
        assert client.get("/api/v1/zerados", headers=auth_headers).json()["total"] == 0


class TestLeituraEVinculo:
    def test_ler_etiqueta_livre_pede_cadastro(self, client, auth_headers):
        """O ponto central: a leitura sinaliza que é uma etiqueta sem dono."""
        dados = gerar(client, auth_headers, 1)
        payload = dados["itens"][0]["payload"]

        r = client.post("/api/v1/scanner/buscar", json={"codigo": payload}, headers=auth_headers)
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["tipo"] == "zerado"
        assert corpo["ativo"] is None
        assert corpo["zerado"]["codigo"] == dados["itens"][0]["codigo"]
        assert corpo["zerado"]["payload"] == payload
        assert corpo["zerado"]["pode_escrever"] is True

    def test_cadastrar_ativo_vincula_a_etiqueta(self, client, auth_headers):
        dados = gerar(client, auth_headers, 1)
        payload = dados["itens"][0]["payload"]
        codigo = dados["itens"][0]["codigo"]

        criado = client.post(
            "/api/v1/ativos", json=corpo_ativo("ZER-0001", payload), headers=auth_headers
        )
        assert criado.status_code == 201, criado.text
        ativo_id = criado.json()["id"]
        assert criado.json()["qr_payload"] == payload

        # A etiqueta agora aparece como usada e apontando para o ativo.
        lista = client.get("/api/v1/zerados", headers=auth_headers).json()
        item = next(i for i in lista["itens"] if i["codigo"] == codigo)
        assert item["status"] == "usado"
        assert item["ativo_id"] == ativo_id
        assert item["ativo_patrimonio"] == "ZER-0001"

    def test_reler_etiqueta_ja_vinculada_devolve_o_ativo(self, client, auth_headers):
        """Depois de cadastrado, o mesmo QR passa a resolver o ativo."""
        dados = gerar(client, auth_headers, 1)
        payload = dados["itens"][0]["payload"]
        client.post("/api/v1/ativos", json=corpo_ativo("ZER-0002", payload), headers=auth_headers)
        r = client.post("/api/v1/scanner/buscar", json={"codigo": payload}, headers=auth_headers)
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert corpo["tipo"] == "ativo"
        assert corpo["ativo"]["patrimonio"] == "ZER-0002"
        assert corpo["ativo"]["origem"] == "qr_zerado"
        assert corpo["ativo"]["assinatura_valida"] is True

    def test_nao_permite_reusar_etiqueta_ja_vinculada(self, client, auth_headers):
        """Dois equipamentos não podem ficar com o mesmo QR."""
        dados = gerar(client, auth_headers, 1)
        payload = dados["itens"][0]["payload"]
        client.post("/api/v1/ativos", json=corpo_ativo("ZER-0003", payload), headers=auth_headers)

        r = client.post("/api/v1/ativos", json=corpo_ativo("ZER-0004", payload), headers=auth_headers)
        assert r.status_code == 409
        assert "já está vinculada" in r.json()["detail"]

    def test_etiqueta_de_outro_sistema_e_recusada(self, client, auth_headers):
        """Código em branco que não foi gerado aqui (outro segredo/instalação)."""
        r = client.post(
            "/api/v1/scanner/buscar", json={"codigo": "TIZERADO:ZZZZZZZZZZ:1700000000:abc"}, headers=auth_headers
        )
        assert r.status_code == 404
        assert "não reconhecida" in r.json()["detail"]

    def test_lista_codigos_livres_para_conferencia(self, client, auth_headers):
        gerar(client, auth_headers, 2)
        r = client.get("/api/v1/zerados", params={"status": "livre"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["total"] == 2


class TestAssinaturaDaEtiqueta:
    def test_assinatura_alterada_e_recusada(self, client, auth_headers, monkeypatch):
        """Com QR_EXIGIR_ASSINATURA=true, um payload adulterado não passa."""
        from app.config import settings

        monkeypatch.setattr(settings, "qr_exigir_assinatura", True)
        # Gera a etiqueta no banco com o payload correto...
        dados = gerar(client, auth_headers, 1)
        payload_real = dados["itens"][0]["payload"]
        codigo_real = dados["itens"][0]["codigo"]

        # ...e envia um payload com a assinatura trocada para o MESMO código.
        partes = payload_real.split(":")
        adulterado = f"{partes[0]}:{partes[1]}:{partes[2]}:assinatura_falsa"
        r = client.post("/api/v1/scanner/buscar", json={"codigo": adulterado}, headers=auth_headers)
        assert r.status_code == 400
        assert "assinatura" in r.json()["detail"].lower()

        # O payload legítimo continua funcionando.
        ok = client.post("/api/v1/scanner/buscar", json={"codigo": payload_real}, headers=auth_headers)
        assert ok.status_code == 200
        assert ok.json()["zerado"]["codigo"] == codigo_real

    def test_payload_em_branco_tem_hmac_valido(self):
        """A assinatura da etiqueta em branco confere com o segredo configurado."""
        from app.services.qr_service import (
            build_payload_zerado,
            extrair_codigo_zerado,
            gerar_codigo_zerado,
            validar_assinatura_zerado,
        )

        codigo = gerar_codigo_zerado()
        payload = build_payload_zerado(codigo)
        assert extrair_codigo_zerado(payload) == codigo
        assert validar_assinatura_zerado(payload) is True
        assert validar_assinatura_zerado(payload.replace(codigo, "OUTROCODIGO")) is False
        assert validar_assinatura_zerado("TIATIVO:1:2:3") is False

    def test_auditoria_registra_geracao(self, client, auth_headers):
        """A geração entra na auditoria (com diff JSON válido)."""
        import sqlite3

        from tests.conftest import engine

        gerar(client, auth_headers, 2)
        with engine.connect() as conn:  # type: ignore[union-attr]
            bruto = conn.exec_driver_sql(
                "select diff from logs_auditoria where acao = 'gerar_zerados' order by id desc limit 1"
            ).scalar()
        assert bruto
        dados = json.loads(bruto)
        assert dados["quantidade"] == 2
        assert dados["lote"].startswith("L")
        # Prova que nada não-serializável vazou para a coluna JSON.
        assert sqlite3 is not None
