"""Sistema zerado: o caminho completo de software e licencas, do inicio.

## O que este teste prova

Nao depende de dado nenhum existente. Cria o cenario do zero e percorre o
fluxo inteiro, na ordem em que acontece numa instalacao nova:

1. instala -> planta + administrador
2. agente registra -> ativo nasce
3. agente envia software -> inventario populado
4. administrador cadastra o software que exige licenca
5. cadastra a licenca (seats)
6. atribui a maquina
7. conformidade: **conforme**
8. revoga a atribuicao
9. conformidade: **sem licenca**

Se qualquer elo quebrar, o teste falha — e o sistema "funcional" para de ser
uma promessa.

## Por que ele existe separado dos outros

Os testes de unidade provam cada peca. Este prova que as pecas **se
encaixam**: que o nome que o agente grava e o mesmo que o `padroes` do
cadastro reconhece, que a atribuicao aponta para o ativo certo, que a
conformidade le tudo isso junto.
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
    Usuario,
)
from app.models.enums import (
    Dominio,
    PapelUsuario,
    SituacaoConformidade,
    StatusAtivo,
    TipoItem,
    TipoLicenca,
)
from app.services import agente_service, conformidade, software_agente


def _instalacao_nova():
    """Uma instalacao recem-criada: banco vazio, uma planta, um administrador."""
    e = create_engine("sqlite://", future=True)
    Base.metadata.create_all(e)
    db = sessionmaker(bind=e, future=True)()

    planta = Planta(nome="Matriz", sigla="MAT", ativa=True)
    db.add(planta)
    db.commit()

    admin = Usuario(
        nome="Administrador",
        email="admin@empresa.com",
        senha_hash="x",
        papel=PapelUsuario.ADMIN,
        planta_id=None,
    )
    db.add(admin)
    db.commit()

    return db, planta, admin


class TestSistemaZerado:
    def test_fluxo_completo_do_zero(self):
        db, planta, admin = _instalacao_nova()

        # --- 1. agente registra a maquina --------------------------------
        _registro, codigo = agente_service.gerar_codigo(
            db, dias=7, usos_max=10, planta_id=planta.id,
        )
        r = agente_service.registrar(
            db, codigo=codigo, serial="SN-0001", hostname="PC-01",
            payload={"basico": {"hostname": "PC-01", "so": "Windows 11",
                                "fabricante": "Dell Inc.", "modelo": "OptiPlex"}},
        )
        assert r["ok"] is True, r

        ativo = db.query(Ativo).filter(Ativo.numero_serie == "SN-0001").one()
        assert ativo.planta_id == planta.id, "nasceu na planta errada"

        # --- 2. agente envia a lista de programas ------------------------
        res = software_agente.registrar_software(db, ativo.id, [
            {"nome": "AutoCAD 2024", "versao": "24.0", "fabricante": "Autodesk"},
            {"nome": "Google Chrome", "versao": "157.0", "fabricante": "Google"},
        ])
        assert res["gravados"] == 2

        # --- 3. administrador cadastra o que exige licenca ---------------
        sw = Software(nome="AutoCAD", fabricante="Autodesk", planta_id=planta.id)
        sw.padroes = "*autocad*"
        db.add(sw)
        db.commit()

        # --- 4. sem licenca: inconformidade ------------------------------
        linhas = conformidade.calcular(db, [sw])
        assert len(linhas) == 1, linhas
        assert linhas[0]["instalado"] == 1
        assert linhas[0]["situacao"] == SituacaoConformidade.SEM_LICENCA

        # --- 5. compra e cadastra a licenca ------------------------------
        lic = Licenca(software_id=sw.id, tipo=TipoLicenca.PERPETUA,
                      seats=1, planta_id=planta.id)
        db.add(lic)
        db.commit()

        # Comprou, mas ninguem atribuiu: continua inconforme.
        linhas = conformidade.calcular(db, [sw])
        assert linhas[0]["licenciado"] == 1
        assert linhas[0]["atribuido"] == 0
        assert linhas[0]["situacao"] == SituacaoConformidade.SEM_LICENCA

        # --- 6. atribui a maquina ----------------------------------------
        db.add(AtribuicaoLicenca(licenca_id=lic.id, ativo_id=ativo.id,
                                 origem="manual"))
        db.commit()

        linhas = conformidade.calcular(db, [sw])
        assert linhas[0]["atribuido"] == 1
        assert linhas[0]["situacao"] == SituacaoConformidade.CONFORME

        # --- 7. revoga: volta a inconformidade ---------------------------
        db.query(AtribuicaoLicenca).delete()
        db.commit()

        linhas = conformidade.calcular(db, [sw])
        assert linhas[0]["situacao"] == SituacaoConformidade.SEM_LICENCA

        db.close()

    def test_programa_nao_cadastrado_nao_polui_a_tela(self):
        """Instalacao nova: 150 programas, zero cadastros, zero alarme."""
        db, planta, _admin = _instalacao_nova()

        db.add(Ativo(planta_id=planta.id, dominio=Dominio.TI,
                     tipo_item=TipoItem.ATIVO, status=StatusAtivo.ESTOQUE,
                     numero_serie="SN-9"))
        db.commit()

        software_agente.registrar_software(db, 1, [
            {"nome": "Programa %d" % i, "versao": "1.0"} for i in range(150)
        ])

        linhas = conformidade.calcular(db, [])

        assert linhas == [], "a tela abriria com 150 inconformidades"
        db.close()

    def test_impressora_nao_entra_na_conformidade(self):
        """Instalacao nova com impressora: ela nao tem software."""
        db, planta, _admin = _instalacao_nova()

        db.add(Ativo(planta_id=planta.id, dominio=Dominio.IMPRESSORA,
                     tipo_item=TipoItem.ATIVO, status=StatusAtivo.ESTOQUE,
                     numero_serie="IMP-1"))
        db.commit()

        linhas = conformidade.calcular(db, [])

        assert linhas == []
        db.close()

    def test_instalacao_virgem_nao_tem_software_nem_licenca(self):
        """Estado real de um sistema recem-instalado."""
        db, _planta, _admin = _instalacao_nova()

        assert db.query(Software).count() == 0
        assert db.query(Licenca).count() == 0
        assert db.query(AtribuicaoLicenca).count() == 0
        assert db.query(SoftwareInstalado).count() == 0

        assert conformidade.calcular(db, []) == []
        db.close()
