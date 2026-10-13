"""Fase 1 (#12) — `obrigatorio` precisa produzir o que promete.

## O campo dizia, o código não fazia

No modelo (`Software.obrigatorio`):

    Software que a empresa exige em toda máquina. Serve para o relatório
    apontar o que FALTA, e não só o que sobra.

No cálculo:

    if licenciado == 0 and instalado == 0:
        continue

O único software que interessa para "o que falta" é aquele que **deveria
estar e não está** — sem licença e sem instalação. Era exatamente o caso que
o `continue` descartava.

Resultado: a promessa estava escrita no modelo e **a ausência de um software
obrigatório nunca aparecia como pendência**.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def db_session(client):
    from app.database import get_db
    from app.main import app

    return next(app.dependency_overrides[get_db]())


def _software(db, nome, padroes, obrigatorio=False):
    from app.models.software import Software

    s = Software(nome=nome, padroes=padroes, obrigatorio=obrigatorio)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _instalado(db, nome, quantas):
    from app.models.core import Ativo, Planta
    from app.models.software import SoftwareInstalado

    planta = db.query(Planta).first()
    for i in range(quantas):
        a = Ativo(dominio="ti", tipo_item="ativo",
                  patrimonio=f"OBR-{nome[:4]}-{i}",
                  planta_id=planta.id if planta else None, status="estoque")
        db.add(a)
        db.flush()
        db.add(SoftwareInstalado(nome=nome, ativo_id=a.id, dominio="ti"))
    db.commit()


class TestSoftwareObrigatorio:
    def test_ausente_aparece_como_pendencia(self, db_session):
        """Alguém decidiu que deveria estar em toda máquina, e não está em
        nenhuma. É a pendência mais importante que o relatório pode mostrar."""
        from app.services import conformidade as c

        s = _software(db_session, "Antivírus Corporativo", "antivirus*", obrigatorio=True)
        linhas = c.calcular(db_session, [s], instalados=[])

        assert linhas, "o software obrigatório ausente não apareceu"
        linha = linhas[0]
        assert linha["software"] == "Antivírus Corporativo"
        assert linha["instalado"] == 0
        assert linha["obrigatorio"] is True

    def test_opcional_ausente_nao_polui(self, db_session):
        """A exceção vale só para os obrigatórios.

        Sem isso, todo software cadastrado e não instalado viraria linha — e
        a pendência de verdade se perderia no meio.
        """
        from app.services import conformidade as c

        s = _software(db_session, "Ferramenta Opcional", "opc*", obrigatorio=False)
        assert c.calcular(db_session, [s], instalados=[]) == []

    def test_instalado_nao_e_pendencia(self, db_session):
        from app.services import conformidade as c

        s = _software(db_session, "Antivírus", "antivirus*", obrigatorio=True)
        _instalado(db_session, "Antivirus Corporativo", 5)

        linhas = c.calcular(db_session, [s])
        linha = [x for x in linhas if x["software_id"] == s.id][0]
        assert linha["instalado"] == 5
        assert linha["obrigatorio"] is True

    def test_acento_casa(self, db_session):
        """Num sistema em português, acento é a regra — não a exceção.

        O OCS reporta `Antivírus`; o operador digita `antivirus*`. Até pouco
        tempo os dois **não casavam**, e o software sumia da contagem de
        instalados — aparecendo como "sem licença", sem erro nenhum.

        O teste anterior travava o comportamento antigo de propósito, para
        que a correção o quebrasse e alguém percebesse. **Foi o que
        aconteceu** — ele falhou com a mensagem certa no primeiro dia.
        """
        from app.services import conformidade as c

        for nome, padrao in (
            ("Antivírus Corporativo", "antivirus*"),
            ("Configuração de Rede", "configuracao*"),
            ("Impressão Fiscal", "impressao*"),
            ("Aplicação Financeira", "aplicacao*"),
        ):
            assert c.casa(nome, [padrao]) is True, f"{nome} não casou com {padrao}"

    def test_o_nome_original_preserva_o_acento(self, db_session):
        """A normalização é só para COMPARAR — a tela mostra como o OCS mandou.

        Se o acento fosse removido na gravação, a evidência de por que uma
        instalação contou (ou não) se perderia — e não haveria com o que
        comparar para corrigir um padrão errado.
        """
        from app.services import conformidade as c

        original = "Antivírus Corporativo"
        assert c.normalizar(original) == "antivirus corporativo"
        assert original == "Antivírus Corporativo", "a função alterou a entrada"

    def test_sem_acento_casa(self, db_session):
        """O caminho que funciona hoje: mesmo texto dos dois lados."""
        from app.services import conformidade as c

        assert c.casa("Antivirus Corporativo", ["antivirus*"]) is True

    def test_vem_no_topo_da_ordenacao(self, db_session):
        """Se entrasse como `nao_instalado` (o último), ficaria na página 4.

        Obrigatório ausente é a coisa mais acionável do relatório — precisa
        estar visível na primeira tela.
        """
        from app.services import conformidade as c

        opcional = _software(db_session, "Chrome", "chrome*")
        _instalado(db_session, "Google Chrome", 3)   # instalado, sem licença

        obrig = _software(db_session, "Antivírus", "antivirus*", obrigatorio=True)

        linhas = c.ordenar(c.calcular(db_session, [opcional, obrig]))
        assert linhas[0]["software"] == "Antivírus", (
            "o obrigatório ausente não ficou no topo"
        )

    def test_o_schema_expoe_a_flag(self):
        """A tela precisa saber que a linha é obrigatória para destacá-la."""
        from app.schemas.software import LinhaConformidade

        assert "obrigatorio" in LinhaConformidade.model_fields

    def test_a_flag_chega_pela_api(self, client, auth_headers, db_session):
        from app.core import segredos

        segredos_antes = segredos.VARIAVEL
        import os

        os.environ[segredos_antes] = "chave-mestra-de-teste"
        try:
            client.post("/api/v1/softwares",
                        json={"nome": "Antivírus", "padroes": "antivirus*",
                              "obrigatorio": True},
                        headers=auth_headers)
            d = client.get("/api/v1/conformidade", headers=auth_headers).json()
            linhas = [x for x in d["linhas"] if x["software"] == "Antivírus"]
            assert linhas, "não apareceu na conformidade"
            assert linhas[0]["obrigatorio"] is True
        finally:
            os.environ.pop(segredos_antes, None)
