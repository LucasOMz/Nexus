"""Testes da auditoria: o `diff` precisa ser SEMPRE serializável em JSON.

Contexto: a coluna `diff` é JSON e o SQLAlchemy serializa no `commit`, fora do
`try` do `audit()`. Um objeto `date` no diff derrubava o request com 500 — foi o
que aconteceu ao salvar a **data de garantia** de um ativo.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import uuid4

from app.models.enums import Dominio, StatusAtivo, TipoItem
from app.services.audit_service import json_safe


class Cor(Enum):
    VERMELHO = "vermelho"
    AZUL = "azul"


class TestJsonSafe:
    def test_valores_simples_passam_iguais(self):
        assert json_safe(None) is None
        assert json_safe("texto") == "texto"
        assert json_safe(42) == 42
        assert json_safe(3.14) == 3.14
        assert json_safe(True) is True

    def test_data_vira_iso(self):
        """O caso do bug: data de garantia."""
        assert json_safe(date(2027, 6, 30)) == "2027-06-30"

    def test_datetime_vira_iso(self):
        valor = datetime(2027, 6, 30, 14, 30, tzinfo=timezone.utc)
        assert json_safe(valor) == valor.isoformat()

    def test_decimal_vira_float(self):
        assert json_safe(Decimal("149.90")) == 149.9

    def test_enum_vira_valor(self):
        assert json_safe(Dominio.TI) == "ti"
        assert json_safe(StatusAtivo.EM_USO) == "em_uso"
        assert json_safe(TipoItem.CONSUMIVEL) == "consumivel"
        assert json_safe(Cor.AZUL) == "azul"

    def test_uuid_vira_string(self):
        valor = uuid4()
        assert json_safe(valor) == str(valor)

    def test_bytes_vira_texto(self):
        assert json_safe(b"abc") == "abc"
        assert json_safe("áçã".encode()) == "áçã"

    def test_dict_aninhado_e_listas(self):
        entrada = {
            "garantia": date(2027, 6, 30),
            "valor": Decimal("10.5"),
            "dominio": Dominio.IMPRESSORA,
            "itens": [date(2025, 1, 1), {"custo": Decimal("9.99"), "status": StatusAtivo.ESTOQUE}],
            "tupla": (1, date(2026, 1, 1)),
        }
        saida = json_safe(entrada)
        assert saida["garantia"] == "2027-06-30"
        assert saida["valor"] == 10.5
        assert saida["dominio"] == "impressora"
        assert saida["itens"][0] == "2025-01-01"
        assert saida["itens"][1]["custo"] == 9.99
        assert saida["itens"][1]["status"] == "estoque"
        assert saida["tupla"] == [1, "2026-01-01"]

    def test_chave_nao_texto_vira_texto(self):
        assert json_safe({1: "a", (2, 3): "b"}) == {"1": "a", "(2, 3)": "b"}

    def test_objeto_desconhecido_nao_quebra(self):
        class Estranho:
            def __str__(self) -> str:
                return "estranho"

        assert json_safe(Estranho()) == "estranho"

    def test_saida_sempre_serializavel(self):
        """A garantia que importa: nunca mais estoura no commit."""
        entrada = {
            "data_garantia": date(2027, 6, 30),
            "data_aquisicao": datetime(2025, 1, 15, 9, 0),
            "valor": Decimal("1234.56"),
            "dominio": Dominio.TI,
            "tipo_item": TipoItem.ATIVO,
            "status": StatusAtivo.ESTOQUE,
            "foto_id": None,
            "anexos": [b"bin", uuid4()],
        }
        texto = json.dumps(json_safe(entrada))  # não pode lançar
        assert "2027-06-30" in texto
        assert "1234.56" in texto
        assert '"ti"' in texto
