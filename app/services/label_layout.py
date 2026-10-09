"""Motor de layout de etiqueta.

A ideia central: **uma única geometria** é calculada a partir da configuração
(o "template") e dos dados do ativo. Dessa mesma geometria saem:

* `render_pdf`  → PDF (impressão manual / pré-visualização fiel)
* `render_zpl`  → comando ZPL (Zebra)
* `render_tspl` → comando TSPL (TSC/Elgin)
* `layout["elementos"]` → enviado ao frontend, que desenha a pré-visualização

Assim o que você vê na tela é a mesma conta que gera a etiqueta impressa —
inclusive os avisos de texto que não cabe.

Unidades: tudo em **milímetros**. A conversão para dots (ZPL/TSPL) usa o DPI
configurado, que é o ponto que mais causa etiqueta saindo no tamanho errado.
"""
from __future__ import annotations

import io
from typing import Any

# Campos que podem ser exibidos na etiqueta (chave -> rótulo).
CAMPOS_DISPONIVEIS: dict[str, str] = {
    "patrimonio": "Patrimônio",
    "codigo": "Código da etiqueta",
    "serie": "Nº de série",
    "modelo": "Modelo",
    "marca": "Marca",
    "categoria": "Categoria",
    "status": "Status",
    "departamento": "Departamento",
    "localizacao": "Localização",
    "valor": "Valor",
    "garantia": "Garantia",
    "hostname": "Hostname",
    "ip": "IP",
    "mac": "MAC",
    "so": "Sistema operacional",
    "ram": "Memória RAM",
    "contador": "Contador de páginas",
    "dominio": "Inventário",
}

CONFIG_PADRAO: dict[str, Any] = {
    # O que aparece
    "campos": ["modelo", "serie"],
    "titulo": "",
    "rodape": "",
    "prefixo_patrimonio": "",
    "mostrar_patrimonio": True,
    "mostrar_patrimonio_negrito": True,
    # QR
    "mostrar_qr": True,
    "qr_tamanho_mm": 36.0,
    "qr_ecc": "M",
    "qr_posicao": "esquerda",  # esquerda | direita
    # Texto
    "alinhamento": "left",  # left | center | right
    "fonte_mm": 4.0,
    "fonte_escala_secundaria": 0.62,
    "espacamento_mm": 1.2,
    "margem_mm": 3.0,
    # Impressora
    "densidade": 0,   # ^MD (ZPL)
    "velocidade": 2,  # ^PR (ZPL)
    # Moldura
    "borda": False,
}

# Largura média de caractere em relação à altura da fonte (Helvetica/Arial).
_FATOR_LARGURA_CHAR = 0.55


def normalizar_config(config: dict | None) -> dict[str, Any]:
    """Combina a configuração recebida com o padrão, validando os tipos."""
    cfg = dict(CONFIG_PADRAO)
    for chave, valor in (config or {}).items():
        if valor is not None:
            cfg[chave] = valor

    # Sanidade: campos válidos, na ordem informada.
    campos = [c for c in (cfg.get("campos") or []) if c in CAMPOS_DISPONIVEIS]
    cfg["campos"] = campos
    cfg["largura_mm"] = float(cfg.get("largura_mm") or 100.0)
    cfg["altura_mm"] = float(cfg.get("altura_mm") or 50.0)
    cfg["dpi"] = int(cfg.get("dpi") or 203)
    cfg["qr_tamanho_mm"] = float(cfg.get("qr_tamanho_mm") or 36.0)
    cfg["fonte_mm"] = float(cfg.get("fonte_mm") or 4.0)
    cfg["margem_mm"] = float(cfg.get("margem_mm") or 3.0)
    cfg["espacamento_mm"] = float(cfg.get("espacamento_mm") or 1.2)
    cfg["fonte_escala_secundaria"] = float(cfg.get("fonte_escala_secundaria") or 0.62)
    if cfg.get("qr_ecc") not in ("L", "M", "Q", "H"):
        cfg["qr_ecc"] = "M"
    if cfg.get("qr_posicao") not in ("esquerda", "direita"):
        cfg["qr_posicao"] = "esquerda"
    if cfg.get("alinhamento") not in ("left", "center", "right"):
        cfg["alinhamento"] = "left"
    return cfg


def _largura_texto_mm(texto: str, altura_mm: float) -> float:
    """Estimativa de largura do texto (suficiente para alinhar e avisar)."""
    return len(texto) * altura_mm * _FATOR_LARGURA_CHAR


def _quebrar_em_linhas(texto: str, altura_mm: float, largura_disponivel_mm: float, max_linhas: int = 2) -> list[str]:
    """Quebra o texto em linhas que cabem na largura (quebra por palavra)."""
    if _largura_texto_mm(texto, altura_mm) <= largura_disponivel_mm:
        return [texto]
    palavras = texto.split()
    linhas: list[str] = []
    atual = ""
    for palavra in palavras:
        teste = f"{atual} {palavra}".strip()
        if _largura_texto_mm(teste, altura_mm) <= largura_disponivel_mm or not atual:
            atual = teste
        else:
            linhas.append(atual)
            atual = palavra
            if len(linhas) >= max_linhas:
                break
    if atual and len(linhas) < max_linhas:
        linhas.append(atual)
    return linhas[:max_linhas] or [texto]


def montar_layout(config: dict, dados: dict[str, str]) -> dict[str, Any]:
    """Calcula a geometria da etiqueta (elementos posicionados em mm)."""
    largura = config["largura_mm"]
    altura = config["altura_mm"]
    margem = config["margem_mm"]
    fonte = config["fonte_mm"]
    fonte_sec = max(1.6, fonte * config["fonte_escala_secundaria"])
    espaco = config["espacamento_mm"]
    avisos: list[str] = []
    elementos: list[dict[str, Any]] = []

    tem_qr = bool(config.get("mostrar_qr")) and bool(dados.get("payload_qr"))
    qr_lado = min(config["qr_tamanho_mm"], altura - 2 * margem, largura * 0.6) if tem_qr else 0.0

    # Coluna de texto: à direita ou à esquerda do QR.
    if tem_qr:
        if config["qr_posicao"] == "esquerda":
            qr_x = margem
            texto_x = margem + qr_lado + 3.0
            texto_largura = largura - texto_x - margem
        else:
            qr_x = largura - margem - qr_lado
            texto_x = margem
            texto_largura = qr_x - 3.0 - margem
    else:
        qr_x = 0.0
        texto_x = margem
        texto_largura = largura - 2 * margem

    if texto_largura < 8:
        avisos.append("A área de texto ficou muito estreita: reduza o tamanho do QR ou aumente a etiqueta.")

    # --- QR ---
    if tem_qr:
        if qr_lado < 10:
            avisos.append("O QR está menor que 10 mm — leitores podem ter dificuldade.")
        elementos.append({
            "tipo": "qr",
            "x_mm": round(qr_x, 2),
            "y_mm": round((altura - qr_lado) / 2, 2),
            "tamanho_mm": round(qr_lado, 2),
            "ecc": config["qr_ecc"],
            "payload": dados["payload_qr"],
        })

    # --- Linhas de texto ---
    linhas: list[dict[str, Any]] = []
    if config.get("titulo"):
        linhas.append({"texto": str(config["titulo"]), "altura_mm": fonte_sec, "negrito": True, "tipo_linha": "titulo"})
    if config.get("mostrar_patrimonio") and dados.get("patrimonio"):
        prefixo = config.get("prefixo_patrimonio") or ""
        linhas.append({
            "texto": f"{prefixo}{dados['patrimonio']}",
            "altura_mm": fonte,
            "negrito": bool(config.get("mostrar_patrimonio_negrito", True)),
            "tipo_linha": "patrimonio",
        })
    for chave in config["campos"]:
        valor = (dados.get(chave) or "").strip()
        if not valor:
            continue
        rotulo = CAMPOS_DISPONIVEIS.get(chave, chave)
        linhas.append({"texto": f"{rotulo}: {valor}", "altura_mm": fonte_sec, "negrito": False, "tipo_linha": chave})
    if config.get("rodape"):
        linhas.append({"texto": str(config["rodape"]), "altura_mm": fonte_sec * 0.85, "negrito": False, "tipo_linha": "rodape"})

    # Distribui verticalmente, quebrando linhas longas.
    expandidas: list[dict[str, Any]] = []
    for linha in linhas:
        for parte in _quebrar_em_linhas(linha["texto"], linha["altura_mm"], texto_largura):
            expandidas.append({**linha, "texto": parte})

    altura_total = sum(item["altura_mm"] + espaco for item in expandidas)
    y = margem + max(0.0, (altura - 2 * margem - altura_total) / 2)

    for linha in expandidas:
        altura_linha = linha["altura_mm"]
        largura_linha = _largura_texto_mm(linha["texto"], altura_linha)
        if largura_linha > texto_largura + 0.5:
            avisos.append(f"O texto \"{linha['texto'][:32]}\" pode não caber na largura da etiqueta.")
        if config["alinhamento"] == "center":
            x = texto_x + max(0.0, (texto_largura - largura_linha) / 2)
        elif config["alinhamento"] == "right":
            x = texto_x + max(0.0, texto_largura - largura_linha)
        else:
            x = texto_x
        elementos.append({
            "tipo": "texto",
            "x_mm": round(x, 2),
            "y_mm": round(y, 2),
            "texto": linha["texto"],
            "altura_mm": round(altura_linha, 2),
            "largura_mm": round(largura_linha, 2),
            "negrito": linha["negrito"],
            "tipo_linha": linha["tipo_linha"],
        })
        y += altura_linha + espaco

    if y > altura - margem + 0.5:
        avisos.append("O conteúdo passou da altura da etiqueta: reduza a fonte ou as linhas exibidas.")

    if config.get("borda"):
        elementos.insert(0, {
            "tipo": "borda", "x_mm": round(margem / 2, 2), "y_mm": round(margem / 2, 2),
            "largura_mm": round(largura - margem, 2), "altura_mm": round(altura - margem, 2),
        })

    return {
        "largura_mm": largura,
        "altura_mm": altura,
        "dpi": config["dpi"],
        "elementos": elementos,
        "avisos": avisos,
        "config": config,
    }


# ---------------------------------------------------------------------------
# Renderizadores
# ---------------------------------------------------------------------------
def _mm_para_dots(mm: float, dpi: int) -> int:
    return max(0, int(round(mm * dpi / 25.4)))


def _sane(texto: str) -> str:
    """Remove caracteres que quebram os comandos ZPL/TSPL."""
    return "".join(ch if ch.isprintable() and ch not in '":^~\\' else " " for ch in (texto or ""))


def render_pdf(layout: dict, logo_bytes: bytes | None = None) -> bytes:
    """Etiqueta em PDF, no tamanho exato configurado (mm)."""
    from reportlab.lib.units import mm as mm_unit
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    from app.services.qr_service import qr_png_bytes

    largura = layout["largura_mm"] * mm_unit
    altura = layout["altura_mm"] * mm_unit
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(largura, altura))
    c.setTitle("Etiqueta")

    for el in layout["elementos"]:
        if el["tipo"] == "qr":
            img = io.BytesIO(qr_png_bytes(el["payload"], box_size=6, ecc=el.get("ecc", "M")))
            lado = el["tamanho_mm"] * mm_unit
            # PDF tem origem embaixo; a geometria usa origem no topo.
            c.drawImage(
                ImageReader(img),
                el["x_mm"] * mm_unit,
                altura - (el["y_mm"] * mm_unit) - lado,
                width=lado, height=lado,
            )
        elif el["tipo"] == "texto":
            fonte_pt = el["altura_mm"] * 2.83  # mm -> pontos
            c.setFont("Helvetica-Bold" if el["negrito"] else "Helvetica", fonte_pt)
            c.drawString(
                el["x_mm"] * mm_unit,
                altura - (el["y_mm"] * mm_unit) - (el["altura_mm"] * mm_unit),
                el["texto"],
            )
        elif el["tipo"] == "borda":
            c.setLineWidth(0.6)
            c.rect(
                el["x_mm"] * mm_unit,
                altura - (el["y_mm"] * mm_unit) - (el["altura_mm"] * mm_unit),
                el["largura_mm"] * mm_unit, el["altura_mm"] * mm_unit,
            )
    c.save()
    return buf.getvalue()


def render_zpl(layout: dict) -> bytes:
    """Comando ZPL (Zebra) a partir da geometria."""
    dpi = layout["dpi"]
    largura_dots = _mm_para_dots(layout["largura_mm"], dpi)
    altura_dots = _mm_para_dots(layout["altura_mm"], dpi)
    cfg = layout.get("config", {})

    partes = [
        "^XA",
        # Codificação UTF-8. O ZPL assume, por padrão, uma tabela de byte único
        # (^CI0): um "ç" enviado em UTF-8 (dois bytes) saía como dois caracteres
        # sem sentido na etiqueta. Com ^CI28 a impressora entende UTF-8 e os
        # acentos saem corretos.
        "^CI28",
        f"^PW{largura_dots}",
        f"^LL{altura_dots}",
        f"^MD{int(cfg.get('densidade', 0) or 0)}",
        f"^PR{int(cfg.get('velocidade', 2) or 2)}",
    ]
    for el in layout["elementos"]:
        if el["tipo"] == "qr":
            x = _mm_para_dots(el["x_mm"], dpi)
            y = _mm_para_dots(el["y_mm"], dpi)
            # Magnificação: 1 bloco do QR ~ 0.25 mm por nível de magnificação.
            mag = max(2, min(10, int(round(el["tamanho_mm"] / 5.0))))
            partes.append(f"^FO{x},{y}^BQN,2,{mag},Q,0^FDMA,{_sane(el['payload'])}^FS")
        elif el["tipo"] == "texto":
            x = _mm_para_dots(el["x_mm"], dpi)
            y = _mm_para_dots(el["y_mm"], dpi)
            h = max(8, _mm_para_dots(el["altura_mm"], dpi))
            fonte = "A0N" if not el["negrito"] else "A0B"
            partes.append(f"^FO{x},{y}^A{fonte},{h},{h}^FD{_sane(el['texto'])}^FS")
        elif el["tipo"] == "borda":
            x0 = _mm_para_dots(el["x_mm"], dpi)
            y0 = _mm_para_dots(el["y_mm"], dpi)
            w = _mm_para_dots(el["largura_mm"], dpi)
            h2 = _mm_para_dots(el["altura_mm"], dpi)
            t = max(1, _mm_para_dots(0.4, dpi))
            partes.append(f"^FO{x0},{y0}^GB{w},{h2},{t}^FS")
    partes.append("^XZ")
    return ("\n".join(partes) + "\n").encode("utf-8")


def render_tspl(layout: dict) -> bytes:
    """Comando TSPL (TSC/Elgin) a partir da geometria.

    Observação: os comandos de texto do TSPL usam fontes internas em dots, então
    o tamanho é aproximado por múltiplos da fonte base — ajuste fino deve ser
    feito na impressora. O QR e as posições são exatos.
    """
    dpi = layout["dpi"]
    altura_dots = _mm_para_dots(layout["altura_mm"], dpi)
    cfg = layout.get("config", {})
    partes = [
        f"SIZE {layout['largura_mm']:.2f} mm,{layout['altura_mm']:.2f} mm",
        "GAP 2 mm,0",
        "DIRECTION 1",
        # O TSPL também assume byte único por padrão. Sem declarar UTF-8, os
        # acentos saem trocados (mesmo problema do ^CI28 no ZPL).
        'CODEPAGE "UTF-8"',
        f"DENSITY {int(cfg.get('densidade', 0) or 0) + 8}",
        f"SPEED {int(cfg.get('velocidade', 2) or 2)}",
        "CLS",
    ]
    for el in layout["elementos"]:
        if el["tipo"] == "qr":
            x = _mm_para_dots(el["x_mm"], dpi)
            y = _mm_para_dots(el["y_mm"], dpi)
            celula = max(2, min(10, int(round(el["tamanho_mm"] / 5.0))))
            partes.append(f'QRCODE {x},{y},{el.get("ecc", "M")},{celula},A,0,M2,S7,"{_sane(el["payload"])}"')
        elif el["tipo"] == "texto":
            x = _mm_para_dots(el["x_mm"], dpi)
            y = _mm_para_dots(el["y_mm"], dpi)
            multiplo = max(1, int(round(el["altura_mm"] / 1.5)))
            fonte = "3" if el["negrito"] else "2"
            partes.append(f'TEXT {x},{y},"{fonte}",0,1,{multiplo},"{_sane(el["texto"])}"')
        elif el["tipo"] == "borda":
            x0 = _mm_para_dots(el["x_mm"], dpi)
            y0 = _mm_para_dots(el["y_mm"], dpi)
            w = _mm_para_dots(el["largura_mm"], dpi)
            h2 = _mm_para_dots(el["altura_mm"], dpi)
            partes.append(f"BOX {x0},{y0},{x0 + w},{min(y0 + h2, altura_dots)},2")
    partes.append("PRINT 1,1")
    return ("\n".join(partes) + "\n").encode("utf-8")
