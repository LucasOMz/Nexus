"""Limites e validação dos arquivos de mídia recebidos pela API."""
from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, ImageSequence
from starlette.datastructures import Headers
from starlette.formparsers import MultiPartException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MIB = 1024 * 1024
MAX_FOTO = 12 * MIB
MAX_PLANTA = 12 * MIB
MAX_PRINT = 8 * MIB
MAX_ANEXO = 20 * MIB
MAX_PIXELS = 30_000_000

_ROTAS = (
    (re.compile(r"/api/v1/admin/fotos"), MAX_FOTO),
    (re.compile(r"/api/v1/reportes"), MAX_PRINT),
    (re.compile(r"/api/v1/mapas/[^/]+/imagem"), MAX_PLANTA),
    (re.compile(r"/api/v1/manutencoes/[^/]+/anexos"), MAX_ANEXO),
    (re.compile(r"/api/v1/admin/termo-entrega(?:/previa)?"), 8 * MIB),
    (re.compile(r"/api/v1/termo-entrega/assinar"), MIB),
)
MIME_IMAGENS = {
    "PNG": ("image/png", ".png"),
    "JPEG": ("image/jpeg", ".jpg"),
    "WEBP": ("image/webp", ".webp"),
    "GIF": ("image/gif", ".gif"),
}


def _mensagem_tamanho(limite: int) -> str:
    return f"Arquivo acima do limite de {limite // MIB} MB."


class LimiteDeUpload:
    """Limita o corpo antes e durante a leitura pelo parser de formulário."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT"}:
            await self.app(scope, receive, send)
            return
        caminho = scope["path"]
        raiz = scope.get("root_path", "").rstrip("/")
        if caminho.startswith(f"{raiz}/"):
            caminho = caminho[len(raiz):]
        caminho = caminho.rstrip("/")
        limite = next((n for rota, n in _ROTAS if rota.fullmatch(caminho)), None)
        if limite is None:
            await self.app(scope, receive, send)
            return

        # Espaço para cabeçalhos das partes e campos de texto do formulário.
        limite_corpo = limite + MIB
        total = 0
        excedeu = False
        tamanho = Headers(scope=scope).get("content-length", "").lstrip("0")
        if tamanho.isascii() and tamanho.isdecimal() and (len(tamanho) > 18 or int(tamanho) > limite_corpo):
            await JSONResponse({"detail": _mensagem_tamanho(limite)}, status_code=413)(scope, receive, send)
            return

        async def receber_limitado() -> Message:
            nonlocal total, excedeu
            mensagem = await receive()
            if mensagem["type"] == "http.request":
                total += len(mensagem.get("body", b""))
                if total > limite_corpo:
                    excedeu = True
                    # O parser fecha os arquivos temporários ao abortar o multipart.
                    raise MultiPartException(_mensagem_tamanho(limite))
            return mensagem

        async def enviar_resposta(mensagem: Message) -> None:
            if excedeu and mensagem["type"] == "http.response.start":
                # O parser converte a exceção de multipart em erro de formulário.
                mensagem = {**mensagem, "status": 413}
            await send(mensagem)

        await self.app(scope, receber_limitado, enviar_resposta)


def ler_arquivo(arquivo: UploadFile, limite: int) -> bytes:
    conteudo = arquivo.file.read(limite + 1)
    if len(conteudo) > limite:
        raise HTTPException(413, _mensagem_tamanho(limite))
    if not conteudo:
        raise HTTPException(400, "O arquivo está vazio.")
    return conteudo


@dataclass(frozen=True)
class ImagemValidada:
    mime: str
    extensao: str
    largura: int
    altura: int


def validar_imagem(
    conteudo: bytes, *, formatos: tuple[str, ...] = tuple(MIME_IMAGENS), status_invalido: int = 400,
) -> ImagemValidada:
    try:
        with Image.open(BytesIO(conteudo), formats=list(formatos)) as imagem:
            largura, altura = imagem.size
            if max(largura, altura) > 20_000 or largura * altura > MAX_PIXELS:
                raise HTTPException(status_invalido, "A imagem excede o limite de dimensões.")
            mime, extensao = MIME_IMAGENS[imagem.format]
            imagem.verify()
        # verify() não decodifica os pixels. A segunda leitura valida os quadros
        # e limita o trabalho necessário para verificar imagens animadas.
        with Image.open(BytesIO(conteudo), formats=list(formatos)) as imagem:
            for numero, quadro in enumerate(ImageSequence.Iterator(imagem), start=1):
                if numero > 120 or numero * largura * altura > 2 * MAX_PIXELS:
                    raise HTTPException(status_invalido, "A imagem animada excede o limite de quadros ou pixels.")
                quadro.load()
    except (EOFError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        tipos = ", ".join("JPG" if tipo == "JPEG" else tipo for tipo in formatos)
        raise HTTPException(status_invalido, f"Envie uma imagem válida em {tipos}.") from exc
    return ImagemValidada(mime, extensao, largura, altura)


def _pdf_valido(conteudo: bytes) -> bool:
    if not re.match(rb"%PDF-(?:1\.[0-7]|2\.0)[\r\n]", conteudo):
        return False
    final = re.search(rb"startxref\s+(\d{1,10})\s+%%EOF\s*\Z", conteudo[-4096:])
    if final is None:
        return False
    indice = int(final[1])
    trecho = conteudo[indice:indice + 4096]
    # O índice pode apontar para uma tabela clássica ou para um stream XRef.
    return bool(re.match(rb"xref\s+\d+\s+\d+", trecho) or (
        re.match(rb"\d+\s+\d+\s+obj\b", trecho)
        and re.search(rb"/Type\s*/XRef\b", trecho.split(b"stream", 1)[0])
    ))


def validar_anexo(conteudo: bytes, nome: str) -> tuple[str, str]:
    if conteudo.startswith(b"%PDF-") or Path(nome).suffix.lower() == ".pdf":
        if not _pdf_valido(conteudo):
            raise HTTPException(400, "O anexo PDF está inválido ou incompleto.")
        return "application/pdf", ".pdf"
    if Path(nome).suffix.lower() == ".txt":
        try:
            conteudo.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(400, "O anexo TXT precisa estar em UTF-8.") from exc
        if re.search(rb"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", conteudo):
            raise HTTPException(400, "O anexo TXT contém dados binários.")
        return "text/plain", ".txt"
    imagem = validar_imagem(conteudo)
    return imagem.mime, imagem.extensao
