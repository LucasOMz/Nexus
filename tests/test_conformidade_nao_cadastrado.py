"""Software instalado sem cadastro vira inconformidade.

## O cenario do usuario

> "o usuario que tiver um AutoCAD instalado, e nao tiver na lista de
> atribuicao, ele esta como inconformidade"

Antes, `calcular` percorria **so os softwares cadastrados**. Um programa
instalado que ninguem cadastrou nao aparecia em lugar nenhum — nem como
conforme, nem como inconformidade. O tecnico nao ficava sabendo.

Agora ele entra na lista como `sem_licenca`, com `nao_cadastrado = True`.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Ativo, Base, Planta, Software, SoftwareInstalado
from app.models.enums import Dominio, SituacaoConformidade, StatusAtivo, TipoItem
from app.services import conformidade


def _banco():
    e = create_engine("sqlite://", future=True)
    Base.metadata.create_all(e)
    db = sessionmaker(bind=e, future=True)()

    db.add(Planta(nome="C", sigla="C", ativa=True))
    db.commit()

    for i in range(1, 4):
        db.add(Ativo(
            planta_id=1,
            dominio=Dominio.TI,
            tipo_item=TipoItem.ATIVO,
            status=StatusAtivo.ESTOQUE,
            numero_serie=f"SN-{i}",
        ))
    db.commit()
    return db


def _instalar(db, ativo_id, nome, versao="1.0"):
    db.add(SoftwareInstalado(
        ativo_id=ativo_id, nome=nome, versao=versao, origem="agente",
    ))
    db.commit()


class TestNaoCadastrado:
    def test_aparece_como_inconformidade(self):
        """O caso central: instalado, sem cadastro, sem atribuicao."""
        db = _banco()
        for ativo_id in (1, 2):
            _instalar(db, ativo_id, "AutoCAD 2024")

        linhas = conformidade.calcular(db, [])

        assert len(linhas) == 1, linhas
        linha = linhas[0]
        assert linha["software"] == "AutoCAD 2024"
        # `0` é o marcador do próprio serviço para "sem cadastro". Não é
        # `None`: a coluna é inteira e 0 não colide com id real.
        assert linha["software_id"] == 0
        assert linha["situacao"] == SituacaoConformidade.SEM_LICENCA
        assert linha["instalado"] == 2
        assert linha["licenciado"] == 0
        db.close()

    def test_cadastrado_nao_vira_nao_cadastrado(self):
        """O que casou com o catalogo continua no fluxo normal."""
        db = _banco()
        _instalar(db, 1, "AutoCAD 2024")

        catalogo = [Software(nome="AutoCAD", fabricante="Autodesk", planta_id=1)]
        catalogo[0].padroes = "*autocad*"
        db.add(catalogo[0])
        db.commit()

        linhas = conformidade.calcular(db, [catalogo[0]])

        sem_cadastro = [x for x in linhas if x["software_id"] == 0]
        assert sem_cadastro == [], sem_cadastro
        assert len(linhas) == 1
        assert linhas[0]["software_id"] == catalogo[0].id
        db.close()

    def test_nao_duplica_o_que_ja_foi_classificado(self):
        """Nome usado por um software cadastrado nao entra duas vezes."""
        db = _banco()
        _instalar(db, 1, "Google Chrome")

        software = Software(nome="Chrome", fabricante="Google", planta_id=1)
        software.padroes = "*chrome*"
        db.add(software)
        db.commit()

        linhas = conformidade.calcular(db, [software])
        assert len(linhas) == 1, [x["software"] for x in linhas]
        db.close()

    def test_resumo_conta_a_inconformidade(self):
        db = _banco()
        _instalar(db, 1, "Programa Pirata")

        linhas = conformidade.calcular(db, [])
        r = conformidade.resumo(linhas)

        assert r["sem_licenca"] == 1
        db.close()

    def test_csv_inclui_nao_cadastrado(self):
        """O tecnico exporta a lista de trabalho — ela precisa sair no CSV."""
        db = _banco()
        _instalar(db, 1, "Programa Pirata")

        csv = conformidade.para_csv(conformidade.calcular(db, []))
        assert "Programa Pirata" in csv
        db.close()
