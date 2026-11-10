"""Conformidade so aponta o que foi cadastrado como licenciado.

## A regra

> "eu cadastro manual o que precisa de licenca, e atraves disso... o usuario
> que tiver instalado e nao tiver a licenca atribuida... vai estar como
> inconformidade"

**Inconformidade = software do catalogo, instalado, sem licenca.**

Programa instalado que ninguem cadastrou **nao** e inconformidade: nao ha
politica dizendo que ele precisa de licenca. Ele aparece na aba **Instalados**,
que e o inventario.

Antes o servico marcava todo programa instalado como `sem_licenca`, e a tela
inteira ficava vermelha.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Ativo,
    AtribuicaoLicenca,
    Base,
    Licenca,
    Planta,
    Software,
    SoftwareInstalado,
)
from app.models.enums import (
    Dominio,
    SituacaoConformidade,
    StatusAtivo,
    TipoItem,
    TipoLicenca,
)
from app.services import conformidade


def _banco():
    e = create_engine("sqlite://", future=True)
    Base.metadata.create_all(e)
    db = sessionmaker(bind=e, future=True)()

    db.add(Planta(nome="C", sigla="C", ativa=True))
    db.commit()

    for i in range(1, 4):
        db.add(Ativo(
            planta_id=1, dominio=Dominio.TI, tipo_item=TipoItem.ATIVO,
            status=StatusAtivo.ESTOQUE, numero_serie=f"SN-{i}",
        ))
    db.commit()
    return db


def _instalar(db, ativo_id, nome, versao="1.0"):
    db.add(SoftwareInstalado(ativo_id=ativo_id, nome=nome, versao=versao, origem="agente"))
    db.commit()


def _software(db, nome, padrao):
    s = Software(nome=nome, fabricante="X", planta_id=1)
    s.padroes = padrao
    db.add(s)
    db.commit()
    return s


class TestNaoCadastrado:
    def test_programa_sem_cadastro_nao_aparece(self):
        """O caso que enchia a tela de vermelho."""
        db = _banco()
        for ativo_id in (1, 2):
            _instalar(db, ativo_id, "AutoCAD 2024")

        linhas = conformidade.calcular(db, [])

        assert linhas == [], [x["software"] for x in linhas]
        db.close()

    def test_cadastrado_aparece(self):
        """Se esta no catalogo, entra na lista — mesmo sem licenca."""
        db = _banco()
        _instalar(db, 1, "AutoCAD 2024")
        sw = _software(db, "AutoCAD", "*autocad*")

        linhas = conformidade.calcular(db, [sw])

        assert len(linhas) == 1, linhas
        assert linhas[0]["software_id"] == sw.id
        assert linhas[0]["instalado"] == 1
        db.close()

    def test_cadastrado_sem_licenca_e_inconformidade(self):
        """O caso central: cadastrou que precisa de licenca e nao tem nenhuma."""
        db = _banco()
        _instalar(db, 1, "AutoCAD 2024")
        sw = _software(db, "AutoCAD", "*autocad*")

        linhas = conformidade.calcular(db, [sw])

        assert linhas[0]["licenciado"] == 0
        assert linhas[0]["situacao"] == SituacaoConformidade.SEM_LICENCA
        db.close()

    def test_cadastrado_com_licenca_suficiente_e_conforme(self):
        db = _banco()
        _instalar(db, 1, "AutoCAD 2024")
        sw = _software(db, "AutoCAD", "*autocad*")
        lic = Licenca(software_id=sw.id, tipo=TipoLicenca.PERPETUA, seats=1, planta_id=1)
        db.add(lic)
        db.commit()

        # Atribuir é o que autoriza: sem a atribuição, seria `sem_licenca`.
        db.add(AtribuicaoLicenca(licenca_id=lic.id, ativo_id=1, origem="manual"))
        db.commit()

        linhas = conformidade.calcular(db, [sw])

        assert linhas[0]["licenciado"] == 1
        assert linhas[0]["atribuido"] == 1
        assert linhas[0]["situacao"] == SituacaoConformidade.CONFORME
        db.close()

    def test_resumo_nao_conta_o_que_nao_foi_cadastrado(self):
        db = _banco()
        _instalar(db, 1, "Programa Qualquer")

        r = conformidade.resumo(conformidade.calcular(db, []))

        assert r["sem_licenca"] == 0
        db.close()

    def test_csv_nao_lista_nao_cadastrado(self):
        db = _banco()
        _instalar(db, 1, "Programa Qualquer")

        csv = conformidade.para_csv(conformidade.calcular(db, []))

        assert "Programa Qualquer" not in csv
        db.close()
