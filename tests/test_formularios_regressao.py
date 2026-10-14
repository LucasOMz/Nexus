"""Regressão: os formulários enviam o MESMO corpo no cadastro e na edição.

Dois problemas relatados em uso real, ambos cobertos aqui:

1. **Editar ativo sempre falhava.** O formulário reenvia `dominio` e `tipo_item`,
   que não existiam no `AtivoUpdate` (`extra="forbid"`). O usuário via
   "Inventário: campo não reconhecido · Tipo de item: campo não reconhecido" com
   o formulário todo preenchido.

2. **Fornecedor com e-mail em branco era recusado.** Formulário HTML manda `""`
   para campo vazio, e `""` não é e-mail válido — a mensagem aparecia como
   `[object Object]`.
"""
from __future__ import annotations

import pytest


# Corpo exatamente como o frontend (ativos.js) monta, no cadastro E na edição.
def corpo_ativo(patrimonio: str = "REG-0001", dominio: str = "ti") -> dict:
    return {
        "patrimonio": patrimonio, "numero_serie": f"NS-{patrimonio}",
        "modelo": "Latitude 5440",
        "marca": "Dell",
        "categoria_id": None,
        "localizacao_id": None,
        "departamento_id": None,
        "status": "estoque",
        "data_garantia": None,
        "valor": None,
        "observacoes": None,
        "foto_id": None,
        "dominio": dominio,
        "tipo_item": "ativo",
        "ti": {
            "hostname": "PC-REG", "mac_address": None, "ip": None, "so": None,
            "dominio_ad": None, "cpu": None, "ram_gb": None, "armazenamento_gb": None,
        },
    }


class TestEdicaoDeAtivo:
    def test_editar_ativo_com_o_corpo_do_cadastro(self, client, auth_headers):
        """O caso que quebrava: criar e depois salvar a edição."""
        criado = client.post("/api/v1/ativos", json=corpo_ativo(), headers=auth_headers)
        assert criado.status_code == 201, criado.text
        ativo_id = criado.json()["id"]

        edicao = corpo_ativo()
        edicao["modelo"] = "Latitude 5450"
        edicao["status"] = "em_uso"
        edicao["ti"]["hostname"] = "PC-REG-EDITADO"

        resp = client.put(f"/api/v1/ativos/{ativo_id}", json=edicao, headers=auth_headers)
        assert resp.status_code == 200, f"Edição falhou: {resp.status_code} {resp.text}"
        corpo = resp.json()
        assert corpo["modelo"] == "Latitude 5450"
        assert corpo["status"] == "em_uso"
        assert corpo["ti"]["hostname"] == "PC-REG-EDITADO"

    def test_editar_ativo_de_impressora(self, client, auth_headers):
        corpo = corpo_ativo("REG-IMP-1", dominio="impressora")
        corpo.pop("ti")
        corpo["impressora"] = {
            "ip": None, "hostname": None, "driver": None, "tipo_impressao": "termica",
            "colorida": False, "contador_paginas": 0, "conectividade": "rede",
        }
        criado = client.post("/api/v1/ativos", json=corpo, headers=auth_headers)
        assert criado.status_code == 201, criado.text
        ativo_id = criado.json()["id"]

        corpo["impressora"]["contador_paginas"] = 250
        resp = client.put(f"/api/v1/ativos/{ativo_id}", json=corpo, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["impressora"]["contador_paginas"] == 250

    def test_trocar_inventario_explica_o_motivo(self, client, auth_headers):
        """Mudar o inventário não é permitido — e a mensagem precisa dizer isso."""
        criado = client.post("/api/v1/ativos", json=corpo_ativo("REG-0002"), headers=auth_headers)
        ativo_id = criado.json()["id"]

        outro = corpo_ativo("REG-0002", dominio="impressora")
        outro.pop("ti")
        outro["impressora"] = {"tipo_impressao": "laser", "conectividade": "rede", "contador_paginas": 0}

        resp = client.put(f"/api/v1/ativos/{ativo_id}", json=outro, headers=auth_headers)
        assert resp.status_code == 400
        assert "não pode ser alterado" in resp.json()["detail"]

    def test_edicao_parcial_continua_funcionando(self, client, auth_headers):
        criado = client.post("/api/v1/ativos", json=corpo_ativo("REG-0003"), headers=auth_headers)
        ativo_id = criado.json()["id"]
        resp = client.put(f"/api/v1/ativos/{ativo_id}", json={"observacoes": "só isto"}, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["observacoes"] == "só isto"


class TestDatas:
    """Datas viram objetos `date` no Python. Ao ir para a coluna JSON da
    auditoria, quebravam a serialização no commit — dando 500 ao salvar a
    garantia (e qualquer outro campo de data)."""

    def test_cadastrar_ativo_com_data_de_garantia(self, client, auth_headers):
        corpo = corpo_ativo("REG-DATA-1")
        corpo["data_garantia"] = "2027-06-30"
        corpo["data_aquisicao"] = "2025-01-15"
        resp = client.post("/api/v1/ativos", json=corpo, headers=auth_headers)
        assert resp.status_code == 201, f"Falhou ao cadastrar com datas: {resp.status_code} {resp.text}"
        assert resp.json()["data_garantia"] == "2027-06-30"

    def test_editar_data_de_garantia(self, client, auth_headers):
        """O caso relatado: alterar a garantia de um ativo existente."""
        criado = client.post("/api/v1/ativos", json=corpo_ativo("REG-DATA-2"), headers=auth_headers)
        ativo_id = criado.json()["id"]

        corpo = corpo_ativo("REG-DATA-2")
        corpo["data_garantia"] = "2027-06-30"
        resp = client.put(f"/api/v1/ativos/{ativo_id}", json=corpo, headers=auth_headers)
        assert resp.status_code == 200, f"Erro ao salvar a garantia: {resp.status_code} {resp.text}"
        assert resp.json()["data_garantia"] == "2027-06-30"

    def test_editar_somente_a_data_de_garantia(self, client, auth_headers):
        """Edição parcial com data (só o campo da garantia)."""
        criado = client.post("/api/v1/ativos", json=corpo_ativo("REG-DATA-3"), headers=auth_headers)
        ativo_id = criado.json()["id"]
        resp = client.put(
            f"/api/v1/ativos/{ativo_id}", json={"data_garantia": "2028-12-31"}, headers=auth_headers
        )
        assert resp.status_code == 200, f"Erro: {resp.status_code} {resp.text}"
        assert resp.json()["data_garantia"] == "2028-12-31"

    def test_remover_data_de_garantia(self, client, auth_headers):
        corpo = corpo_ativo("REG-DATA-4")
        corpo["data_garantia"] = "2027-06-30"
        criado = client.post("/api/v1/ativos", json=corpo, headers=auth_headers)
        ativo_id = criado.json()["id"]

        corpo["data_garantia"] = None
        resp = client.put(f"/api/v1/ativos/{ativo_id}", json=corpo, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["data_garantia"] is None

    def test_manutencao_com_custo(self, client, auth_headers):
        """Decimal junto com datas no mesmo registro."""
        criado = client.post("/api/v1/ativos", json=corpo_ativo("REG-DATA-5"), headers=auth_headers)
        ativo_id = criado.json()["id"]
        resp = client.post(
            "/api/v1/manutencoes",
            json={"ativo_id": ativo_id, "descricao": "Troca de peça", "custo": 149.9, "tecnico": "João"},
            headers=auth_headers,
        )
        assert resp.status_code == 201, f"Erro em manutenção: {resp.status_code} {resp.text}"


class TestCamposVazios:
    """Formulários mandam "" — isso não pode virar erro de validação."""

    def test_fornecedor_com_email_vazio(self, client, auth_headers):
        resp = client.post(
            "/api/v1/fornecedores",
            json={"nome": "Fornecedor Sem Email", "cnpj": "", "contato": "", "telefone": "", "email": ""},
            headers=auth_headers,
        )
        assert resp.status_code == 201, f"Recusou e-mail vazio: {resp.status_code} {resp.text}"
        assert resp.json()["email"] in (None, "")

    def test_fornecedor_com_email_valido(self, client, auth_headers):
        resp = client.post(
            "/api/v1/fornecedores",
            json={"nome": "Fornecedor Com Email", "email": "contato@fornecedor.com.br"},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["email"] == "contato@fornecedor.com.br"

    def test_fornecedor_com_email_invalido_ainda_e_recusado(self, client, auth_headers):
        """A validação de e-mail precisa continuar valendo."""
        resp = client.post(
            "/api/v1/fornecedores",
            json={"nome": "Fornecedor Email Ruim", "email": "nao-e-email"},
            headers=auth_headers,
        )
        assert resp.status_code == 422
        # O erro precisa apontar o campo, não vir como objeto cru.
        assert resp.json()["detail"][0]["loc"][-1] == "email"

    @pytest.mark.parametrize(
        "rota,corpo",
        [
            ("/api/v1/departamentos", {"nome": "Depto Vazio", "sigla": ""}),
            ("/api/v1/localizacoes", {"nome": "Local Vazio", "descricao": ""}),
            ("/api/v1/categorias", {"nome": "Categoria Vazia", "dominio": "", "descricao": ""}),
        ],
    )
    def test_cadastros_com_campos_opcionais_vazios(self, client, auth_headers, rota, corpo):
        resp = client.post(rota, json=corpo, headers=auth_headers)
        assert resp.status_code == 201, f"{rota} recusou campos vazios: {resp.status_code} {resp.text}"
