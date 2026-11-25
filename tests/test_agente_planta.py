"""O codigo de instalacao define a planta do ativo registrado.

## O que estava errado

`_criar_ativo_do_payload` usava **a primeira planta ativa** como dona. Com
uma planta so, funciona. Com varias, **toda a frota cai na planta 1** — e o
agente nao tem sessao para perguntar.

## A correcao

Quem sabe a planta e quem gera o codigo. O administrador cria o codigo para
a filial X, distribui, e toda maquina registrada com ele nasce em X.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Ativo, Base, EquipamentoPendente, Planta, PlantaLocalidade
from app.services import agente_service as s

def _novo_banco():
    e = create_engine("sqlite://", future=True)
    Base.metadata.create_all(e)
    return sessionmaker(bind=e, future=True)()


def _payload(serial: str) -> dict:
    return {
        "serial": serial,
        "basico": {
            "hostname": "PC-" + serial,
            "so": "Windows 11 Pro",
            "cpu": "i5",
            "ram_gb": 8,
            "armazenamento_gb": 256,
            "fabricante": "Dell Inc.",
            "modelo": "OptiPlex",
        },
        "detalhes": {"rede": [{"mac": "AA:BB", "ips": ["10.0.0.9"]}]},
    }


class TestPlantaDoCodigo:
    def test_ativo_nasce_na_planta_do_codigo(self):
        db = _novo_banco()
        db.add(Planta(nome="Primeira", sigla="PRI", ativa=True))
        db.add(Planta(nome="Segunda", sigla="SEG", ativa=True))
        db.commit()

        segunda = db.query(Planta).filter(Planta.sigla == "SEG").one()

        _registro, valor = s.gerar_codigo(db, dias=7, usos_max=5, planta_id=segunda.id)

        r = s.registrar(db, codigo=valor, serial="SN-1", hostname="PC-1", payload=_payload("SN-1"))
        assert r["ok"] is True, r.get("motivo")

        from app.models.core import Ativo

        ativo = db.query(Ativo).filter(Ativo.numero_serie == "SN-1").one()
        assert ativo.planta_id == segunda.id, "nasceu na planta errada"
        db.close()

    def test_codigo_sem_planta_usa_a_primeira(self):
        """Compatibilidade: códigos antigos continuam funcionando."""
        db = _novo_banco()
        primeira = Planta(nome="Unica", sigla="UNI", ativa=True)
        db.add(primeira)
        db.commit()

        _registro, valor = s.gerar_codigo(db, dias=7, usos_max=5)

        r = s.registrar(db, codigo=valor, serial="SN-2", hostname="PC-2", payload=_payload("SN-2"))
        assert r["ok"] is True, r.get("motivo")

        from app.models.core import Ativo

        ativo = db.query(Ativo).filter(Ativo.numero_serie == "SN-2").one()
        assert ativo.planta_id == primeira.id
        db.close()


@pytest.mark.parametrize(("hostname", "sigla"), [
    ("DTAT0020", "TAT"), ("NTAT0020", "TAT"), ("RTAT0020", "TAT"),
    ("DMTZ0020", "MTZ"), ("NMTZ0020", "MTZ"), ("rmtz0020.empresa.local", "MTZ"),
])
def test_identifica_localidade_independente_do_prefixo(hostname, sigla):
    with _novo_banco() as db:
        tat = Planta(nome="Unidade TAT", sigla="U01", localidades_hostname=[PlantaLocalidade(codigo="TAT")])
        mtz = Planta(nome="Unidade MTZ", sigla="U02", localidades_hostname=[PlantaLocalidade(codigo="MTZ")])
        db.add_all([tat, mtz])
        db.commit()
        _, codigo = s.gerar_codigo(db)
        resultado = s.registrar(db, codigo=codigo, serial="SN-HOST", hostname=hostname, payload=_payload("SN-HOST"))
        assert resultado["ok"] is True, resultado
        assert db.get(Ativo, resultado["ativo_id"]).planta_id == {"TAT": tat.id, "MTZ": mtz.id}[sigla]


def test_host_sem_mapa_fica_pendente_e_vincula_na_proxima_tentativa():
    with _novo_banco() as db:
        planta = Planta(nome="Unidade", sigla="UNI", localidades_hostname=[PlantaLocalidade(codigo="MTZ")])
        db.add(planta)
        db.commit()
        registro, codigo = s.gerar_codigo(db)
        entrada = {"codigo": codigo, "serial": "SN-HOST", "hostname": "DTAT0020", "payload": _payload("SN-HOST")}
        assert s.registrar(db, **entrada)["motivo"] == "localidade_nao_cadastrada"
        pendencia = db.query(EquipamentoPendente).one()
        assert registro.usos_feitos == 0
        planta.localidades_hostname.append(PlantaLocalidade(codigo="TAT"))
        db.commit()
        resultado = s.registrar(db, **entrada)
        db.refresh(pendencia)
        assert resultado["ok"] is True
        assert pendencia.resolvido_em is not None
        assert pendencia.ativo_criado_id == resultado["ativo_id"]


def test_localidade_inativa_ou_incompativel_e_ativo_existente_preservado():
    with _novo_banco() as db:
        matriz = Planta(nome="Matriz", sigla="MAT")
        tat = Planta(nome="Unidade TAT", sigla="U01", ativa=False,
                    localidades_hostname=[PlantaLocalidade(codigo="TAT")])
        db.add_all([matriz, tat])
        db.commit()
        _, codigo = s.gerar_codigo(db, planta_id=matriz.id)
        entrada = {"codigo": codigo, "serial": "SN-HOST", "hostname": "DTAT0020", "payload": _payload("SN-HOST")}
        assert s.registrar(db, **entrada)["motivo"] == "localidade_inativa"
        tat.ativa = True
        db.commit()
        assert s.registrar(db, **entrada)["motivo"] == "localidade_conflitante"
        dados_legados = s.registrar(db, **{**entrada, "hostname": "LEGADO-01"})
        resultado = s.registrar(db, **entrada)
        assert resultado["ativo_id"] == dados_legados["ativo_id"]
        assert db.get(Ativo, resultado["ativo_id"]).planta_id == matriz.id
