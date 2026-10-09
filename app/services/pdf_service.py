"""Geração de PDFs: Termo de Responsabilidade e Relatórios.

O Termo é gerado com hash SHA-256 do próprio PDF para garantir integridade
(critério de aceite "Termo PDF com hash de integridade").
"""
from __future__ import annotations

import hashlib
import io
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_termo_pdf(
    patrimonio: str,
    modelo: str,
    dominio: str,
    colaborador_nome: str,
    colaborador_email: str,
    departamento: str,
) -> tuple[bytes, str]:
    """Gera o PDF do Termo de Responsabilidade e devolve (bytes, hash_sha256)."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=25 * mm, leftMargin=25 * mm, topMargin=25 * mm, bottomMargin=25 * mm)
    styles = getSampleStyleSheet()
    title = styles["Title"]
    body = styles["BodyText"]
    body.fontSize = 11
    body.leading = 15

    story = [
        Paragraph("Termo de Responsabilidade — Equipamento", title),
        Spacer(1, 6 * mm),
        Paragraph(
            f"<b>Data:</b> {datetime.now().strftime('%d/%m/%Y %H:%M')}<br/>"
            f"<b>Domínio:</b> {dominio}<br/>"
            f"<b>Patrimônio:</b> {patrimonio}<br/>"
            f"<b>Equipamento:</b> {modelo or '—'}",
            body,
        ),
        Spacer(1, 6 * mm),
        Paragraph(
            "Declaro que recebi o equipamento acima identificado em perfeitas condições de uso, "
            "comprometendo-me a utilizá-lo exclusivamente para as atividades da empresa, zelando "
            "pela sua conservação e comunicando imediatamente qualquer defeito, extravio ou dano.",
            body,
        ),
        Spacer(1, 6 * mm),
        Paragraph(
            f"<b>Colaborador:</b> {colaborador_nome}<br/>"
            f"<b>E-mail:</b> {colaborador_email}<br/>"
            f"<b>Departamento:</b> {departamento or '—'}",
            body,
        ),
        Spacer(1, 18 * mm),
        Paragraph("_________________________________________", body),
        Paragraph("Assinatura do Colaborador", body),
    ]
    doc.build(story)
    data = buf.getvalue()
    return data, _sha256(data)


def build_relatorio_pdf(
    titulo: str,
    headers: Sequence[str],
    rows: Iterable[Sequence[Any]],
    subtitulo: str = "",
) -> bytes:
    """Gera um relatório tabular em PDF."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=15 * mm, leftMargin=15 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
    styles = getSampleStyleSheet()
    story = [Paragraph(titulo, styles["Title"])]
    if subtitulo:
        story.append(Paragraph(subtitulo, styles["Normal"]))
    story.append(Spacer(1, 6 * mm))

    data = [list(headers)] + [[str(c) if c is not None else "" for c in row] for row in rows]
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#6750A4")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CAC4D0")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F4F0FA")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    return buf.getvalue()
