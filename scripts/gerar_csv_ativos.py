"""Gera um CSV de ativos para importar pela tela, em vez de inserir no banco.

## Por que um CSV, e não INSERT

O importador da tela é **o mesmo caminho que o cliente vai usar**. Alimentar o
banco direto testaria o banco; gerar o CSV testa **a importação** — validação,
criação de categoria/fornecedor/local, vínculo de planta, relatório de erros.

Um teste que pula a importação não prova nada sobre a importação.

## O que ele produz

`ativos_teste_5000.csv` — 5.000 ativos **únicos**, no formato que
`app/services/importar_ativos.py` espera:

* delimitador `;`
* UTF-8 **com BOM** (o Excel precisa do BOM para abrir acentuação)
* uma linha de cabeçalho, na ordem de `COLUNAS`

**Distribuição**: 4.000 de TI e 1.000 impressoras, para exercitar as duas
fichas técnicas.

## Determinismo

Usa semente fixa. Rodar duas vezes gera o **mesmo arquivo** — o que permite
comparar, versionar e repetir um teste que falhou.

Uso:
    python scripts/gerar_csv_ativos.py
    python scripts/gerar_csv_ativos.py --total 500 --saida amostra.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import random
from datetime import date, timedelta
from pathlib import Path

from app.services import importar_ativos as modelo

SEMENTE = 20261030
SERIE = "ACDEFGHJKLMNPQRTUVWXY3456789"  # sem I/O/0/1/B/2/Z — confundem na etiqueta

SO = [
    "Windows 11 Pro", "Windows 10 Pro", "Windows 11 Enterprise",
    "Ubuntu 24.04 LTS", "Ubuntu 22.04 LTS",
]
CPU = [
    "Intel Core i5-1235U", "Intel Core i7-1355U", "Intel Core i5-1145G7",
    "AMD Ryzen 5 5600U", "AMD Ryzen 7 5800U", "Intel Core i3-1115G4",
]

TI_MODELOS = [
    ("Dell", "Latitude 3420", "Notebook"),
    ("Dell", "Latitude 5440", "Notebook"),
    ("Dell", "OptiPlex 3000", "Desktop"),
    ("Lenovo", "ThinkPad E14", "Notebook"),
    ("Lenovo", "ThinkCentre M70q", "Desktop"),
    ("HP", "EliteBook 840 G9", "Notebook"),
    ("HP", "ProDesk 400 G9", "Desktop"),
    ("Acer", "Aspire 5", "Notebook"),
    ("Positivo", "Master D570", "Desktop"),
    ("Apple", "MacBook Air M2", "Notebook"),
]

IMP_MODELOS = [
    ("HP", "LaserJet Pro M404dn", "laser", "nao"),
    ("HP", "Color LaserJet Pro M454dw", "laser", "sim"),
    ("Brother", "HL-L2350DW", "laser", "nao"),
    ("Brother", "DCP-L3551CDW", "laser", "sim"),
    ("Epson", "EcoTank L3250", "jato_tinta", "sim"),
    ("Epson", "EcoTank L15150", "jato_tinta", "sim"),
    ("Zebra", "ZD220", "termica", "nao"),
    ("Zebra", "ZT411", "termica", "nao"),
    ("Elgin", "i9", "termica", "nao"),
    ("Argox", "OS-214", "termica", "nao"),
]

FORNECEDORES = ["Dell Brasil", "Lenovo do Brasil", "HP Brasil", "Epson Brasil",
                "Brother Brasil", "Zebra Technologies", "Positivo Tecnologia"]
LOCAIS = ["Escritório Central", "Recepção", "Sala de Reunião 1", "Sala de Reunião 2",
          "Financeiro", "Almoxarifado", "Fábrica — Linha 1", "Fábrica — Linha 2",
          "Sala Técnica", "Diretoria"]
DEPARTAMENTOS = ["TI", "Financeiro", "RH", "Comercial", "Produção", "Logística",
                 "Administrativo", "Diretoria", "Engenharia", "Suporte"]

# `status` ponderado: a maioria em uso, como num parque real.
STATUS = ["em_uso"] * 60 + ["estoque"] * 25 + ["manutencao"] * 10 + ["reservado"] * 5


def _serial(rng: random.Random, usado: set[str]) -> str:
    """Série no formato do fabricante, garantidamente única."""
    while True:
        corpo = "".join(rng.choice(SERIE) for _ in range(9))
        serie = f"{corpo[:3]}{corpo[3:]}"
        if serie not in usado:
            usado.add(serie)
            return serie


def _mac(rng: random.Random) -> str:
    return ":".join(f"{rng.randint(0, 255):02X}" for _ in range(6))


def _ip(rng: random.Random, usado: set[str]) -> str:
    while True:
        ip = f"10.{rng.randint(1, 30)}.{rng.randint(1, 254)}.{rng.randint(2, 254)}"
        if ip not in usado:
            usado.add(ip)
            return ip


def gerar(total: int, saida: Path) -> None:
    rng = random.Random(SEMENTE)

    # A distribuição 4:1 mantém a proporção e garante que as duas fichas
    # apareçam com volume suficiente para exercitar a importação.
    qtd_impressoras = max(1, total // 5)
    qtd_ti = total - qtd_impressoras

    seriais: set[str] = set()
    ips: set[str] = set()

    buf = io.StringIO()
    escritor = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    escritor.writerow([c[0] for c in modelo.COLUNAS])

    for i in range(total):
        eh_impressora = i >= qtd_ti
        n = (i + 1) if not eh_impressora else (i - qtd_ti + 1)

        if eh_impressora:
            marca, modelo_nome, tipo_imp, colorida = rng.choice(IMP_MODELOS)
            patrimonio = f"IMP-{n:05d}"
            categoria = "Impressora"
            dominio = "impressora"
            ano = rng.randint(2019, 2025)
            valor = round(rng.uniform(900, 5500), 2)
            garantia = date(ano, rng.randint(1, 12), rng.randint(1, 28)) + timedelta(days=365 * 2)
        else:
            marca, modelo_nome, categoria = rng.choice(TI_MODELOS)
            patrimonio = f"TI-{n:06d}"
            dominio = "ti"
            ano = rng.randint(2018, 2025)
            valor = round(rng.uniform(2200, 9800), 2)
            garantia = date(ano, rng.randint(1, 12), rng.randint(1, 28)) + timedelta(days=365 * 3)

        data_aquisicao = date(ano, rng.randint(1, 12), rng.randint(1, 28))
        # Garantia pode já ter vencido — é o caso real de parte do parque.
        data_garantia = garantia if garantia > data_aquisicao else data_aquisicao + timedelta(days=365)

        linha = {
            "patrimonio": patrimonio,
            "dominio": dominio,
            "tipo_item": "ativo",
            "numero_serie": _serial(rng, seriais),
            "modelo": modelo_nome,
            "marca": marca,
            "status": rng.choice(STATUS),
            "categoria": categoria,
            "fornecedor": rng.choice(FORNECEDORES),
            "localizacao": rng.choice(LOCAIS),
            "departamento": rng.choice(DEPARTAMENTOS),
            "data_aquisicao": data_aquisicao.isoformat(),
            "data_garantia": data_garantia.isoformat(),
            "valor": f"{valor:.2f}",
            "forma_aquisicao": rng.choice(["comprado"] * 8 + ["locado", "assinatura"]),
            "observacoes": "",
            "foto": "",
        }

        if eh_impressora:
            linha.update({
                "tipo_impressao": tipo_imp,
                "colorida": colorida,
                "contador_paginas": str(rng.randint(0, 480_000)),
                "conectividade": rng.choice(["rede", "rede", "rede", "usb", "wifi"]),
                "driver": f"{marca} Universal Driver",
                "ip": _ip(rng, ips),
            })
        else:
            linha.update({
                "hostname": f"NM-{rng.choice(['SP', 'FN', 'RJ'])}-{n:04d}",
                "mac_address": _mac(rng),
                "ip": _ip(rng, ips),
                "so": rng.choice(SO),
                "cpu": rng.choice(CPU),
                "ram_gb": str(rng.choice([8, 8, 16, 16, 16, 32])),
                "armazenamento_gb": str(rng.choice([240, 256, 512, 512, 1024])),
            })

        escritor.writerow([linha.get(c[0], "") for c in modelo.COLUNAS])

    # BOM explícito: é o que faz o Excel abrir acentuação corretamente.
    conteudo = "\ufeff" + buf.getvalue()
    saida.write_text(conteudo, encoding="utf-8", newline="")

    print(f"  {saida}  — {total} linhas")
    print(f"  TI: {qtd_ti}  |  Impressoras: {qtd_impressoras}")
    print(f"  tamanho: {saida.stat().st_size / 1024:.0f} KB")
    print(f"  séries únicas: {len(seriais)}  |  IPs únicos: {len(ips)}")


def main() -> None:
    p = argparse.ArgumentParser(description="Gera CSV de ativos para importar pela tela.")
    p.add_argument("--total", type=int, default=5000)
    p.add_argument("--saida", type=Path, default=Path("ativos_teste_5000.csv"))
    a = p.parse_args()

    if a.total < 1:
        raise SystemExit("--total precisa ser >= 1")
    gerar(a.total, a.saida)


if __name__ == "__main__":
    main()
