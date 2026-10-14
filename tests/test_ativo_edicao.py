"""A edição do ativo aceita tudo o que o formulário envia.

## O bug que este arquivo impede

`AtivoUpdate` herda de `SemVazios`, e **não** de `AtivoBase` — diferente de
`AtivoCreate` e `AtivoOut`. Quando a locação acrescentou `forma_aquisicao`,
`contrato_id` e `valor_residual` em `AtivoBase`, os campos entraram na
criação e no retorno, **mas não na edição**.

O formulário os envia sempre. Com `extra="forbid"`, salvar qualquer ativo
era recusado:

    422 — forma_aquisicao: campo não reconhecido
          valor_residual:  campo não reconhecido

E a mensagem ainda mandava *"repasse ao suporte"* — o pior desfecho para um
problema interno e determinístico.

## Por que passou despercebido

Os testes de ativo exercitavam **criar** e **ler**. A edição era testada com
um corpo mínimo, sem os campos que o formulário real envia — então a
divergência entre o que o frontend manda e o que o schema aceita não
aparecia.

Por isso o teste abaixo envia o **corpo completo**, como a tela manda.
"""
from __future__ import annotations

import pytest

# O que o formulário do frontend envia ao salvar um ativo — incluindo os
# campos que o usuário nem toca, mas que o sistema preenche.
CORPO_DO_FORMULARIO = {
    "patrimonio": "TESTE-001", "numero_serie": "NS-TESTE-001",
    "modelo": "Latitude 3420",
    "marca": "Dell",
    "status": "estoque",
    "forma_aquisicao": "comprado",
    "contrato_id": None,
    "valor_residual": None,
    "observacoes": "criado no teste",
}


class TestSchemaAceitaOFormulario:
    def test_ativo_update_aceita_os_campos_de_locacao(self):
        """A garantia estrutural: o schema de edição conhece os campos."""
        from app.schemas.ativos import AtivoUpdate

        campos = set(AtivoUpdate.model_fields)
        for nome in ("forma_aquisicao", "contrato_id", "valor_residual"):
            assert nome in campos, (
                f"`{nome}` não está em `AtivoUpdate` — o formulário envia este "
                "campo e a edição será recusada com 422"
            )

    def test_o_corpo_do_formulario_valida(self):
        from app.schemas.ativos import AtivoUpdate

        # Não levanta: é o que a tela manda.
        AtivoUpdate(**CORPO_DO_FORMULARIO)

    def test_o_create_e_o_update_aceitam_os_mesmos_campos(self):
        """Divergência entre eles é o bug — e voltaria silenciosamente.

        `AtivoCreate` herda de `AtivoBase`; `AtivoUpdate` herda de
        `SemVazios`. Essa diferença é legítima (na edição quase tudo é
        opcional), mas os campos precisam ser os mesmos.
        """
        from app.schemas.ativos import AtivoCreate, AtivoUpdate

        importantes = {
            "forma_aquisicao", "contrato_id", "valor_residual",
            "patrimonio", "modelo", "marca", "status", "foto_id",
        }
        faltando_no_update = importantes - set(AtivoUpdate.model_fields)
        assert not faltando_no_update, (
            f"campos que a criação aceita e a edição não: {faltando_no_update}"
        )
        faltando_no_create = importantes - set(AtivoCreate.model_fields)
        assert not faltando_no_create, f"faltam na criação: {faltando_no_create}"


class TestEdicaoPelaAPI:
    def test_editar_com_o_corpo_do_formulario(self, client, auth_headers):
        """O caminho completo, como a tela faz."""
        ativos = client.get("/api/v1/ativos?size=1", headers=auth_headers).json()
        itens = ativos.get("items", [])
        if not itens:
            pytest.skip("sem ativos no banco de teste")

        alvo = itens[0]
        corpo = {**CORPO_DO_FORMULARIO, "numero_serie": f"NS-{alvo['patrimonio']}", "patrimonio": alvo["patrimonio"]}

        r = client.put(f"/api/v1/ativos/{alvo['id']}", json=corpo, headers=auth_headers)
        assert r.status_code == 200, (
            f"a edição recusou o corpo do formulário:\n{r.text}"
        )

    def test_os_campos_de_locacao_sao_aplicados(self, client, auth_headers):
        """Aceitar e ignorar seria pior que recusar.

        O router aplica por `setattr` genérico — mas se alguém trocar isso por
        uma lista de campos, os novos ficariam de fora sem aviso.
        """
        ativos = client.get("/api/v1/ativos?size=1", headers=auth_headers).json()
        itens = ativos.get("items", [])
        if not itens:
            pytest.skip("sem ativos no banco de teste")

        alvo = itens[0]
        corpo = {**CORPO_DO_FORMULARIO, "numero_serie": f"NS-{alvo['patrimonio']}", "patrimonio": alvo["patrimonio"],
                 "forma_aquisicao": "locado"}

        r = client.put(f"/api/v1/ativos/{alvo['id']}", json=corpo, headers=auth_headers)
        assert r.status_code == 200, r.text
        devolvido = r.json()
        forma = devolvido.get("forma_aquisicao")
        assert getattr(forma, "value", forma) == "locado", (
            "o campo foi aceito mas NÃO aplicado — pior que recusar"
        )

    def test_campo_desconhecido_continua_recusado(self, client, auth_headers):
        """A proteção não pode ter sido afrouxada para consertar isto.

        `extra="forbid"` existe para pegar divergência entre tela e API. A
        correção foi acrescentar os campos CERTOS, não liberar geral.
        """
        ativos = client.get("/api/v1/ativos?size=1", headers=auth_headers).json()
        itens = ativos.get("items", [])
        if not itens:
            pytest.skip("sem ativos no banco de teste")

        alvo = itens[0]
        r = client.put(f"/api/v1/ativos/{alvo['id']}",
                       json={"campo_que_nao_existe": 1}, headers=auth_headers)
        assert r.status_code == 422, "aceitou campo desconhecido"
