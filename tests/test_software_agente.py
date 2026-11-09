"""Coleta de software enviada pelo agente.

## O que estes testes travam

1. **Substituição, não acúmulo** — duas coletas seguidas deixam o estado da
   segunda, não a soma das duas. Sem isso, 3.000 máquinas × 150 programas
   viraria milhões de linhas em uma semana.
2. **Deduplicação** — o registro do Windows repete programas de 32 bits
   (`Wow6432Node`). Duas linhas iguais fariam o mesmo programa contar duas
   vezes na conformidade.
3. **Teto por máquina** — payload gigante é recusado, não gravado pela metade.
4. **Token obrigatório** — a rota é pública na rede, e só o agente escreve.
"""
from __future__ import annotations

import logging
import warnings

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Ativo, Base, Planta, SoftwareInstalado
from app.models.enums import Dominio, StatusAtivo, TipoItem
from app.services import software_agente

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)


def _banco():
    e = create_engine("sqlite://", future=True)
    Base.metadata.create_all(e)
    db = sessionmaker(bind=e, future=True)()
    db.add(Planta(nome="C", sigla="C", ativa=True))
    db.commit()
    a = Ativo(
        planta_id=1,
        dominio=Dominio.TI,
        tipo_item=TipoItem.ATIVO,
        status=StatusAtivo.ESTOQUE,
        numero_serie="SN-SW",
    )
    db.add(a)
    db.commit()
    return db, a


class TestColetaDeSoftware:
    def test_grava_a_lista(self):
        db, ativo = _banco()

        r = software_agente.registrar_software(db, ativo.id, [
            {"nome": "Google Chrome", "versao": "120.0", "fabricante": "Google LLC"},
            {"nome": "7-Zip", "versao": "23.01"},
        ])
        assert r["ok"] is True
        assert r["gravados"] == 2

        linhas = db.query(SoftwareInstalado).all()
        assert len(linhas) == 2
        assert {x.nome for x in linhas} == {"Google Chrome", "7-Zip"}
        db.close()

    def test_substitui_em_vez_de_acumular(self):
        """A segunda coleta define o estado — não soma."""
        db, ativo = _banco()

        software_agente.registrar_software(db, ativo.id, [
            {"nome": "Antigo", "versao": "1.0"},
        ])
        software_agente.registrar_software(db, ativo.id, [
            {"nome": "Novo", "versao": "2.0"},
        ])

        nomes = [x.nome for x in db.query(SoftwareInstalado).all()]
        assert nomes == ["Novo"], nomes
        db.close()

    def test_deduplica_nome_e_versao(self):
        """O registro repete entradas; a contagem não pode dobrar."""
        db, ativo = _banco()

        r = software_agente.registrar_software(db, ativo.id, [
            {"nome": "Chrome", "versao": "120"},
            {"nome": "chrome", "versao": "120"},
            {"nome": "CHROME", "versao": "120"},
        ])
        assert r["gravados"] == 1
        assert r["descartados"] == 2
        db.close()

    def test_versoes_diferentes_do_mesmo_programa(self):
        """Versão diferente é outra linha — é o que permite o drill-down."""
        db, ativo = _banco()

        software_agente.registrar_software(db, ativo.id, [
            {"nome": "Chrome", "versao": "119"},
            {"nome": "Chrome", "versao": "120"},
        ])
        assert db.query(SoftwareInstalado).count() == 2
        db.close()

    def test_recusa_item_sem_nome(self):
        db, ativo = _banco()

        r = software_agente.registrar_software(db, ativo.id, [
            {"versao": "1.0"},
            {"nome": "  ", "versao": "1.0"},
            {"nome": "Valido", "versao": "1.0"},
        ])
        assert r["gravados"] == 1
        assert r["descartados"] == 2
        db.close()

    def test_teto_por_maquina(self):
        """Payload maior que o teto é truncado, não gravado inteiro."""
        db, ativo = _banco()

        itens = [{"nome": f"Prog {i}", "versao": "1.0"} for i in range(900)]
        r = software_agente.registrar_software(db, ativo.id, itens)

        assert r["truncado"] is True
        assert r["gravados"] == software_agente.MAX_ITENS
        db.close()

    def test_lista_vazia_limpa_o_ativo(self):
        """Máquina que desinstalou tudo fica com zero — não com o anterior."""
        db, ativo = _banco()

        software_agente.registrar_software(db, ativo.id, [{"nome": "X", "versao": "1"}])
        r = software_agente.registrar_software(db, ativo.id, [])

        assert r["gravados"] == 0
        assert db.query(SoftwareInstalado).count() == 0
        db.close()

    def test_nao_apaga_o_que_veio_do_ocs(self):
        """Durante a migração os dois convivem; só o do agente é substituído."""
        db, ativo = _banco()

        db.add(SoftwareInstalado(
            ativo_id=ativo.id, nome="Do OCS", versao="1.0", origem="ocs",
        ))
        db.commit()

        software_agente.registrar_software(db, ativo.id, [{"nome": "Do agente", "versao": "1"}])

        nomes = {x.nome for x in db.query(SoftwareInstalado).all()}
        assert nomes == {"Do OCS", "Do agente"}, nomes
        db.close()


class TestRota:
    def test_exige_token(self, client):
        r = client.post("/api/v1/agente/software", json={"software": []})
        assert r.status_code == 401

    def test_token_invalido(self, client):
        r = client.post(
            "/api/v1/agente/software",
            headers={"Authorization": "Bearer nada-a-ver"},
            json={"software": []},
        )
        assert r.status_code == 401
