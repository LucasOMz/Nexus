"""Relatório de custo mensal por contrato (passo: exportação).

## Por que existe

O custo de locação **não aparece** no financeiro tradicional: não é
patrimônio, não deprecia e não tem valor de compra. Sem esta planilha, a
gestão não tem como conferir a fatura do fornecedor contra o que o sistema
acha que está contratado.

O CSV responde "quanto eu pago por mês, e por quê".
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.database import get_db
from app.main import app
from app.models.contrato import Contrato
from app.models.core import Ativo, Planta
from app.models.enums import FormaAquisicao, TipoContrato


def _db(client):
    return next(app.dependency_overrides[get_db]())


def _planta(db, sigla="TAT"):
    p = Planta(nome=f"Planta {sigla}", sigla=sigla)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _contrato(db, numero, mensal="8500.00", **campos):
    # `tipo` vem em `campos` quando o teste quer comodato; o default entra
    # por `setdefault` para não haver dois valores para o mesmo argumento.
    campos.setdefault("tipo", TipoContrato.LOCACAO)
    c = Contrato(
        numero=numero, inicio=date(2024, 1, 1),
        valor_mensal=Decimal(mensal) if mensal else None, **campos,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _csv(client, headers):
    r = client.get("/api/v1/financeiro/contratos.csv", headers=headers)
    assert r.status_code == 200, r.text
    return r, r.text


class TestRelatorioDeCustos:
    def test_responde_csv(self, client, auth_headers):
        r, texto = _csv(client, auth_headers)
        assert "text/csv" in r.headers["content-type"]
        assert "nexus-contratos.csv" in r.headers["content-disposition"]

    def test_tem_cabecalho(self, client, auth_headers):
        _, texto = _csv(client, auth_headers)
        cabeca = texto.splitlines()[0]
        for coluna in ("contrato", "valor_mensal", "rateio_por_equipamento", "custo_12_meses"):
            assert coluna in cabeca, f"faltou a coluna {coluna}"

    def test_comeca_com_bom_para_o_excel(self, client, auth_headers):
        """Sem o BOM, o Excel em português abre os acentos errado."""
        _, texto = _csv(client, auth_headers)
        assert texto.startswith("\ufeff")

    def test_lista_os_contratos(self, client, auth_headers):
        db = _db(client)
        _contrato(db, "CT-A")
        _contrato(db, "CT-B")
        _, texto = _csv(client, auth_headers)
        assert "CT-A" in texto
        assert "CT-B" in texto

    def test_calcula_o_rateio(self, client, auth_headers):
        db = _db(client)
        planta = _planta(db)
        c = _contrato(db, "RATEIO")
        for i in range(50):
            db.add(Ativo(dominio="ti", tipo_item="ativo", patrimonio=f"F-{i}",
                         planta_id=planta.id, status="estoque",
                         contrato_id=c.id, forma_aquisicao=FormaAquisicao.LOCADO))
        db.commit()

        _, texto = _csv(client, auth_headers)
        linha = [lin for lin in texto.splitlines() if "RATEIO" in lin][0]
        # 8500 / 50 = 170,00
        assert "170,00" in linha

    def test_usa_virgula_decimal_e_ponto_e_virgula(self, client, auth_headers):
        """Excel em português: `;` separa e `,` é o decimal."""
        db = _db(client)
        _contrato(db, "BR-1")
        _, texto = _csv(client, auth_headers)
        linha = [lin for lin in texto.splitlines() if "BR-1" in lin][0]
        assert ";" in linha
        assert "8500,00" in linha

    def test_contrato_sem_equipamento_nao_divide_por_zero(self, client, auth_headers):
        db = _db(client)
        _contrato(db, "VAZIO")
        r, texto = _csv(client, auth_headers)
        assert r.status_code == 200
        linha = [lin for lin in texto.splitlines() if "VAZIO" in lin][0]
        # A coluna de rateio fica vazia, e a linha existe.
        assert linha.count(";") >= 8

    def test_prazo_indeterminado_nao_quebra(self, client, auth_headers):
        db = _db(client)
        _contrato(db, "SEM-FIM", fim=None)
        r, _ = _csv(client, auth_headers)
        assert r.status_code == 200

    def test_comodato_sem_mensalidade_aparece_com_zero(self, client, auth_headers):
        db = _db(client)
        _contrato(db, "COMOD", mensal=None, tipo=TipoContrato.COMODATO)
        _, texto = _csv(client, auth_headers)
        linha = [lin for lin in texto.splitlines() if "COMOD" in lin][0]
        assert "0,00" in linha

    def test_contrato_encerrado_sai(self, client, auth_headers):
        from datetime import datetime, timezone

        db = _db(client)
        c = _contrato(db, "ENCERRADO")
        c.deleted_at = datetime.now(timezone.utc)
        db.commit()
        _, texto = _csv(client, auth_headers)
        assert "ENCERRADO" not in texto

    def test_exige_autenticacao(self, client):
        r = client.get("/api/v1/financeiro/contratos.csv")
        assert r.status_code == 401
