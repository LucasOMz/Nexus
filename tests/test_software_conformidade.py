"""Conformidade: o casamento entre instalado e licenciado.

## O que está em jogo

**Comparar por nome exato não acha nada.**

O OCS reporta `Microsoft Office LTSC Professional Plus 2021`; a licença está
cadastrada como `Office 2021`. Um relatório que não casa nada **não é um
relatório com zero problemas** — é um relatório quebrado que parece limpo.

A pessoa abre, vê tudo conforme, e conclui que está tudo bem. É a pior falha
possível neste módulo: silenciosa, e no sentido tranquilizador.
"""
from __future__ import annotations

import pytest

from app.services import conformidade as c


@pytest.fixture
def db_session(client):
    """A sessão do banco de teste.

    O `client` entra como dependência de propósito: é ele que cria a
    estrutura e a planta padrão. Sem pedir o `client` primeiro, a sessão
    abriria num banco vazio.
    """
    from app.database import get_db
    from app.main import app

    return next(app.dependency_overrides[get_db]())


class TestCasamento:
    """O padrão precisa casar o nome que o OCS realmente reporta."""

    @pytest.mark.parametrize("nome,padroes", [
        # O caso real: o nome carrega edição, idioma e sufixo.
        ("Microsoft Office LTSC Professional Plus 2021", ["microsoft office*2021"]),
        ("Microsoft Office LTSC 2021 - pt-br", ["office*2021*"]),
        ("Microsoft Office 2021", ["office 2021"]),
        ("Microsoft Office LTSC Professional Plus 2021 - pt-br", ["microsoft office*"]),
        # `fnmatch` ancora no início: o nome começa pelo fabricante, e o
        # padrão precisa valer em QUALQUER posição.
        ("Adobe Acrobat Pro DC", ["acrobat*"]),
        ("Autodesk AutoCAD 2024 - Portugues", ["autocad*"]),
        ("Google Chrome", ["chrome"]),
    ])
    def test_casa(self, nome, padroes):
        assert c.casa(nome, padroes) is True

    @pytest.mark.parametrize("nome,padroes", [
        ("Google Chrome", ["microsoft office*2021"]),
        ("7-Zip", ["winrar"]),
        ("Notepad++", ["office"]),
        ("", ["office"]),
    ])
    def test_nao_casa(self, nome, padroes):
        assert c.casa(nome, padroes) is False

    def test_sem_padroes_nao_casa_nada(self):
        assert c.casa("Qualquer Coisa", []) is False

    def test_ignora_maiusculas_e_espacos(self):
        """O OCS varia entre coletas; a comparação não pode depender disso."""
        assert c.casa("MICROSOFT   OFFICE  2021", ["office 2021"]) is True

    def test_varios_padroes_basta_um(self):
        assert c.casa("LibreOffice 7.6", ["microsoft office", "libreoffice*"]) is True

    def test_padrao_vazio_e_ignorado(self):
        """Um `;;` no cadastro não pode fazer casar com tudo."""
        assert c.casa("Google Chrome", ["", "  "]) is False


class TestSituacao:
    def test_excedente_quando_instala_mais_que_compra(self):
        assert c.situacao(50, 63).value == "excedente"

    def test_ocioso_quando_compra_mais_que_usa(self):
        """Comprar 50 e usar 31 é dinheiro parado — precisa aparecer."""
        assert c.situacao(50, 31).value == "ocioso"

    def test_conforme_quando_bate(self):
        assert c.situacao(50, 50).value == "conforme"

    def test_sem_licenca_quando_instalado_e_nada_comprado(self):
        """O caso mais grave — e o que nenhum relatório tradicional mostra."""
        assert c.situacao(0, 10).value == "sem_licenca"

    def test_nao_instalado(self):
        assert c.situacao(0, 0).value == "nao_instalado"


class TestOrdenacao:
    def test_o_que_preocupa_vem_primeiro(self):
        """A tela abre por aqui: risco não pode ficar na página 4."""
        linhas = [
            {"situacao": c.SituacaoConformidade.CONFORME, "diferenca": 0},
            {"situacao": c.SituacaoConformidade.OCIOSO, "diferenca": -19},
            {"situacao": c.SituacaoConformidade.EXCEDENTE, "diferenca": 13},
            {"situacao": c.SituacaoConformidade.SEM_LICENCA, "diferenca": 10},
        ]
        ordem = [x["situacao"] for x in c.ordenar(linhas)]
        assert ordem[0] == c.SituacaoConformidade.EXCEDENTE
        assert ordem[1] == c.SituacaoConformidade.SEM_LICENCA
        assert ordem[-1] == c.SituacaoConformidade.CONFORME


class TestNormalizacao:
    def test_espacos_duplos_e_caixa(self):
        assert c.normalizar("  Microsoft   Office  ") == "microsoft office"

    def test_none_e_vazio(self):
        assert c.normalizar(None) == ""
        assert c.normalizar("   ") == ""


class TestCalcular:
    """O cruzamento de ponta a ponta, com o banco de teste."""

    def _software(self, db, nome, padroes):
        from app.models.software import Software

        s = Software(nome=nome, padroes=padroes)
        db.add(s)
        db.commit()
        db.refresh(s)
        return s

    def _instalado(self, db, nome, quantas, dominio="ti"):
        """Grava `quantas` instalações, cada uma num ativo **de verdade**.

        Usar um `ativo_id` inventado parecia mais simples, mas o relatório
        junta com a tabela de ativos — para saber a planta, e para não contar
        instalação de máquina que já não existe. Com id falso, a linha some e
        o teste mede zero.
        """
        from app.models.core import Ativo, Planta
        from app.models.software import SoftwareInstalado

        planta = db.query(Planta).first()
        for i in range(quantas):
            a = Ativo(dominio=dominio, tipo_item="ativo",
                      patrimonio=f"INST-{nome[:6]}-{i}",
                      planta_id=planta.id if planta else None, status="estoque")
            db.add(a)
            db.flush()
            db.add(SoftwareInstalado(nome=nome, ativo_id=a.id, dominio=dominio))
        db.commit()

    def test_conta_instalacoes_por_padrao(self, db_session):
        s = self._software(db_session, "Office 2021", "office*2021*")
        self._instalado(db_session, "Microsoft Office LTSC 2021 - pt-br", 3)

        linhas = c.calcular(db_session, [s])
        linha = [x for x in linhas if x["software_id"] == s.id][0]
        assert linha["instalado"] == 3
        assert linha["situacao"] == c.SituacaoConformidade.SEM_LICENCA

    def test_nao_conta_duas_vezes_o_mesmo_nome(self, db_session):
        """Um padrão genérico não pode fazer o parque contar em dobro."""
        a = self._software(db_session, "Office", "office*")
        b = self._software(db_session, "Office LTSC", "*office*")
        self._instalado(db_session, "Microsoft Office 2021", 2)

        linhas = c.calcular(db_session, [a, b])
        total = sum(x["instalado"] for x in linhas if x["software_id"] in (a.id, b.id))
        assert total == 2, "o mesmo software foi contado duas vezes"

    def test_o_nao_reconhecido_vira_sem_licenca(self, db_session):
        """Instalado e não cadastrado é uso irregular — e passa batido."""
        s = self._software(db_session, "Office", "office*")
        self._instalado(db_session, "WinRAR 6.24", 5)

        linhas = c.calcular(db_session, [s])
        orfaos = [x for x in linhas if x["software_id"] == 0]
        assert orfaos, "o software sem licença não apareceu"
        assert orfaos[0]["instalado"] == 5
        assert orfaos[0]["situacao"] == c.SituacaoConformidade.SEM_LICENCA

    def test_guarda_os_nomes_que_casaram(self, db_session):
        """Explicar POR QUE contou é o que permite corrigir o padrão."""
        s = self._software(db_session, "Office", "office*")
        self._instalado(db_session, "Microsoft Office LTSC 2021", 1)

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id][0]
        assert "Microsoft Office LTSC 2021" in linha["origens"]

    def test_software_sem_instalacao_nao_e_escondido(self, db_session):
        """"Compramos e ninguém usa" é informação, não ruído."""
        from app.models.software import Licenca

        s = self._software(db_session, "AutoCAD", "autocad*")
        db_session.add(Licenca(software_id=s.id, tipo="perpetua", seats=5,
                               validade=None, chave_versao=1))
        db_session.commit()

        linha = [x for x in c.calcular(db_session, [s]) if x["software_id"] == s.id][0]
        assert linha["instalado"] == 0
        assert linha["licenciado"] == 5
        assert linha["situacao"] == c.SituacaoConformidade.OCIOSO

    def test_resumo_conta_por_situacao(self, db_session):
        s = self._software(db_session, "Office", "office*")
        self._instalado(db_session, "Microsoft Office 2021", 3)

        linhas = c.calcular(db_session, [s])
        r = c.resumo(linhas)
        assert r["sem_licenca"] >= 1
        assert "custo_mensal" in r
