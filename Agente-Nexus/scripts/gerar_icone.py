"""Gera o icone do agente a partir do logo Nexus.

## O bug que a primeira versao tinha

O SVG tem viewBox `-50 -30 1396 1276`, mas a letra ocupa apenas
`x 206..1088` — ela **nao esta no centro do arquivo**, esta deslocada para a
esquerda. O anel, por outro lado, esta centrado em `648`.

Desenhando as duas coisas pelo mesmo `esc`, a letra saia a esquerda e o anel
no meio: no Windows parecia **dois desenhos soltos**, exatamente o que
apareceu na tela.

Agora cada parte e centralizada no proprio canvas, mantendo a proporcao
interna. O anel continua inclinado -24 graus, como no SVG.

## Por que desenhar em vez de converter

Tentei `svglib` (interpreta o SVG de verdade). Ele falha neste arquivo:
o parser nao resolve os `path` com `Q` e o anel eliptico, e devolve
`pdfPath = None`.

Sem renderizador que aceite o formato, o desenho replica a geometria —
proporcoes, angulo e gradientes tirados do proprio arquivo.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "installer" / "nexus.ico"
PNG = RAIZ / "installer" / "nexus-256.png"

TAM = 256
MARGEM = 0.78

# Cores do logo-nexus.svg
LETRA = ("#53F52C", "#08BC48", "#005B40")
ANEL_TRAS = ("#21DD37", "#008343", "#16C942")
ANEL_FRENTE = ("#8CFC42", "#21E83B", "#C2FF55")


def _cor(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def gradiente(c1, c2, c3):
    """Gradiente vertical em tres paradas, como no SVG."""
    a, b, c = _cor(c1), _cor(c2), _cor(c3)
    saida = []
    for y in range(TAM):
        t = y / (TAM - 1)
        if t < 0.4:
            u, p, q = t / 0.4, a, b
        else:
            u, p, q = (t - 0.4) / 0.6, b, c
        saida.append(tuple(int(p[k] + (q[k] - p[k]) * u) for k in range(3)))
    return saida


def tingir(mascara, cores):
    """Aplica o gradiente na area desenhada."""
    faixa = Image.new("RGBA", (1, TAM))
    for y in range(TAM):
        faixa.putpixel((0, y), cores[y] + (255,))
    faixa = faixa.resize(mascara.size)
    saida = Image.new("RGBA", mascara.size, (0, 0, 0, 0))
    saida.paste(faixa, (0, 0), mascara)
    return saida


def letra_n():
    """O "N" do SVG, centralizado no canvas."""
    mascara = Image.new("RGBA", (TAM, TAM), (0, 0, 0, 0))
    d = ImageDraw.Draw(mascara)

    # A letra mede 882 x 889 no SVG.
    util = TAM * MARGEM
    larg_total = util * (882 / 1396.0)
    alt_total = util * (889 / 1276.0)

    x0 = (TAM - larg_total) / 2
    y0 = (TAM - alt_total) / 2
    x1 = x0 + larg_total
    y1 = y0 + alt_total

    # Haste: 254 de largura no SVG (460-206).
    larg = max(5, larg_total * (254 / 882.0))
    raio = larg / 2

    branco = (255, 255, 255, 255)

    # duas hastes
    d.rounded_rectangle([x0, y0, x0 + larg, y1], radius=raio, fill=branco)
    d.rounded_rectangle([x1 - larg, y0, x1, y1], radius=raio, fill=branco)

    # diagonal, da base da esquerda ao topo da direita
    d.line([(x0 + raio, y0 + raio * 1.4), (x1 - raio, y1 - raio * 1.4)],
           fill=branco, width=int(larg))
    for px, py in ((x0 + raio, y0 + raio * 1.4), (x1 - raio, y1 - raio * 1.4)):
        d.ellipse([px - raio, py - raio, px + raio, py + raio], fill=branco)

    return mascara


def anel(cores, frente):
    """Anel eliptico inclinado -24 graus, centrado no canvas."""
    grande = TAM * 4
    mascara = Image.new("RGBA", (grande, grande), (0, 0, 0, 0))
    d = ImageDraw.Draw(mascara)

    cx = cy = grande // 2
    # ## A escala e a do TAM, nao a do canvas grande
    #
    # O canvas grande existe so para girar sem cortar. Usar a escala dele
    # fazia o anel ficar 4x maior que o recorte final — e ele aparecia como
    # dois arcos soltos nos cantos.
    util = TAM * MARGEM
    rx = util * (655 / 1396.0)
    ry = util * (206 / 1276.0)
    esp = max(3, int(util * (44 / 1396.0)))

    caixa = [cx - rx, cy - ry, cx + rx, cy + ry]

    if frente:
        # Meio arco: e o que atravessa a letra, como no SVG.
        d.arc(caixa, start=10, end=170, fill=(255, 255, 255, 255), width=esp)
    else:
        d.ellipse(caixa, outline=(255, 255, 255, 255), width=esp)

    # ## O sinal importa
    #
    # O SVG usa rotate(-24), que em SVG significa ANTI-horario.
    # No Pillow, angulo positivo e anti-horario — o sinal e invertido.
    # Usar -24 aqui inclinava o anel para o lado errado.
    mascara = mascara.rotate(24, resample=Image.BICUBIC, center=(cx, cy))
    meio = (grande - TAM) // 2
    mascara = mascara.crop((meio, meio, meio + TAM, meio + TAM))
    return tingir(mascara, gradiente(*cores))


def gerar():
    base = Image.new("RGBA", (TAM, TAM), (0, 0, 0, 0))

    base.alpha_composite(anel(ANEL_TRAS, False))
    base.alpha_composite(tingir(letra_n(), gradiente(*LETRA)))
    base.alpha_composite(anel(ANEL_FRENTE, True))

    base.save(PNG)
    base.save(DESTINO, sizes=[
        (16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48),
        (64, 64), (96, 96), (128, 128), (256, 256),
    ])
    return DESTINO


if __name__ == "__main__":
    print("  icone gerado:", gerar())
