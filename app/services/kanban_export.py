"""Exportação das atividades do Kanban para PDF e CSV.

## O que se exporta, e por quê

O Kanban serve para acompanhar o trabalho; o PDF serve para **prestar contas** —
é o que vai anexado num relatório mensal, o que o gestor assina. Por isso o
padrão é conservador: só o essencial, e o resto só se pedido.

## Filtros

* **período** — por `prazo` (quando vence) ou por `concluida_em` (quando saiu)
* **bucket** — uma coluna específica
* **situação** — concluídas, abertas ou todas

## Campos opcionais

Descrição, responsáveis, checklist, prazo e prioridade são opcionais porque
cada um aumenta a largura da linha. Um PDF com tudo vira ilegível; um PDF com
título e data cabe numa página por 40 atividades.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from datetime import date, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Colunas possíveis, na ordem em que aparecem. `True` = pedida pelo cliente.
CAMPOS = ("descricao", "responsaveis", "checklist", "prazo", "prioridade")


def aplicar_filtros(
    consulta,
    *,
    de: date | None = None,
    ate: date | None = None,
    bucket_id: int | None = None,
    status: str = "todas",
    por: str = "prazo",
):
    """Refina a consulta de atividades.

    ## Por que `por` importa

    "Atividades do mês" é ambíguo: pode ser o que **vence** no mês ou o que foi
    **concluído** no mês. As duas listas são diferentes, e escolher a errada
    produz um relatório que parece certo e está errado.
    """
    from app.models.kanban import Atividade

    if bucket_id is not None:
        consulta = consulta.filter(Atividade.bucket_id == bucket_id)

    coluna = Atividade.concluida_em if por == "conclusao" else Atividade.prazo

    if de is not None:
        consulta = consulta.filter(coluna >= de)
    if ate is not None:
        consulta = consulta.filter(coluna <= ate)

    if status == "concluidas":
        consulta = consulta.filter(Atividade.concluida_em.isnot(None))
    elif status == "abertas":
        consulta = consulta.filter(Atividade.concluida_em.is_(None))

    return consulta


def _fmt_data(valor) -> str:
    if not valor:
        return ""
    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")
    return str(valor)[:10]


def _fmt_data_hora(valor) -> str:
    if not valor:
        return ""
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    return str(valor)


def _rotulo_situacao(a) -> str:
    return "Concluída" if a.concluida_em else "Aberta"


def _responsaveis(a, nomes: dict[int, str]) -> str:
    """Nomes dos responsáveis, pelo mapa `usuario_id -> nome`.

    `AtividadeResponsavel` guarda só o id: não há relação ORM para `Usuario`,
    e carregar um a um seria uma consulta por atividade.
    """
    return ", ".join(
        nomes[r.usuario_id] for r in (a.responsaveis or []) if r.usuario_id in nomes
    )


def _itens(a) -> tuple[int, int]:
    itens = a.itens or []
    return sum(1 for i in itens if i.feito), len(itens)


# ---------------------------------------------------------------- CSV
def para_csv(
    atividades: Iterable, campos: set[str], nomes: dict[int, str] | None = None
) -> bytes:
    """Planilha para análise — separador `;` e BOM, para abrir no Excel em pt-BR."""
    nomes = nomes or {}
    buf = io.StringIO()
    escritor = csv.writer(buf, delimiter=";", lineterminator="\r\n")

    cabecalho = ["ID", "Título", "Coluna", "Situação"]
    if "prazo" in campos:
        cabecalho += ["Prazo", "Atrasada"]
    if "prioridade" in campos:
        cabecalho.append("Prioridade")
    if "responsaveis" in campos:
        cabecalho.append("Responsáveis")
    if "checklist" in campos:
        cabecalho.append("Checklist")
    if "descricao" in campos:
        cabecalho.append("Descrição")
    cabecalho.append("Concluída em")

    escritor.writerow(cabecalho)

    hoje = date.today()
    for a in atividades:
        linha = [a.id, a.titulo, a.bucket.nome if a.bucket else "", _rotulo_situacao(a)]

        if "prazo" in campos:
            atrasada = bool(a.prazo and not a.concluida_em and a.prazo < hoje)
            linha += [_fmt_data(a.prazo), "sim" if atrasada else "não"]
        if "prioridade" in campos:
            linha.append(getattr(a.prioridade, "value", a.prioridade) or "")
        if "responsaveis" in campos:
            linha.append(_responsaveis(a, nomes))
        if "checklist" in campos:
            feito, total = _itens(a)
            linha.append(f"{feito}/{total}" if total else "")
        if "descricao" in campos:
            linha.append((a.descricao or "").replace("\n", " ").strip())

        linha.append(_fmt_data_hora(a.concluida_em))
        escritor.writerow(linha)

    # BOM: sem ele, o Excel em português abre "Concluída" como "ConcluÃ­da".
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------- PDF
def para_pdf(
    atividades: Iterable,
    campos: set[str],
    *,
    titulo: str,
    periodo: str,
    filtros: str,
    nomes: dict[int, str] | None = None,
) -> bytes:
    """Relatório em A4 paisagem — cabeçalho, resumo e a tabela."""
    nomes = nomes or {}
    itens = list(atividades)
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=titulo,
    )

    estilos = getSampleStyleSheet()
    titulo_estilo = estilos["Title"]
    titulo_estilo.fontSize = 16
    corpo = estilos["BodyText"]
    corpo.fontSize = 9
    corpo.leading = 12

    concluidas = sum(1 for a in itens if a.concluida_em)
    hoje = date.today()
    atrasadas = sum(
        1 for a in itens if a.prazo and not a.concluida_em and a.prazo < hoje
    )

    historia = [
        Paragraph(titulo, titulo_estilo),
        Spacer(1, 3 * mm),
        Paragraph(
            f"<b>Período:</b> {periodo} &nbsp;&nbsp; "
            f"<b>Filtros:</b> {filtros or 'nenhum'} &nbsp;&nbsp; "
            f"<b>Gerado em:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            corpo,
        ),
        Spacer(1, 2 * mm),
        Paragraph(
            f"<b>{len(itens)}</b> atividade(s) — "
            f"{concluidas} concluída(s), {len(itens) - concluidas} aberta(s), "
            f"{atrasadas} atrasada(s)",
            corpo,
        ),
        Spacer(1, 5 * mm),
    ]

    # Colunas proporcionais: título é o que ocupa espaço.
    cabecalho = ["#", "Título", "Coluna", "Situação"]
    larguras = [10 * mm, 0, 34 * mm, 22 * mm]

    if "prazo" in campos:
        cabecalho.append("Prazo")
        larguras.append(22 * mm)
    if "prioridade" in campos:
        cabecalho.append("Prioridade")
        larguras.append(20 * mm)
    if "responsaveis" in campos:
        cabecalho.append("Responsáveis")
        larguras.append(38 * mm)
    if "checklist" in campos:
        cabecalho.append("Checklist")
        larguras.append(18 * mm)
    if "descricao" in campos:
        cabecalho.append("Descrição")
        larguras.append(52 * mm)

    largura_util = A4[0] - 24 * mm
    larguras[1] = largura_util - sum(larguras) + larguras[1]

    linhas = [cabecalho]
    for n, a in enumerate(itens, start=1):
        linha = [
            str(n),
            Paragraph(a.titulo or "", corpo),
            a.bucket.nome if a.bucket else "",
            _rotulo_situacao(a),
        ]

        if "prazo" in campos:
            linha.append(_fmt_data(a.prazo))
        if "prioridade" in campos:
            linha.append(getattr(a.prioridade, "value", a.prioridade) or "")
        if "responsaveis" in campos:
            linha.append(Paragraph(_responsaveis(a, nomes), corpo))
        if "checklist" in campos:
            feito, total = _itens(a)
            linha.append(f"{feito}/{total}" if total else "")
        if "descricao" in campos:
            linha.append(Paragraph((a.descricao or "")[:300], corpo))

        linhas.append(linha)

    tabela = Table(linhas, colWidths=larguras, repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B8C4D0")),
        # Zebra: sem ela, 40 linhas de texto viram um bloco só.
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5F8")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    historia.append(tabela)
    doc.build(historia)

    return buf.getvalue()
