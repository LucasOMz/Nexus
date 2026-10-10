"""A migração automática funciona numa instalação que JÁ existe.

## Por que este teste existe

O sistema não usa migração manual: `init_db()` faz `create_all` (tabelas
novas) e `_adicionar_colunas_faltantes` (colunas novas em tabelas que já
existiam). É o que permite atualizar o sistema sem apagar o banco.

Se isso falhar, a instalação de quem já usa o sistema **não sobe** — e é o
tipo de erro que só aparece em produção, onde o banco tem dado de verdade.

Aqui se simula o banco ANTES desta mudança, roda o `init_db` e confere que as
colunas novas entraram e o dado antigo continua lá.
"""
from __future__ import annotations

import sqlite3

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.models import Base

# Esquema MÍNIMO de antes da locação: só o que o teste precisa para provar
# que os campos novos entram e que a linha existente sobrevive.
ATIVOS_ANTIGO = """
CREATE TABLE ativos (
    id INTEGER PRIMARY KEY,
    dominio VARCHAR(30) NOT NULL,
    tipo_item VARCHAR(30) NOT NULL,
    patrimonio VARCHAR(80) NOT NULL UNIQUE,
    status VARCHAR(30) NOT NULL,
    valor NUMERIC(14, 2),
    created_at DATETIME,
    updated_at DATETIME
)
"""


def _banco_antigo(tmp_path):
    """Cria um SQLite com o esquema anterior e uma linha dentro."""
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.executescript(ATIVOS_ANTIGO)
    con.execute(
        "INSERT INTO ativos (id, dominio, tipo_item, patrimonio, status, valor) "
        "VALUES (1, 'ti', 'ativo', 'LEGADO-001', 'estoque', 4500.00)"
    )
    con.commit()
    con.close()
    return caminho


class TestMigracaoAutomatica:
    def test_colunas_novas_entram_no_ativo(self, tmp_path):
        from app.database import _adicionar_colunas_faltantes

        caminho = _banco_antigo(tmp_path)
        eng = create_engine(f"sqlite:///{caminho}")

        antes = {c["name"] for c in inspect(eng).get_columns("ativos")}
        assert "forma_aquisicao" not in antes, "o teste precisa partir do esquema antigo"

        # `Base.metadata` conhece `ativos` com os campos novos; é o mesmo
        # caminho que o `init_db` usa numa atualização de verdade.
        _adicionar_colunas_faltantes(eng)

        depois = {c["name"] for c in inspect(eng).get_columns("ativos")}
        assert "forma_aquisicao" in depois
        assert "contrato_id" in depois
        assert "valor_residual" in depois

    def test_o_dado_antigo_sobrevive(self, tmp_path):
        """Atualizar o sistema não pode perder o inventário."""
        from app.database import _adicionar_colunas_faltantes

        caminho = _banco_antigo(tmp_path)
        eng = create_engine(f"sqlite:///{caminho}")
        _adicionar_colunas_faltantes(eng)

        with eng.connect() as con:
            linha = con.execute(
                text("SELECT patrimonio, valor FROM ativos WHERE id = 1")
            ).one()
        assert linha[0] == "LEGADO-001"
        assert float(linha[1]) == 4500.00

    def test_o_ativo_legado_vira_comprado(self, tmp_path):
        """O que já existia foi tratado como comprado — e deve continuar.

        Se o padrão fosse `locado`, todo o parque antigo mudaria de natureza
        no dia da atualização, e os números de patrimônio mudariam junto.
        """
        from app.database import _adicionar_colunas_faltantes

        caminho = _banco_antigo(tmp_path)
        eng = create_engine(f"sqlite:///{caminho}")
        _adicionar_colunas_faltantes(eng)

        with eng.connect() as con:
            valor = con.execute(
                text("SELECT forma_aquisicao FROM ativos WHERE id = 1")
            ).scalar()
        assert valor == "comprado"

    def test_a_tabela_de_contratos_e_criada(self, tmp_path):
        """`create_all` cria a tabela nova sem tocar nas que existem."""
        caminho = _banco_antigo(tmp_path)
        eng = create_engine(f"sqlite:///{caminho}")

        # Só as tabelas que já existem são preservadas; `create_all` ignora
        # as presentes e cria as ausentes.
        Base.metadata.create_all(bind=eng, checkfirst=True)

        nomes = set(inspect(eng).get_table_names())
        assert "contratos" in nomes
        assert "ativos" in nomes

    def test_roda_duas_vezes_sem_estourar(self, tmp_path):
        """Atualização repetida é o caso comum — o app sobe muitas vezes."""
        from app.database import _adicionar_colunas_faltantes

        caminho = _banco_antigo(tmp_path)
        eng = create_engine(f"sqlite:///{caminho}")
        _adicionar_colunas_faltantes(eng)
        _adicionar_colunas_faltantes(eng)   # não pode dar "duplicate column"

        colunas = [c["name"] for c in inspect(eng).get_columns("ativos")]
        assert colunas.count("forma_aquisicao") == 1


class TestContratoNaInstalacaoAntiga:
    def test_da_para_criar_contrato_e_vincular_legado(self, tmp_path):
        """O fluxo real: banco antigo, atualiza, e já dá para locar."""
        from datetime import date
        from decimal import Decimal

        from app.database import _adicionar_colunas_faltantes
        from app.models.contrato import Contrato
        from app.models.core import Ativo
        from app.models.enums import FormaAquisicao, TipoContrato

        caminho = _banco_antigo(tmp_path)
        eng = create_engine(f"sqlite:///{caminho}")
        Base.metadata.create_all(bind=eng, checkfirst=True)
        _adicionar_colunas_faltantes(eng)

        with Session(eng) as db:
            c = Contrato(numero="2025/001", tipo=TipoContrato.LOCACAO,
                         inicio=date(2025, 1, 1), valor_mensal=Decimal("1000.00"))
            db.add(c)
            db.commit()
            db.refresh(c)

            a = db.get(Ativo, 1)
            a.forma_aquisicao = FormaAquisicao.LOCADO
            a.contrato_id = c.id
            db.commit()
            db.refresh(c)

            assert c.valor_mensal_por_ativo == Decimal("1000.00")
