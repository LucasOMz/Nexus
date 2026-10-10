"""Plataforma: auditoria imutável, limite de requisições, LGPD e MFA.

Tudo de lógica pura — sem banco, sem rede, sem serviço externo. É o que
permite verificar estas quatro peças de confiabilidade.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.auditoria_cadeia import (
    GENESIS,
    calcular_hash,
    conferir_selo,
    encadear,
    selo,
    verificar,
)
from app.services.plataforma import (
    RETENCAO,
    Limitador,
    anonimizar,
    conferir_codigo,
    decidir,
    gerar_codigo,
    gerar_codigos_de_recuperacao,
    gerar_segredo,
    plano_de_expurgo,
    prazo_de,
    uri_otpauth,
)

AGORA = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _logs(n=5):
    return [{"id": i, "acao": "editar", "alvo": f"ativo-{i}",
             "criado_em": f"2026-10-0{i + 1}T10:00:00"} for i in range(n)]


# ===========================================================================
class TestCadeiaDeAuditoria:
    """O log diz o que aconteceu. A cadeia prova que ninguém reescreveu."""

    def test_encadeia_em_ordem(self):
        c = encadear(_logs(3))
        assert c[0]["hash_anterior"] == GENESIS
        assert c[1]["hash_anterior"] == c[0]["hash"]
        assert c[2]["hash_anterior"] == c[1]["hash"]

    def test_cadeia_recem_montada_e_integra(self):
        assert verificar(encadear(_logs(5)))["integra"]

    def test_cadeia_vazia_e_integra(self):
        assert verificar([])["integra"]

    def test_alterar_conteudo_e_detectado(self):
        c = encadear(_logs(5))
        c[2]["acao"] = "excluir"          # a linha que o incriminava
        r = verificar(c)
        assert not r["integra"]
        assert r["indice"] == 2
        assert r["motivo"] == "conteudo alterado"

    def test_remover_registro_e_detectado(self):
        c = encadear(_logs(5))
        del c[2]
        r = verificar(c)
        assert not r["integra"]
        assert r["motivo"] in ("encadeamento quebrado", "conteudo alterado")

    def test_reordenar_e_detectado(self):
        c = encadear(_logs(5))
        c[1], c[2] = c[2], c[1]
        assert not verificar(c)["integra"]

    def test_adulterar_o_primeiro_quebra_todos(self):
        """Uma alteração antiga invalida toda a cadeia seguinte."""
        c = encadear(_logs(5))
        c[0]["acao"] = "outra"
        r = verificar(c)
        assert not r["integra"]
        assert r["indice"] == 0

    def test_aponta_onde_rompeu(self):
        c = encadear(_logs(10))
        c[7]["alvo"] = "outro"
        r = verificar(c)
        assert r["indice"] == 7
        assert r["registro_id"] == 7
        assert r["verificados"] == 7

    def test_hash_ordem_de_chave_nao_importa(self):
        """O mesmo registro com chaves em ordem diferente dá o mesmo hash."""
        a = calcular_hash({"id": 1, "acao": "x"}, GENESIS)
        b = calcular_hash({"acao": "x", "id": 1}, GENESIS)
        assert a == b

    def test_hash_anterior_muda_o_resultado(self):
        assert calcular_hash({"id": 1}, GENESIS) != calcular_hash({"id": 1}, "a" * 64)


class TestSeloExterno:
    """Guardar o topo da cadeia FORA fecha a brecha."""

    def test_selo_guarda_o_ultimo_hash(self):
        c = encadear(_logs(5))
        s = selo(c, agora=AGORA)
        assert s["ultimo_hash"] == c[-1]["hash"]
        assert s["registros"] == 5

    def test_selo_confere_com_a_mesma_cadeia(self):
        c = encadear(_logs(5))
        assert conferir_selo(c, selo(c, agora=AGORA))["confere"]

    def test_cadeia_crescendo_continua_conferindo(self):
        """Registro novo não invalida o selo antigo."""
        c = encadear(_logs(5))
        s = selo(c, agora=AGORA)
        c2 = encadear(_logs(8))
        assert conferir_selo(c2, s)["confere"]

    def test_registros_removidos_sao_detectados(self):
        c = encadear(_logs(8))
        s = selo(c, agora=AGORA)
        assert not conferir_selo(c[:4], s)["confere"]

    def test_historico_reescrito_e_detectado(self):
        """Apagar e recriar a cadeia inteira: o hash selado não bate."""
        c = encadear(_logs(5))
        s = selo(c, agora=AGORA)
        forjado = encadear([{**r, "acao": "falso"} for r in _logs(5)])
        assert len(forjado) == 5
        assert not conferir_selo(forjado, s)["confere"]


# ===========================================================================
class TestLimitador:
    """Conter abuso acidental: script em laço, celular reenviando."""

    def test_permite_ate_o_limite(self):
        lim = Limitador(limite=3, janela_s=60)
        assert all(lim.permitir("ip", 1000 + i)["permitido"] for i in range(3))

    def test_bloqueia_acima_do_limite(self):
        lim = Limitador(limite=3, janela_s=60)
        for i in range(3):
            lim.permitir("ip", 1000 + i)
        r = lim.permitir("ip", 1004)
        assert not r["permitido"]
        assert r["restantes"] == 0
        assert r["recomeca_em_s"] > 0

    def test_janela_deslizante_libera(self):
        lim = Limitador(limite=2, janela_s=60)
        lim.permitir("ip", 1000)
        lim.permitir("ip", 1001)
        assert not lim.permitir("ip", 1002)["permitido"]
        assert lim.permitir("ip", 1070)["permitido"]

    def test_chaves_diferentes_nao_se_misturam(self):
        lim = Limitador(limite=1, janela_s=60)
        assert lim.permitir("a", 1000)["permitido"]
        assert lim.permitir("b", 1000)["permitido"]
        assert not lim.permitir("a", 1001)["permitido"]

    def test_conta_restantes(self):
        lim = Limitador(limite=5, janela_s=60)
        assert lim.permitir("ip", 1000)["restantes"] == 4
        assert lim.permitir("ip", 1001)["restantes"] == 3

    def test_esquecer_libera(self):
        """Login bem-sucedido zera o contador."""
        lim = Limitador(limite=1, janela_s=60)
        lim.permitir("ip", 1000)
        lim.esquecer("ip")
        assert lim.permitir("ip", 1001)["permitido"]

    def test_teto_de_chaves_nao_cresce_sem_fim(self):
        """Um ataque com milhões de IPs falsos não pode encher a memória."""
        lim = Limitador(limite=1, janela_s=10, max_chaves=50)
        for i in range(500):
            lim.permitir(f"ip-{i}", 1000 + i)
        assert len(lim._marcas) <= 51


# ===========================================================================
class TestRetencao:
    """Dado guardado sem motivo vira passivo. Apagar de mais também."""

    def test_auditoria_e_anonimizada_e_nao_apagada(self):
        """A trilha 'alguém alterou o ativo X' continua; QUEM era, não."""
        assert RETENCAO["auditoria"]["acao"] == "anonimizar"

    def test_movimentacao_fica_por_década(self):
        assert RETENCAO["movimentacoes"]["dias"] >= 365 * 10

    def test_dentro_do_prazo_e_mantido(self):
        recente = (AGORA - timedelta(days=10)).isoformat()
        assert decidir("reportes", recente, agora=AGORA)["acao"] == "manter"

    def test_fora_do_prazo_e_expurgado(self):
        antigo = (AGORA - timedelta(days=365 * 3)).isoformat()
        d = decidir("reportes", antigo, agora=AGORA)
        assert d["acao"] == "apagar"
        assert d["vencido_em"]

    def test_prazo_por_tipo(self):
        assert prazo_de("logs_acesso", agora=AGORA) == (AGORA.date() - timedelta(days=180))

    def test_tipo_sem_politica_e_mantido(self):
        """Na dúvida, não se apaga."""
        assert decidir("tipo_novo", AGORA.isoformat(), agora=AGORA)["acao"] == "manter"

    def test_sem_data_nao_expurga(self):
        assert decidir("reportes", None, agora=AGORA)["acao"] == "manter"

    def test_foto_fica_enquanto_o_ativo_existir(self):
        assert RETENCAO["fotos"]["dias"] is None
        assert decidir("fotos", "2015-01-01", agora=AGORA)["acao"] == "vincular_ao_ativo"

    def test_plano_conta_por_tipo_e_acao(self):
        registros = [
            {"tipo": "reportes", "criado_em": (AGORA - timedelta(days=1000)).isoformat()},
            {"tipo": "reportes", "criado_em": (AGORA - timedelta(days=10)).isoformat()},
            {"tipo": "logs_acesso", "criado_em": (AGORA - timedelta(days=300)).isoformat()},
        ]
        p = plano_de_expurgo(registros, agora=AGORA)
        assert p["por_tipo"]["reportes"]["apagar"] == 1
        assert p["por_tipo"]["reportes"]["manter"] == 1
        assert p["por_tipo"]["logs_acesso"]["apagar"] == 1

    def test_plano_nao_expurga_nada(self):
        """É só um retrato — quem confirma é a pessoa."""
        registros = [{"tipo": "reportes", "criado_em": "2000-01-01"}]
        assert plano_de_expurgo(registros, agora=AGORA)["total"] == 1

    def test_anonimizar_tira_a_pessoa(self):
        r = anonimizar({"acao": "editar", "usuario_nome": "Fulano",
                        "usuario_id": 7, "ip": "10.0.0.1", "alvo": "ativo-9"})
        assert r["usuario_nome"] == "[anonimizado]"
        assert r["ip"] == "[anonimizado]"
        assert r["usuario_id_original"] is None
        assert r["alvo"] == "ativo-9", "o FATO permanece"
        assert r["acao"] == "editar"

    def test_anonimizar_marca_o_registro(self):
        assert anonimizar({"acao": "x"})["anonimizado"] is True


# ===========================================================================
class TestMFA:
    """Segunda etapa para administradores (TOTP, RFC 6238)."""

    SEGREDO = "JBSWY3DPEHPK3PXP"   # valor de exemplo da própria RFC

    def test_codigo_tem_seis_digitos(self):
        c = gerar_codigo(self.SEGREDO, AGORA)
        assert len(c) == 6 and c.isdigit()

    def test_codigo_e_estavel_no_mesmo_intervalo(self):
        a = gerar_codigo(self.SEGREDO, AGORA)
        b = gerar_codigo(self.SEGREDO, AGORA + timedelta(seconds=10))
        assert a == b

    def test_codigo_muda_no_intervalo_seguinte(self):
        a = gerar_codigo(self.SEGREDO, AGORA)
        b = gerar_codigo(self.SEGREDO, AGORA + timedelta(seconds=31))
        assert a != b

    def test_confere_o_codigo_certo(self):
        c = gerar_codigo(self.SEGREDO, AGORA)
        assert conferir_codigo(self.SEGREDO, c, AGORA)

    def test_recusa_codigo_errado(self):
        assert not conferir_codigo(self.SEGREDO, "000000", AGORA)

    def test_aceita_o_intervalo_anterior(self):
        """Relógios diferentes e digitação no limite não podem recusar."""
        c = gerar_codigo(self.SEGREDO, AGORA - timedelta(seconds=30))
        assert conferir_codigo(self.SEGREDO, c, AGORA)

    def test_aceita_o_intervalo_seguinte(self):
        c = gerar_codigo(self.SEGREDO, AGORA + timedelta(seconds=30))
        assert conferir_codigo(self.SEGREDO, c, AGORA)

    def test_recusa_muito_antigo(self):
        c = gerar_codigo(self.SEGREDO, AGORA - timedelta(seconds=300))
        assert not conferir_codigo(self.SEGREDO, c, AGORA)

    def test_segredo_diferente_nao_confere(self):
        c = gerar_codigo(self.SEGREDO, AGORA)
        assert not conferir_codigo(gerar_segredo(), c, AGORA)

    def test_entrada_invalida_nao_quebra(self):
        for ruim in ("", "abc", "12345", "1234567", None, "12 34"):
            assert not conferir_codigo(self.SEGREDO, ruim, AGORA)

    def test_segredo_gerado_e_base32_valido(self):
        s = gerar_segredo()
        assert len(s) >= 26
        assert gerar_codigo(s, AGORA).isdigit()

    def test_espacos_no_codigo_sao_tolerados(self):
        """App mostra '123 456'; colar com espaço não pode falhar."""
        c = gerar_codigo(self.SEGREDO, AGORA)
        assert conferir_codigo(self.SEGREDO, f"{c[:3]} {c[3:]}", AGORA)

    def test_uri_para_o_aplicativo(self):
        u = uri_otpauth(self.SEGREDO, "admin@empresa.com")
        assert u.startswith("otpauth://totp/")
        assert f"secret={self.SEGREDO}" in u
        assert "issuer=" in u

    def test_codigos_de_recuperacao_sao_distintos(self):
        cs = gerar_codigos_de_recuperacao(8)
        assert len(set(cs)) == 8
        assert all(len(c) == 9 for c in cs)

    def test_recuperacao_evita_perder_o_acesso(self):
        """Sem isso, perder o celular vira desligar o MFA — pior que não ter."""
        assert len(gerar_codigos_de_recuperacao()) == 8
