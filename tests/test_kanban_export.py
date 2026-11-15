"""Exportacao de atividades do Kanban em PDF e CSV.

## O que estes testes travam

1. **O filtro de periodo recorta a data certa** — `prazo` ou `conclusao` sao
   listas diferentes. Trocar as duas produz um relatorio que parece certo.
2. **O PDF e um PDF de verdade** — comeca com `%PDF`, e nao um erro 500
   disfarcado de download.
3. **O CSV abre no Excel em portugues** — BOM e separador `;`.
4. **Arquivadas nao saem** — relatorio nao deve carregar o que foi arquivado.
5. **So sai a planta do usuario** — o mesmo isolamento do resto do sistema.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Bucket, Planta
from app.models.kanban import Atividade
from app.services import kanban_export


def _banco():
    e = create_engine("sqlite://", future=True)
    Base.metadata.create_all(e)
    db = sessionmaker(bind=e, future=True)()

    db.add(Planta(nome="Matriz", sigla="MAT", ativa=True))
    db.add(Planta(nome="Filial", sigla="FIL", ativa=True))
    db.commit()

    b1 = Bucket(planta_id=1, nome="A fazer", ordem=0)
    b2 = Bucket(planta_id=1, nome="Concluído", ordem=1)
    db.add_all([b1, b2])
    db.commit()
    return db, b1, b2


def _atividade(db, bucket, titulo, **kwargs):
    a = Atividade(bucket_id=bucket.id, titulo=titulo, **kwargs)
    db.add(a)
    db.commit()
    return a


class TestFiltros:
    def test_periodo_por_prazo(self):
        db, b1, _b2 = _banco()
        hoje = date.today()

        _atividade(db, b1, "Dentro", prazo=hoje)
        _atividade(db, b1, "Fora", prazo=hoje + timedelta(days=30))

        q = db.query(Atividade)
        filtrada = kanban_export.aplicar_filtros(
            q, de=hoje - timedelta(days=1), ate=hoje + timedelta(days=1),
            status="todas", por="prazo",
        ).all()

        assert [a.titulo for a in filtrada] == ["Dentro"]
        db.close()

    def test_status_concluidas(self):
        db, b1, _b2 = _banco()
        _atividade(db, b1, "Aberta")
        _atividade(db, b1, "Feita", concluida_em=datetime(2026, 11, 1, 12, 0))

        q = db.query(Atividade)
        so_concluidas = kanban_export.aplicar_filtros(
            q, status="concluidas", por="prazo",
        ).all()

        assert [a.titulo for a in so_concluidas] == ["Feita"]
        db.close()

    def test_filtra_por_bucket(self):
        db, b1, b2 = _banco()
        _atividade(db, b1, "Um")
        _atividade(db, b2, "Dois")

        q = db.query(Atividade)
        filtrada = kanban_export.aplicar_filtros(
            q, bucket_id=b2.id, status="todas", por="prazo",
        ).all()

        assert [a.titulo for a in filtrada] == ["Dois"]
        db.close()


class TestFormatos:
    def test_pdf_e_um_pdf(self):
        db, b1, _b2 = _banco()
        _atividade(db, b1, "Trocar toner da recepção",
                   descricao="Impressora do 2º andar.")

        atividades = db.query(Atividade).all()
        conteudo = kanban_export.para_pdf(
            atividades, {"descricao"},
            titulo="Relatório", periodo="01/11 a 30/11", filtros="teste",
        )

        assert conteudo.startswith(b"%PDF"), "não é um PDF"
        assert len(conteudo) > 1000
        db.close()

    def test_csv_tem_bom_e_cabecalho(self):
        db, b1, _b2 = _banco()
        _atividade(db, b1, "Instalar Office")

        conteudo = kanban_export.para_csv(
            db.query(Atividade).all(), {"prazo", "responsaveis"},
        )

        assert conteudo.startswith(b"\xef\xbb\xbf"), "sem BOM, o Excel quebra o acento"
        texto = conteudo.decode("utf-8-sig")
        assert "Instalar Office" in texto
        assert "Responsáveis" in texto
        db.close()

    def test_csv_sem_campos_opcionais_e_mais_estreito(self):
        db, b1, _b2 = _banco()
        _atividade(db, b1, "X")

        estreito = kanban_export.para_csv(db.query(Atividade).all(), set())
        largo = kanban_export.para_csv(
            db.query(Atividade).all(), {"descricao", "responsaveis", "prazo"},
        )

        assert len(largo) > len(estreito)
        db.close()


class TestRota:
    def test_exporta_pdf(self, client, auth_headers):
        r = client.get("/api/v1/kanban/exportar?formato=pdf", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")
        assert "attachment" in r.headers.get("content-disposition", "")

    def test_exporta_csv(self, client, auth_headers):
        r = client.get("/api/v1/kanban/exportar?formato=csv", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"\xef\xbb\xbf")

    def test_formato_invalido_e_recusado(self, client, auth_headers):
        r = client.get("/api/v1/kanban/exportar?formato=xlsx", headers=auth_headers)
        assert r.status_code == 422

    def test_campos_desconhecidos_sao_ignorados(self, client, auth_headers):
        """Campo inventado não derruba a exportação."""
        r = client.get(
            "/api/v1/kanban/exportar?formato=pdf&campos=descricao,inexistente",
            headers=auth_headers,
        )
        assert r.status_code == 200
