"""Filtros personalizados no relatório de gráficos.

## O que estes testes existem para pegar

Um filtro que vale em **alguns** blocos e não em outros é pior do que nenhum:
os números parecem filtrados e não são. É o tipo de falha que não aparece como
erro — aparece como decisão tomada em cima de número errado.

Por isso há dois níveis de verificação:

1. **Na fonte** — nenhuma consulta de ativo fora de `_condicoes()`.
2. **No comportamento** — com um filtro que reduz o conjunto, TODOS os blocos
   reduzem junto.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from app.core.security import create_access_token, hash_password
from app.database import get_db
from app.main import app
from app.models.contrato import Contrato
from app.models.core import (
    Ativo,
    Categoria,
    Departamento,
    Localizacao,
    Manutencao,
    Movimentacao,
    Planta,
    Produto,
    Usuario,
)
from app.models.enums import FormaAquisicao, TipoContrato

FONTE = Path(__file__).resolve().parent.parent / "app" / "routers" / "graficos.py"


def _db(client):
    return next(app.dependency_overrides[get_db]())


def _planta(db, sigla):
    p = Planta(nome=f"Planta {sigla}", sigla=sigla)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _ativo(db, planta_id, patrimonio, dominio="ti", **campos):
    a = Ativo(dominio=dominio, tipo_item="ativo", patrimonio=patrimonio, numero_serie=f"NS-{patrimonio}",
              planta_id=planta_id, status="estoque", **campos)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _graficos(client, headers, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    r = client.get(f"/api/v1/relatorios/graficos{('?' + q) if q else ''}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _operador(db, planta_id, *, inventarios=None):
    usuario = Usuario(
        nome="Operador", email="operador@relatorio.test", senha_hash=hash_password("teste123"),
        papel="ti", ativo=True, planta_id=planta_id,
        permissoes={"inventarios": inventarios} if inventarios is not None else {},
    )
    db.add(usuario)
    db.commit()
    token = create_access_token(usuario.id, "ti", usuario.email)
    return {"Authorization": f"Bearer {token}"}


class TestEscopoDosRelatorios:
    def test_csv_e_pdf_usam_planta_e_inventario_autorizados(self, client, auth_headers, monkeypatch):
        from app.routers import relatorios

        db = _db(client)
        a, b = _planta(db, "AAA"), _planta(db, "BBB")
        validade = date.today() + timedelta(days=10)
        local = _ativo(db, a.id, "ESCOPO-A", data_garantia=validade)
        externo = _ativo(db, b.id, "ESCOPO-B", data_garantia=validade)
        impressora = _ativo(db, a.id, "ESCOPO-IMP", dominio="impressora", data_garantia=validade)
        headers = _operador(db, a.id, inventarios=["ti"])
        for ativo in (local, externo, impressora):
            db.add(Movimentacao(ativo_id=ativo.id, tipo="atribuicao", destino_usuario_id=1))
            db.add(Manutencao(ativo_id=ativo.id))
        db.commit()

        for relatorio in ("inventario", "ativos-por-usuario", "movimentacoes", "manutencoes", "garantias"):
            url = f"/api/v1/relatorios/{relatorio}"
            csv_local = client.get(url, headers=headers)
            assert csv_local.status_code == 200, csv_local.text
            assert "ESCOPO-A" in csv_local.text
            assert "ESCOPO-B" not in csv_local.text
            assert "ESCOPO-IMP" not in csv_local.text
            admin_b = {**auth_headers, "X-Planta-Id": str(b.id)}
            csv_b = client.get(url, headers=admin_b)
            assert csv_b.status_code == 200, csv_b.text
            assert "ESCOPO-B" in csv_b.text
            assert "ESCOPO-A" not in csv_b.text
            assert "ESCOPO-B" in client.get(url, headers=auth_headers).text

        gerador = relatorios.build_relatorio_pdf

        def verificar_linhas(titulo, colunas, linhas, subtitulo):
            assert [linha[0] for linha in linhas] == ["ESCOPO-A"]
            return gerador(titulo, colunas, linhas, subtitulo)

        monkeypatch.setattr(relatorios, "build_relatorio_pdf", verificar_linhas)
        pdf = client.get("/api/v1/relatorios/inventario?formato=pdf", headers=headers)
        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF")
        impressoras = client.get("/api/v1/relatorios/inventario?dominio=impressora", headers=headers)
        assert impressoras.status_code == 403

    def test_graficos_e_estoque_global_respeitam_escopo(self, client, auth_headers):
        db = _db(client)
        a, b = _planta(db, "AAA"), _planta(db, "BBB")
        local = _ativo(db, a.id, "LOCAL")
        externo = _ativo(db, b.id, "EXTERNO")
        produto = Produto(nome="Consumível compartilhado", sku="GLOBAL", dominio="ti", estoque_minimo=2)
        db.add(produto)
        db.flush()
        db.add_all([
            Movimentacao(ativo_id=local.id, tipo="entrada"),
            Movimentacao(ativo_id=externo.id, tipo="entrada"),
            Movimentacao(produto_id=produto.id, tipo="entrada"),
        ])
        db.commit()
        headers = _operador(db, a.id)

        local = _graficos(client, headers)
        consolidado = _graficos(client, auth_headers)
        assert sum(item["valor"] for item in local["status"]) == 1
        assert sum(item["entradas"] for item in local["movimentacoes_mes"]) == 1
        assert sum(item["entradas"] for item in consolidado["movimentacoes_mes"]) == 3
        resposta = client.get("/api/v1/relatorios/graficos", params={"planta_id": b.id}, headers=headers)
        assert resposta.status_code == 403

        estoque = "/api/v1/relatorios/consumiveis-minimo"
        assert client.get(estoque, headers=headers).status_code == 403
        assert "GLOBAL" in client.get(estoque, headers=auth_headers).text

    def test_usuario_sem_planta_nao_recebe_relatorio(self, client):
        headers = _operador(_db(client), None)
        for caminho in ("inventario", "graficos", "consumiveis-minimo"):
            assert client.get(f"/api/v1/relatorios/{caminho}", headers=headers).status_code == 400

    def test_exportacao_de_etiquetas_respeita_a_planta(self, client):
        db = _db(client)
        a, b = _planta(db, "AAA"), _planta(db, "BBB")
        local = _ativo(db, a.id, "LOCAL")
        externo = _ativo(db, b.id, "EXTERNO")
        headers = _operador(db, a.id)

        assert client.get(f"/api/v1/print/etiqueta/{externo.id}.pdf", headers=headers).status_code == 404
        assert client.get(f"/api/v1/print/etiqueta/{local.id}.pdf", headers=headers).status_code == 200
        lote = client.get("/api/v1/print/etiquetas.pdf", params={"ids": f"{local.id},{externo.id}"}, headers=headers)
        assert lote.status_code == 200
        assert "LOCAL" in lote.headers["content-disposition"]


class TestGuardaNaFonte:
    """O que impediu a falha de voltar. Sem isto, um bloco novo nasce sem
    filtro e ninguém percebe."""

    def test_nenhuma_consulta_de_ativo_fora_do_helper(self):
        fonte = FONTE.read_text(encoding="utf-8")
        i = fonte.find("def _condicoes")
        j = fonte.find("@router.get")
        assert i > 0 and j > i, "não achei o helper nem o endpoint"

        resto = fonte[:i] + fonte[j:]
        assert "Ativo.dominio ==" not in resto, (
            "Há consulta de ativo filtrando o domínio por conta própria — "
            "ela ignora os filtros personalizados."
        )
        assert "Ativo.deleted_at.is_(None)" not in resto, (
            "Há consulta de ativo filtrando deleted_at por conta própria — "
            "use _condicoes()."
        )

    def test_o_helper_nao_se_autodestroi(self):
        """A ordem invertida é o que impede uma substituição textual de
        transformar a linha em `cond = [*cond]`.

        Procura a ATRIBUIÇÃO, não o texto solto: o docstring do helper cita
        `[*cond]` justamente para explicar por que ele não pode acontecer.
        """
        fonte = FONTE.read_text(encoding="utf-8")
        assert "cond = [Ativo.dominio == dominio, Ativo.deleted_at.is_(None)]" in fonte
        assert "cond = [*cond]" not in fonte
        assert "cond = [ Ativo" not in fonte


class TestFiltroValeEmTodosOsBlocos:
    """O teste que distingue filtro completo de filtro parcial."""

    def _dois_parques(self, client):
        db = _db(client)
        pa = _planta(db, "AAA")
        pb = _planta(db, "BBB")
        cat = Categoria(nome="Notebook")
        db.add(cat)
        db.commit()
        loc = Localizacao(nome="Sala 1")
        dep = Departamento(nome="TI")
        db.add_all([loc, dep])
        db.commit()

        # Planta AAA: 2 ativos. Planta BBB: 5 ativos.
        for i in range(2):
            _ativo(db, pa.id, f"AAA-{i}", categoria_id=cat.id,
                   localizacao_id=loc.id, departamento_id=dep.id,
                   valor=Decimal("1000.00"))
        for i in range(5):
            _ativo(db, pb.id, f"BBB-{i}", categoria_id=cat.id,
                   localizacao_id=loc.id, departamento_id=dep.id,
                   valor=Decimal("1000.00"))
        return pa.id

    def _soma(self, serie):
        return sum(x["valor"] for x in serie)

    def test_sem_filtro_conta_tudo(self, client, auth_headers):
        self._dois_parques(client)
        g = _graficos(client, auth_headers)
        assert self._soma(g["status"]) == 7
        assert self._soma(g["categoria"]) == 7
        assert self._soma(g["localizacao"]) == 7
        assert self._soma(g["departamento"]) == 7

    def test_o_filtro_de_planta_reduz_TODOS_os_blocos(self, client, auth_headers):
        """Se um bloco ignorar o filtro, ele continua com 7 e o teste acusa."""
        planta_aaa = self._dois_parques(client)

        g = _graficos(client, auth_headers, planta_id=planta_aaa)

        assert self._soma(g["status"]) == 2, "status ignorou o filtro"
        assert self._soma(g["categoria"]) == 2, "categoria ignorou o filtro"
        assert self._soma(g["localizacao"]) == 2, "localizacao ignorou o filtro"
        assert self._soma(g["departamento"]) == 2, "departamento ignorou o filtro"
        assert self._soma(g["valor_categoria"]) == 2000.0, "valor ignorou o filtro"

    def test_o_parque_respeita_o_filtro(self, client, auth_headers):
        db = _db(client)
        pa = _planta(db, "AAA")
        pb = _planta(db, "BBB")
        _ativo(db, pa.id, "A-1", forma_aquisicao=FormaAquisicao.LOCADO)
        for i in range(3):
            _ativo(db, pb.id, f"B-{i}", forma_aquisicao=FormaAquisicao.LOCADO)

        g = _graficos(client, auth_headers, planta_id=pa.id)
        assert g["parque"]["locados"] == 1

    def test_filtro_de_forma_de_aquisicao(self, client, auth_headers):
        db = _db(client)
        planta = _planta(db, "AAA")
        # A categoria importa: o gráfico "por categoria" faz outerjoin, e ativo
        # sem categoria simplesmente não aparece nele — o que está certo, mas
        # faria este teste medir outra coisa.
        cat = Categoria(nome="Notebook")
        db.add(cat)
        db.commit()

        _ativo(db, planta.id, "C-1", forma_aquisicao=FormaAquisicao.COMPRADO,
               valor=Decimal("5000.00"), categoria_id=cat.id)
        _ativo(db, planta.id, "L-1", forma_aquisicao=FormaAquisicao.LOCADO,
               categoria_id=cat.id)
        _ativo(db, planta.id, "L-2", forma_aquisicao=FormaAquisicao.LOCADO,
               categoria_id=cat.id)

        g = _graficos(client, auth_headers, forma_aquisicao="locado")
        assert self._soma(g["status"]) == 2, "status ignorou a forma"
        assert self._soma(g["categoria"]) == 2, "categoria ignorou a forma"
        assert self._soma(g["valor_categoria"]) == 0, "locado não tem valor de compra"

    def test_filtro_de_periodo(self, client, auth_headers):
        db = _db(client)
        planta = _planta(db, "AAA")
        _ativo(db, planta.id, "ANTIGO", data_aquisicao=date(2020, 1, 1))
        _ativo(db, planta.id, "NOVO", data_aquisicao=date(2025, 1, 1))

        g = _graficos(client, auth_headers, inicio="2024-01-01")
        assert self._soma(g["status"]) == 1

        g2 = _graficos(client, auth_headers, inicio="2024-01-01", fim="2025-12-31")
        assert self._soma(g2["status"]) == 1

        g3 = _graficos(client, auth_headers, fim="2021-01-01")
        assert self._soma(g3["status"]) == 1

    def test_filtro_de_contrato(self, client, auth_headers):
        db = _db(client)
        planta = _planta(db, "AAA")
        c = Contrato(numero="CT-1", tipo=TipoContrato.LOCACAO,
                     inicio=date(2024, 1, 1), valor_mensal=Decimal("1000.00"))
        db.add(c)
        db.commit()
        db.refresh(c)

        _ativo(db, planta.id, "NO-CONTRATO", forma_aquisicao=FormaAquisicao.LOCADO,
               contrato_id=c.id)
        _ativo(db, planta.id, "FORA", forma_aquisicao=FormaAquisicao.LOCADO)

        g = _graficos(client, auth_headers, contrato_id=c.id)
        assert self._soma(g["status"]) == 1

    def test_o_custo_do_contrato_usa_o_recorte(self, client, auth_headers):
        """O custo por equipamento é do RECORTE, não do contrato inteiro."""
        db = _db(client)
        planta = _planta(db, "AAA")
        c = Contrato(numero="CT-2", tipo=TipoContrato.LOCACAO,
                     inicio=date(2024, 1, 1), valor_mensal=Decimal("1000.00"))
        db.add(c)
        db.commit()
        db.refresh(c)

        _ativo(db, planta.id, "TI-1", forma_aquisicao=FormaAquisicao.LOCADO, contrato_id=c.id)
        _ativo(db, planta.id, "IMP-1", dominio="impressora",
               forma_aquisicao=FormaAquisicao.LOCADO, contrato_id=c.id)

        g = _graficos(client, auth_headers, dominio="ti", contrato_id=c.id)
        linha = g["parque"]["top_contratos"][0]
        # 1000 / 1 ativo de TI no recorte — e não / 2 (o contrato inteiro).
        assert linha["por_ativo"] == 1000.0

    def test_filtro_que_nao_casa_esvazia_tudo(self, client, auth_headers):
        """O caso extremo: se TODOS os blocos respeitam, todos zeram juntos."""
        self._dois_parques(client)
        g = _graficos(client, auth_headers, inicio="2099-01-01")
        assert g["status"] == []
        assert g["categoria"] == []
        assert g["localizacao"] == []
        assert g["departamento"] == []
        assert g["parque"]["comprados"] == 0
        assert g["parque"]["custo_mensal"] == 0.0


class TestNaoQuebrouOAntigo:
    def test_os_blocos_antigos_continuam_vindo(self, client, auth_headers):
        _db(client)
        g = _graficos(client, auth_headers)
        for chave in ("status", "categoria", "localizacao", "departamento",
                      "valor_categoria", "garantias", "movimentacoes_mes",
                      "manutencoes_status", "parque", "extra"):
            assert chave in g, f"sumiu o bloco {chave}"

    def test_sem_filtro_o_parque_e_igual_ao_de_antes(self, client, auth_headers):
        db = _db(client)
        planta = _planta(db, "AAA")
        _ativo(db, planta.id, "C-1", forma_aquisicao=FormaAquisicao.COMPRADO,
               valor=Decimal("5000.00"))
        _ativo(db, planta.id, "L-1", forma_aquisicao=FormaAquisicao.LOCADO)

        g = _graficos(client, auth_headers)
        assert g["parque"]["comprados"] == 1
        assert g["parque"]["locados"] == 1
        assert g["parque"]["valor_patrimonial"] == 5000.0

    def test_garantias_ainda_funciona(self, client, auth_headers):
        """O bloco 6 parte de `base` — que agora carrega as condições."""
        db = _db(client)
        planta = _planta(db, "AAA")
        _ativo(db, planta.id, "G-1", data_garantia=date.today())
        g = _graficos(client, auth_headers)
        assert len(g["garantias"]) == 3
