"""Segurança do inventário de software: a chave da licença.

## O que estes testes protegem

Uma chave de licença é um **segredo**: vazada, permite uso irregular e pode ser
revogada pelo fabricante. E o sistema tem uma armadilha específica para ela —
**a auditoria é encadeada por hash e não pode ser editada**. Um segredo que
entra no `diff` está vazado de forma permanente.

Por isso os testes são de segurança, e não de cadastro: eles verificam que a
chave (a) não fica em claro no banco, (b) não sai no diff da auditoria, (c)
não aparece em listagem, e (d) não pode ser lida por quem não tem a chave
mestra.
"""
from __future__ import annotations

import pytest

from app.core import segredos
from app.models.software import Licenca, Software
from app.services.audit_service import CAMPOS_PROTEGIDOS, serialize_entity

CHAVE = "ABCD-1234-EFGH-5678"


@pytest.fixture(autouse=True)
def _com_chave_mestra(monkeypatch):
    """Toda a suíte roda com uma chave mestra. Sem ela, cifrar levanta."""
    monkeypatch.setenv(segredos.VARIAVEL, "chave-mestra-de-teste")
    yield


class TestCifra:
    def test_ida_e_volta(self):
        seg = segredos.cifrar(CHAVE)
        assert seg is not None
        assert segredos.decifrar(seg.cifrado, seg.versao) == CHAVE

    def test_o_cifrado_nao_contem_o_valor(self):
        """O básico: quem lê o banco não lê a chave."""
        seg = segredos.cifrar(CHAVE)
        assert CHAVE.encode() not in seg.cifrado
        assert b"ABCD" not in seg.cifrado

    def test_dois_cifrados_do_mesmo_valor_diferem(self):
        """Fernet inclui IV aleatório: o mesmo valor cifra diferente.

        Sem isso, duas licenças com a mesma chave teriam bytes idênticos — e
        daria para descobrir que são iguais sem decifrar.
        """
        a = segredos.cifrar(CHAVE)
        b = segredos.cifrar(CHAVE)
        assert a.cifrado != b.cifrado

    def test_vazio_e_none_passam_direto(self):
        assert segredos.cifrar(None) is None
        assert segredos.cifrar("") is None
        assert segredos.decifrar(None) is None

    def test_chave_mestra_ausente_avisa_o_que_fazer(self, monkeypatch):
        monkeypatch.delenv(segredos.VARIAVEL, raising=False)
        with pytest.raises(segredos.ChaveMestraAusente) as e:
            segredos.cifrar(CHAVE)
        # A mensagem precisa ser acionável: diz o nome da variável.
        assert segredos.VARIAVEL in str(e.value)

    def test_chave_mestra_errada_nao_decifra(self, monkeypatch):
        seg = segredos.cifrar(CHAVE)
        monkeypatch.setenv(segredos.VARIAVEL, "outra-chave-completamente-diferente")
        with pytest.raises(segredos.SegredoIlegivel):
            segredos.decifrar(seg.cifrado, seg.versao)

    def test_aceita_frase_como_chave_mestra(self):
        """Exigir base64 do Fernet obrigaria o operador a gerar a chave.

        Derivar por SHA-256 aceita qualquer frase — e continua sendo 256 bits
        de entropia quando a frase é boa.
        """
        seg = segredos.cifrar(CHAVE)
        assert segredos.decifrar(seg.cifrado) == CHAVE

    def test_rotacao_de_chave(self, monkeypatch):
        """Girar a chave mestra não pode invalidar o que já está cifrado.

        A chave antiga vai para `NEXUS_CHAVE_LICENCAS_V1`; a atual assume o
        nome principal e a versão sobe para 2. O valor gravado na versão 1
        continua legível — e é isso que torna a rotação possível em vez de
        teórica.
        """
        seg = segredos.cifrar(CHAVE)
        assert seg.versao == 1

        # O giro: a chave que estava em uso vira a versão 1, e a nova assume.
        monkeypatch.setenv(f"{segredos.VARIAVEL}_V1", "chave-mestra-de-teste")
        monkeypatch.setenv(segredos.VARIAVEL, "chave-nova-apos-rotacao")
        monkeypatch.setenv(f"{segredos.VARIAVEL}_VERSAO", "2")

        # O valor antigo ainda abre…
        assert segredos.decifrar(seg.cifrado, 1) == CHAVE
        # …e o re-cifrado nasce na versão 2.
        novo = segredos.recifrar(seg.cifrado, 1)
        assert novo.versao == 2
        assert segredos.decifrar(novo.cifrado) == CHAVE

        # O novo só abre com a chave nova.
        monkeypatch.setenv(segredos.VARIAVEL, "chave-mestra-de-teste")
        with pytest.raises(segredos.SegredoIlegivel):
            segredos.decifrar(novo.cifrado, 2)

    def test_sem_a_chave_antiga_o_legado_nao_abre(self, monkeypatch):
        """A mensagem de erro precisa ser acionável em caso de rotação errada."""
        seg = segredos.cifrar(CHAVE)
        monkeypatch.setenv(segredos.VARIAVEL, "chave-nova-apos-rotacao")
        monkeypatch.setenv(f"{segredos.VARIAVEL}_VERSAO", "2")
        with pytest.raises(segredos.SegredoIlegivel) as e:
            segredos.decifrar(seg.cifrado, 1)
        assert "rotação" in str(e.value)

    def test_a_versao_vem_do_ambiente(self, monkeypatch):
        """Se fosse constante no código, girar a chave exigiria deploy —
        e ninguém gira uma chave que precisa de deploy."""
        assert segredos.versao_atual() == 1
        monkeypatch.setenv(f"{segredos.VARIAVEL}_VERSAO", "3")
        assert segredos.versao_atual() == 3
        monkeypatch.setenv(f"{segredos.VARIAVEL}_VERSAO", "lixo")
        assert segredos.versao_atual() == 1


class TestImpressaoEHash:
    def test_impressao_mostra_so_o_final(self):
        assert segredos.impressao(CHAVE) == "5678"
        assert "ABCD" not in (segredos.impressao(CHAVE) or "")

    def test_mascara_esconde_o_resto(self):
        m = segredos.mascarar(segredos.impressao(CHAVE))
        assert m == "••••-••••-••••-5678"
        assert "ABCD" not in m

    def test_valor_curto_nao_quebra(self):
        assert segredos.impressao("AB") == "AB"
        assert segredos.mascarar(None) == "—"

    def test_hash_ignora_formatacao(self):
        """`ABC-123` e `abc 123` são a mesma chave para quem digita."""
        assert segredos.impressao_hash("ABC-123") == segredos.impressao_hash("abc 123")

    def test_hash_distingue_chaves_diferentes(self):
        assert segredos.impressao_hash("ABC-123") != segredos.impressao_hash("ABC-124")

    def test_hash_nao_revela_o_valor(self):
        h = segredos.impressao_hash(CHAVE)
        assert h is not None
        assert "ABCD" not in h and "5678" not in h
        assert len(h) == 64


class TestDiffDaAuditoria:
    """O teste mais importante deste arquivo.

    Se falhar, a chave entra na auditoria — e a auditoria é imutável.
    """

    def _licenca_com_chave(self) -> Licenca:
        lic = Licenca(tipo="volume", seats=50)
        seg = segredos.cifrar(CHAVE)
        lic.chave_cifrada = seg.cifrado
        lic.chave_versao = seg.versao
        lic.chave_impressao = segredos.impressao(CHAVE)
        lic.chave_hash = segredos.impressao_hash(CHAVE)
        return lic

    def test_a_chave_nao_entra_no_diff(self):
        d = serialize_entity(self._licenca_com_chave())
        assert d["chave_cifrada"] == "<protegido>"
        assert d["chave_impressao"] == "<protegido>"
        assert d["chave_hash"] == "<protegido>"

    def test_nada_do_valor_vaza_por_qualquer_campo(self):
        """Percorre TODOS os valores: um campo novo não protegido seria pego."""
        d = serialize_entity(self._licenca_com_chave())
        for campo, valor in d.items():
            texto = str(valor)
            assert "ABCD" not in texto, f"vazou em {campo}"
            assert "5678" not in texto, f"vazou em {campo}"

    def test_o_registro_diz_que_algo_mudou(self):
        """Proteger não pode significar esconder que houve alteração."""
        d = serialize_entity(self._licenca_com_chave())
        assert d["chave_cifrada"] == "<protegido>"

    def test_campos_normais_continuam_no_diff(self):
        """A proteção não pode cegar a auditoria do resto."""
        d = serialize_entity(self._licenca_com_chave())
        assert d["seats"] == 50
        assert d["tipo"] == "volume"

    def test_todo_campo_de_chave_esta_na_lista(self):
        """Guarda contra campo novo em `Licenca` que nasça desprotegido.

        `chave_versao` é exceção explícita: é o NÚMERO da versão da chave
        mestra (1, 2, 3…), não o segredo. Protegê-lo esconderia qual chave
        usar na rotação — justamente o dado que a operação precisa.
        """
        nao_segredos = {"chave_versao"}

        colunas = {c.name for c in Licenca.__table__.columns}
        sensiveis = {c for c in colunas if "chave" in c or "senha" in c or "token" in c}
        desprotegidos = sensiveis - CAMPOS_PROTEGIDOS - nao_segredos
        assert not desprotegidos, f"campos sensíveis sem proteção: {desprotegidos}"

    def test_senha_de_usuario_nao_entra_no_diff(self):
        """A proteção vale para QUALQUER modelo, não só licença."""
        from app.models.core import Usuario

        u = Usuario(nome="X", email="x@teste.com", senha_hash="hash-secreto-do-usuario")
        d = serialize_entity(u)
        assert d.get("senha_hash") in (None, "<protegido>")


class TestModelo:
    def test_nao_existe_coluna_de_chave_em_claro(self):
        colunas = {c.name for c in Licenca.__table__.columns}
        assert "chave" not in colunas, "existe coluna `chave` em claro!"

    def test_a_chave_cifrada_e_binaria(self):
        col = Licenca.__table__.columns["chave_cifrada"]
        assert col.type.__class__.__name__ in ("LargeBinary", "BLOB")

    def test_mascara_do_modelo_nunca_e_o_valor(self):
        lic = Licenca(tipo="volume", seats=1)
        lic.chave_impressao = segredos.impressao(CHAVE)
        assert "ABCD" not in lic.chave_mascarada
        assert lic.chave_mascarada.endswith("5678")

    def test_perpetua_nunca_vence(self):
        from datetime import date

        lic = Licenca(tipo="perpetua", seats=1, validade=date(2020, 1, 1))
        assert lic.vencida is False

    def test_assinatura_vencida(self):
        from datetime import date

        lic = Licenca(tipo="assinatura", seats=1, validade=date(2020, 1, 1))
        assert lic.vencida is True

    def test_seats_livres(self):
        lic = Licenca(tipo="volume", seats=10)
        lic.atribuicoes = []
        assert lic.seats_livres == 10

    def test_software_sem_padroes_devolve_lista_vazia(self):
        assert Software(nome="X").lista_de_padroes() == []

    def test_padroes_sao_normalizados(self):
        s = Software(nome="Office", padroes=" Office 2021 ;  msoffice* ")
        assert s.lista_de_padroes() == ["office 2021", "msoffice*"]
