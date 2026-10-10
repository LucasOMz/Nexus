"""Gera os icones do Nexus a partir de Nexus.png.

Le a imagem da raiz e escreve os tamanhos que o site usa:
  frontend/icons/favicon-32.png     aba do navegador
  frontend/icons/favicon-64.png     atalho de alta densidade
  frontend/icons/icon-192.png       PWA (Android)
  frontend/icons/icon-512.png       PWA (tela de instalacao / iOS)
  frontend/icons/logo-256.png       tela do assistente de instalacao
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
ORIGEM = RAIZ / "Nexus.png"
DESTINO = RAIZ / "frontend" / "icons"

TAMANHOS = {
    "favicon-32.png": 32,
    "favicon-64.png": 64,
    "icon-192.png": 192,
    "icon-512.png": 512,
    "logo-256.png": 256,
}


def main() -> int:
    if not ORIGEM.exists():
        print(f"  ! nao encontrei {ORIGEM}")
        return 1

    img = Image.open(io.BytesIO(ORIGEM.read_bytes()))
    print(f"  origem: {img.size[0]}x{img.size[1]} px, modo {img.mode}")

    # Quadrada e com alfa: os icones sao recortados em circulo no Android e
    # em quadrado arredondado no iOS. Sem isto, a imagem esticaria.
    lado = max(img.size)
    quadrada = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    quadrada.paste(img.convert("RGBA"), ((lado - img.size[0]) // 2, (lado - img.size[1]) // 2))

    DESTINO.mkdir(parents=True, exist_ok=True)
    for nome, px in TAMANHOS.items():
        # LANCZOS: o redutor de melhor qualidade. Em icones pequenos a
        # diferenca para o padrao e visivel nas bordas.
        redimensionada = quadrada.resize((px, px), Image.LANCZOS)
        caminho = DESTINO / nome
        redimensionada.save(caminho, format="PNG", optimize=True)
        print(f"  {nome:<18} {px}x{px}  {caminho.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
