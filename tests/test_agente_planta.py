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

import logging
import warnings

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Planta
from app.services import agente_service as s

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)


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
