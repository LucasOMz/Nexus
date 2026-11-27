"""Gera o favicon e os ícones do PWA a partir da marca da barra lateral."""
from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "frontend" / "icons"

TAMANHOS = {
    "favicon-32.png": 32,
    "favicon-64.png": 64,
    "icon-192.png": 192,
    "icon-512.png": 512,
    "logo-256.png": 256,
}


def main() -> int:
    marca = ElementTree.parse(DESTINO / "marca.svg").getroot()[0]
    pontos = [tuple(map(int, par.split(","))) for par in marca.attrib["points"].split()]
    verde = marca.attrib["fill"]
    lado = 2048
    fundo = "#112a22"
    quadrada = Image.new("RGBA", (lado, lado))
    desenho = [(round(lado * (0.17 + x * 0.0066)), round(lado * (0.22 + y * 0.0056))) for x, y in pontos]
    pincel = ImageDraw.Draw(quadrada)
    pincel.rounded_rectangle((0, 0, lado - 1, lado - 1), radius=lado // 5, fill=fundo)
    pincel.polygon(desenho, fill=verde)
    maskable = Image.new("RGB", (lado, lado), fundo)
    desenho_maskable = [(round(lado * (0.23 + x * 0.0054)), round(lado * (0.27 + y * 0.0046))) for x, y in pontos]
    ImageDraw.Draw(maskable).polygon(desenho_maskable, fill=verde)

    for nome, px in TAMANHOS.items():
        # LANCZOS: o redutor de melhor qualidade. Em icones pequenos a
        # diferenca para o padrao e visivel nas bordas.
        redimensionada = quadrada.resize((px, px), Image.LANCZOS)
        caminho = DESTINO / nome
        redimensionada.save(caminho, format="PNG", optimize=True)
        print(f"  {nome:<18} {px}x{px}  {caminho.stat().st_size / 1024:.1f} KB")
    maskable.resize((512, 512), Image.LANCZOS).save(DESTINO / "icon-maskable.png", optimize=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
