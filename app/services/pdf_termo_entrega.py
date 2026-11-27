"""Renderização das páginas e composição do termo preenchido."""
from base64 import b64decode
from binascii import Error as Base64Error
from io import BytesIO
from threading import Lock

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from pypdfium2 import PdfDocument, PdfiumError
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

LIMITE_PDF = 8 * 1024 * 1024
_PDFIUM = Lock()
FONTES = {"classica": "Times-Italic", "inclinada": "Helvetica-Oblique", "manuscrita": "Courier-Oblique"}


def dimensoes_pdf(pdf: bytes) -> list[list[float]]:
    if not pdf.startswith(b"%PDF-") or len(pdf) > LIMITE_PDF:
        raise HTTPException(422, "Envie um PDF de até 8 MB.")
    with _PDFIUM:
        try:
            documento = PdfDocument(pdf)
            try:
                if not 1 <= len(documento) <= 12:
                    raise HTTPException(422, "O modelo deve ter de 1 a 12 páginas.")
                medidas = [list(documento.get_page_size(i)) for i in range(len(documento))]
                if any(not (144 <= w <= 1440 and 144 <= h <= 1440) for w, h in medidas):
                    raise HTTPException(422, "O PDF contém uma página fora das dimensões aceitas.")
                return medidas
            finally:
                documento.close()
        except PdfiumError as exc:
            raise HTTPException(422, "Não foi possível abrir o PDF. Confira se ele está protegido por senha.") from exc


def imagem_pagina(pdf: bytes, pagina: int, escala: float = 1.4) -> bytes:
    with _PDFIUM:
        try:
            documento = PdfDocument(pdf)
            try:
                imagem = documento[pagina - 1].render(scale=escala, draw_annots=False).to_pil().copy()
            finally:
                documento.close()
        except PdfiumError as exc:
            raise HTTPException(422, "Não foi possível renderizar uma página do termo.") from exc
    buffer = BytesIO()
    imagem.save(buffer, "PNG")
    return buffer.getvalue()


def normalizar_png(valor: str | None) -> bytes | None:
    if not valor:
        return None
    try:
        bruto = b64decode(valor, validate=True)
        with Image.open(BytesIO(bruto), formats=["PNG"]) as figura:
            if figura.width * figura.height > 2_000_000 or getattr(figura, "is_animated", False):
                raise ValueError
            png = figura.convert("RGBA")
            if png.getbbox() is None:
                raise ValueError
            png.thumbnail((1000, 480), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        png.save(buffer, "PNG")
        return buffer.getvalue()
    except (ValueError, Base64Error, Image.DecompressionBombError, UnidentifiedImageError, OSError):
        raise HTTPException(422, "Envie uma assinatura PNG estática com até 2 milhões de pixels.") from None


def gerar_pdf(modelo, respostas: dict, imagem: bytes | None, comprovante: dict) -> bytes:
    buffer = BytesIO()
    pdf = Canvas(buffer, pageCompression=1)
    pdf.setTitle("Termo de entrega")
    original = modelo.pdf
    for numero, (largura, altura) in enumerate(modelo.paginas, 1):
        pdf.setPageSize((largura, altura))
        pdf.drawImage(ImageReader(BytesIO(imagem_pagina(original, numero, escala=2))), 0, 0, largura, altura)
        pdf.setFillColorRGB(0.06, 0.16, 0.14)
        for campo in modelo.campos:
            if campo["pagina"] != numero:
                continue
            x = largura * campo["x"] / 100
            y = altura * (100 - campo["y"] - campo["altura"]) / 100
            w = largura * campo["largura"] / 100
            h = altura * campo["altura"] / 100
            if campo["tipo"] == "assinatura" and imagem:
                pdf.drawImage(ImageReader(BytesIO(imagem)), x, y, w, h, preserveAspectRatio=True, anchor="w", mask="auto")
                continue
            valor = respostas["campos"].get(campo["id"])
            texto = ("X" if valor is True else "") if campo["tipo"] == "leitura" else str(valor or "")
            fonte = FONTES[respostas["fonte"]] if campo["tipo"] == "assinatura" else "Helvetica"
            tamanho = min(h * 0.72, 22 if campo["tipo"] == "assinatura" else 13)
            tamanho = min(tamanho, max(1, w - 2) / max(1, stringWidth(texto, fonte, 1)))
            pdf.setFont(fonte, tamanho)
            pdf.drawString(x + 1, y + max(0.5, (h - tamanho) / 2), texto)
        pdf.showPage()

    pdf.setPageSize((595, 842))
    pdf.setFillColorRGB(0.06, 0.16, 0.14)
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(45, 780, "Comprovante do termo de entrega")
    y = 742
    for rotulo, valor in [
        ("Documento", str(comprovante["termo_id"])),
        ("Colaborador", comprovante["colaborador"]),
        ("E-mail confirmado", comprovante["destinatario"]),
        ("Identidade no AD", comprovante["login_ad"]),
        ("Patrimônio ou número de série", comprovante["equipamento"]),
        ("Aceite registrado em (UTC)", comprovante["aceite_em"]),
        ("Confirmação pelo agente", comprovante.get("confirmacao_agente", "Não exigida pela política deste termo")),
        ("Hash do aceite (SHA-256)", comprovante["hash_aceite"]),
        ("Selo de integridade do Nexus", comprovante["selo"]),
    ]:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(45, y, rotulo)
        pdf.setFont("Helvetica", min(11, 505 / max(1, stringWidth(valor, "Helvetica", 1))))
        pdf.drawString(45, y - 17, valor)
        y -= 46
    pdf.setFont("Helvetica", 9)
    pdf.drawString(45, y - 8, "Comprovante interno de aceite eletrônico do Nexus.")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
