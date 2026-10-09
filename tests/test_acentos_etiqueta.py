"""Acentos na etiqueta térmica.

O ZPL e o TSPL assumem, por padrão, uma tabela de byte único. Enviando UTF-8
sem avisar, um "ç" (dois bytes) saía como dois caracteres sem sentido e a
etiqueta ficava ilegível.

A correção: declarar a codificação no próprio comando — `^CI28` no ZPL e
`CODEPAGE "UTF-8"` no TSPL.
"""
from __future__ import annotations

from app.services.label_layout import render_tspl, render_zpl

LAYOUT = {
    "dpi": 203,
    "largura_mm": 100,
    "altura_mm": 50,
    "config": {},
    "elementos": [
        {"tipo": "texto", "x_mm": 2, "y_mm": 2, "altura_mm": 4, "negrito": True,
         "texto": "Recepção — 3º andar"},
        {"tipo": "texto", "x_mm": 2, "y_mm": 10, "altura_mm": 3, "negrito": False,
         "texto": "Impressora térmica nº 1"},
    ],
}

ACENTOS = "çãoáéíóúâêôãõàçÁÉÍÓÚÂÊÔÃÕÀÇºª"


class TestCodificacaoDaEtiqueta:
    def test_zpl_declara_utf8(self):
        zpl = render_zpl(LAYOUT).decode("utf-8")
        assert "^CI28" in zpl, "sem ^CI28 a impressora lê os acentos errado"

    def test_tspl_declara_utf8(self):
        tspl = render_tspl(LAYOUT).decode("utf-8")
        assert 'CODEPAGE "UTF-8"' in tspl

    def test_a_declaracao_vem_antes_do_conteudo(self):
        """Precisa estar no cabeçalho: depois do primeiro texto já não vale."""
        linhas = render_zpl(LAYOUT).decode("utf-8").split("\n")
        pos_ci = next(i for i, linha in enumerate(linhas) if linha.startswith("^CI"))
        pos_texto = next(i for i, linha in enumerate(linhas) if "^FD" in linha)
        assert pos_ci < pos_texto

    def test_acentos_sobrevivem_como_utf8(self):
        """O texto acentuado precisa chegar codificado em UTF-8, não latin-1."""
        bruto = render_zpl(LAYOUT)
        assert "Recepção — 3º andar".encode("utf-8") in bruto
        # E não pode ter sido "achatado" para ASCII.
        assert b"Recepcao" not in bruto

    def test_todas_as_acentuacoes_passam(self):
        """Um texto com toda a acentuação do português não pode perder nada."""
        layout = dict(LAYOUT)
        layout["elementos"] = [{
            "tipo": "texto", "x_mm": 2, "y_mm": 2, "altura_mm": 3,
            "negrito": False, "texto": ACENTOS,
        }]
        zpl = render_zpl(layout)
        assert ACENTOS.encode("utf-8") in zpl

    def test_caracteres_de_comando_continuam_bloqueados(self):
        """A proteção contra injeção de comando não pode ter sido perdida."""
        layout = dict(LAYOUT)
        layout["elementos"] = [{
            "tipo": "texto", "x_mm": 0, "y_mm": 0, "altura_mm": 3,
            "negrito": False, "texto": 'a^FDquebra^FS"b',
        }]
        zpl = render_zpl(layout).decode("utf-8")
        # O ^ e as aspas do texto viraram espaço; só os comandos legítimos ficam.
        assert zpl.count("^FD") == 1


class TestEtiquetaDeTeste:
    """O texto de teste precisa ter acentos — é como se confere a impressora."""

    def test_texto_de_teste_tem_acentos(self):
        from app.routers.print import _dados_exemplo

        dados = _dados_exemplo()
        juntos = " ".join(str(v) for v in dados.values() if v)
        assert any(c in juntos for c in "çãoºª"), "a etiqueta de teste deveria ter acentos"

    def test_etiqueta_de_teste_e_gerada_em_utf8(self):
        """O texto do teste, montado numa etiqueta real, sai em UTF-8."""
        from app.routers.print import _dados_exemplo

        dados = _dados_exemplo()
        layout = dict(LAYOUT)
        layout["elementos"] = [
            {"tipo": "texto", "x_mm": 2, "y_mm": 2, "altura_mm": 4,
             "negrito": True, "texto": str(dados.get("modelo") or "")},
            {"tipo": "texto", "x_mm": 2, "y_mm": 10, "altura_mm": 4,
             "negrito": False, "texto": str(dados.get("marca") or "")},
        ]
        zpl = render_zpl(layout)
        assert b"^CI28" in zpl
        # "Recepção" e "térmica" em UTF-8, byte a byte — a prova do acento certo.
        assert b"Recep\xc3\xa7\xc3\xa3o" in zpl
        assert b"t\xc3\xa9rmica" in zpl
