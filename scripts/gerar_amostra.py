"""Gera 5.000 ativos de amostra em CADA inventário (TI e Impressoras).

## Para que serve

Ter um parque com volume parecido com o real para avaliar o sistema: as telas,
os filtros, os relatórios, a busca e o desempenho. Com dois ou três ativos,
nada disso mostra o que vai mostrar em produção.

## Como identificar e remover depois

Todo registro gerado leva a marca `AMOSTRA` em `observacoes`. Para apagar:

    python scripts/gerar_amostra.py --limpar

A marca é o que permite remover **sem tocar** no que já existia.

## O que é criado

- 5.000 ativos de TI      (notebooks, desktops, monitores)
- 5.000 impressoras       (laser, jato de tinta, térmica)
- Contratos de locação    — a maioria do parque, como no cenário real
- Categorias, localizações, departamentos e fornecedores, se faltarem
- Fotos do Banco de Imagens, distribuídas entre os ativos

Os dados são sorteados de listas de marcas e modelos reais, para a amostra
parecer um parque de verdade — e não `teste1`, `teste2`, `teste3`.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.contrato import Contrato  # noqa: E402
from app.models.core import (  # noqa: E402
    Ativo,
    Categoria,
    Departamento,
    Fornecedor,
    Imagem,
    Localizacao,
    Planta,
)
from app.models.enums import (  # noqa: E402
    Conectividade,
    Dominio,
    FormaAquisicao,
    StatusAtivo,
    TipoContrato,
    TipoImpressao,
    TipoItem,
)
from app.models.impressora import AtivoImpressora  # noqa: E402
from app.models.ti import AtivoTI  # noqa: E402

MARCA = "AMOSTRA"

QUANTOS = 5000
LOTE = 500

# ---------------------------------------------------------------------------
# Dados de apoio
# ---------------------------------------------------------------------------
CATEGORIAS = {
    "ti": ["Notebook", "Desktop", "Monitor", "All-in-One", "Workstation"],
    "impressora": ["Impressora Laser", "Impressora Jato de Tinta", "Impressora Térmica", "Multifuncional"],
}
LOCALIZACOES = [
    "Matriz — 1º andar", "Matriz — 2º andar", "Matriz — Térreo", "Almoxarifado",
    "Recepção", "Sala de Reuniões", "Data Center", "Produção", "Expedição",
    "Filial Norte", "Filial Sul", "Home Office",
]
DEPARTAMENTOS = [
    ("Administrativo", "ADM"), ("Financeiro", "FIN"), ("Recursos Humanos", "RH"),
    ("Tecnologia da Informação", "TI"), ("Comercial", "COM"), ("Produção", "PROD"),
    ("Logística", "LOG"), ("Compras", "CMP"), ("Jurídico", "JUR"), ("Marketing", "MKT"),
]
FORNECEDORES = [
    ("Dell Brasil", "72.381.189/0001-10"), ("HP Brasil", "61.797.924/0001-40"),
    ("Lenovo Brasil", "04.078.254/0001-15"), ("Positivo Tecnologia", "81.243.735/0001-44"),
    ("Brother Brasil", "05.675.278/0001-77"), ("Epson do Brasil", "43.013.971/0001-16"),
    ("Ricoh Brasil", "43.500.121/0001-90"), ("Xerox do Brasil", "03.952.866/0001-23"),
    ("Simpress Locação", "07.883.611/0001-55"), ("Kingstar Locação", "11.222.333/0001-44"),
]

TI_MARCAS = {
    "Notebook": [("Dell", "Latitude 3420"), ("Dell", "Latitude 5420"), ("HP", "EliteBook 840 G8"),
                 ("HP", "ProBook 445 G9"), ("Lenovo", "ThinkPad T14"), ("Lenovo", "IdeaPad 3i"),
                 ("Acer", "Aspire 5"), ("Samsung", "Book NP550"), ("Positivo", "Motion Q464C")],
    "Desktop": [("Dell", "OptiPlex 3080"), ("Dell", "OptiPlex 7010"), ("HP", "ProDesk 400 G7"),
                ("Lenovo", "ThinkCentre M70q"), ("Positivo", "Master D570")],
    "Monitor": [("Dell", "P2422H"), ("LG", "24MK430H"), ("Samsung", "S24R350"),
                ("AOC", "24B2XH"), ("HP", "P22h G4")],
    "All-in-One": [("Dell", "Inspiron 24 5410"), ("HP", "ProOne 440 G9"), ("Lenovo", "IdeaCentre AIO 3")],
    "Workstation": [("Dell", "Precision 3660"), ("HP", "Z2 G9"), ("Lenovo", "ThinkStation P360")],
}
TI_SO = ["Windows 10 Pro", "Windows 11 Pro", "Windows 11 Home", "Ubuntu 22.04 LTS",
         "Ubuntu 24.04 LTS", "Windows Server 2019"]
TI_CPU = ["i5-1135G7", "i5-1235U", "i7-1165G7", "i7-1255U", "Ryzen 5 5500U",
          "Ryzen 7 5700U", "Celeron N4020", "i3-1115G4"]
TI_RAM = [4, 8, 8, 16, 16, 16, 32, 32, 64]
TI_DISCO = [128, 256, 256, 512, 512, 512, 1024]

IMP_MARCAS = {
    "Impressora Laser": [("HP", "LaserJet Pro M404dn"), ("HP", "LaserJet Enterprise M507dn"),
                         ("Brother", "HL-L6202DW"), ("Brother", "DCP-L5652DN"),
                         ("Ricoh", "SP 3300DN"), ("Xerox", "VersaLink B405")],
    "Impressora Jato de Tinta": [("Epson", "EcoTank L6270"), ("Epson", "WorkForce Pro WF-C5790"),
                                 ("HP", "Smart Tank 581"), ("Canon", "PIXMA G3160")],
    "Impressora Térmica": [("Epson", "TM-T20X"), ("Elgin", "i9"), ("Bematech", "MP-4200 TH"),
                           ("Argox", "OS-214 plus"), ("Zebra", "ZD220")],
    "Multifuncional": [("HP", "LaserJet MFP M428fdw"), ("Brother", "MFC-L6902DW"),
                       ("Epson", "EcoTank L15150"), ("Ricoh", "MP C3004"), ("Canon", "imageRUNNER 2630i")],
}
IMP_DRIVERS = ["PCL6", "PostScript 3", "PCL5", "ZPL II", "TSPL", "ESC/POS", "GDI"]
IMP_CONECT = [Conectividade.REDE, Conectividade.USB, Conectividade.WIFI, Conectividade.REDE]

# Status ponderados: a maior parte do parque está em uso, não em estoque.
STATUS_PESO = [
    (StatusAtivo.EM_USO, 62),
    (StatusAtivo.ESTOQUE, 18),
    (StatusAtivo.MANUTENCAO, 9),
    (StatusAtivo.EMPRESTADO, 6),
    (StatusAtivo.RESERVADO, 3),
    (StatusAtivo.DESCARTADO, 2),
]


def _sorteio(pesos):
    total = sum(p for _, p in pesos)
    r = random.uniform(0, total)
    acumulado = 0.0
    for valor, peso in pesos:
        acumulado += peso
        if r <= acumulado:
            return valor
    return pesos[-1][0]


def _mac() -> str:
    return ":".join(f"{random.randint(0, 255):02X}" for _ in range(6))


def _ip(usados: set) -> str:
    """IP de rede interna, sem repetir dentro da geração."""
    while True:
        ip = f"10.{random.randint(10, 30)}.{random.randint(0, 255)}.{random.randint(2, 254)}"
        if ip not in usados:
            usados.add(ip)
            return ip


def _patrimonio(indice: int, prefixo: str) -> str:
    # 12 dígitos, no formato que já existe no sistema (ex.: TP98000011212).
    return f"{prefixo}{98000000000 + indice}"


# ---------------------------------------------------------------------------
def garantir_apoio(db) -> dict:
    """Cria categorias, localizações, departamentos e fornecedores se faltarem.

    Sem isso, os gráficos "por categoria" e "por departamento" ficariam
    vazios — e a amostra não serviria para avaliar justamente as telas que
    agrupam.
    """
    def obter(modelo, **filtros):
        achado = db.query(modelo).filter_by(**filtros).first()
        if achado:
            return achado
        novo = modelo(**filtros)
        db.add(novo)
        db.flush()
        return novo

    cats = {}
    for dom, nomes in CATEGORIAS.items():
        cats[dom] = [obter(Categoria, nome=n, dominio=dom) for n in nomes]

    locais = [obter(Localizacao, nome=n) for n in LOCALIZACOES]
    deps = [obter(Departamento, nome=n, sigla=s) for n, s in DEPARTAMENTOS]
    forns = [obter(Fornecedor, nome=n, cnpj=c) for n, c in FORNECEDORES]

    planta = db.query(Planta).first()
    fotos = [f.id for f in db.query(Imagem).all()]

    db.commit()
    return {"cats": cats, "locais": locais, "deps": deps, "forns": forns,
            "planta": planta, "fotos": fotos}


def criar_contratos(db, apoio) -> list[Contrato]:
    """Contratos de locação — a maioria do parque, como no cenário real."""
    contratos = []
    for i, fornecedor in enumerate(apoio["forns"][-2:], start=1):
        numero = f"LOC-2024/{i:03d}"
        if db.query(Contrato).filter(Contrato.numero == numero).first():
            continue
        c = Contrato(
            numero=numero,
            tipo=TipoContrato.LOCACAO,
            planta_id=apoio["planta"].id if apoio["planta"] else None,
            fornecedor_id=fornecedor.id,
            inicio=date(2024, random.randint(1, 6), 1),
            fim=date(2026, random.randint(6, 12), 28),
            valor_mensal=Decimal(random.randrange(18000, 95000, 500)),
            dia_vencimento=random.choice([5, 10, 15, 20]),
            observacoes=f"{MARCA} — contrato de amostra",
        )
        db.add(c)
        contratos.append(c)
    db.commit()
    return contratos


def gerar(db, dominio: str, quantos: int, apoio: dict, contratos: list) -> int:
    """Gera `quantos` ativos de um inventário. Devolve quantos criou."""
    prefixo = "TP" if dominio == "ti" else "IM"
    base_indice = db.query(func.count(Ativo.id)).scalar() or 0
    usados_ip: set[str] = set()
    criados = 0

    for inicio in range(0, quantos, LOTE):
        tamanho = min(LOTE, quantos - inicio)
        for i in range(tamanho):
            n = base_indice + inicio + i
            cat = random.choice(apoio["cats"][dominio])

            # 70% locado: é o cenário real do parque, e é o que faz o
            # financeiro e o rateio terem o que mostrar.
            locado = random.random() < 0.70
            contrato = random.choice(contratos) if (locado and contratos) else None

            ativo = Ativo(
                dominio=Dominio(dominio),
                tipo_item=TipoItem.ATIVO,
                patrimonio=_patrimonio(n + 1, prefixo),
                numero_serie=f"{random.choice('ABCDEFGHJKLMNPQRSTUVWXYZ')}{random.randint(1000000, 9999999)}",
                status=_sorteio(STATUS_PESO),
                planta_id=apoio["planta"].id if apoio["planta"] else None,
                categoria_id=cat.id,
                fornecedor_id=random.choice(apoio["forns"]).id,
                localizacao_id=random.choice(apoio["locais"]).id,
                departamento_id=random.choice(apoio["deps"]).id,
                # Distribuídos nos últimos 5 anos.
                data_aquisicao=date.today() - timedelta(days=random.randint(30, 1825)),
                data_garantia=date.today() + timedelta(days=random.randint(-400, 900)),
                forma_aquisicao=FormaAquisicao.LOCADO if locado else FormaAquisicao.COMPRADO,
                contrato_id=contrato.id if contrato else None,
                valor_residual=(
                    Decimal(random.randrange(200, 3000, 50)) if locado and random.random() < 0.4 else None
                ),
                foto_id=random.choice(apoio["fotos"]) if apoio["fotos"] else None,
                observacoes=f"{MARCA} — dado de teste para avaliação",
            )
            # Locado não tem valor de compra: preenchê-lo infla o patrimônio
            # com bem que não é da empresa.
            if not locado:
                ativo.valor = Decimal(random.randrange(1200, 12000, 50))

            db.add(ativo)
            db.flush()  # precisa do id para a ficha técnica

            if dominio == "ti":
                marca, modelo = random.choice(TI_MARCAS[cat.nome])
                ativo.marca, ativo.modelo = marca, modelo
                db.add(AtivoTI(
                    ativo_id=ativo.id,
                    hostname=f"{random.choice('ND')}TAT{n + 1:05d}",
                    mac_address=_mac(),
                    ip=_ip(usados_ip),
                    so=random.choice(TI_SO),
                    dominio_ad="empresa.local" if random.random() < 0.6 else None,
                    cpu=random.choice(TI_CPU),
                    ram_gb=random.choice(TI_RAM),
                    armazenamento_gb=random.choice(TI_DISCO),
                ))
            else:
                marca, modelo = random.choice(IMP_MARCAS[cat.nome])
                ativo.marca, ativo.modelo = marca, modelo
                db.add(AtivoImpressora(
                    ativo_id=ativo.id,
                    ip=_ip(usados_ip),
                    hostname=f"RTAT{n + 1:05d}",
                    driver=random.choice(IMP_DRIVERS),
                    tipo_impressao=random.choice(list(TipoImpressao)),
                    colorida=random.random() < 0.35,
                    contador_paginas=random.randint(0, 480000),
                    conectividade=random.choice(IMP_CONECT),
                ))
            criados += 1

        db.commit()
        print(f"  {dominio}: {criados}/{quantos}", end="\r")

    print(f"  {dominio}: {criados}/{quantos} — concluído")
    return criados


def limpar(db) -> None:
    """Remove só o que esta ferramenta criou — pela marca em `observacoes`."""
    ids = [a.id for a in db.query(Ativo.id).filter(Ativo.observacoes.like(f"{MARCA}%")).all()]
    if not ids:
        print("  Nada de amostra para remover.")
        return

    db.query(AtivoTI).filter(AtivoTI.ativo_id.in_(ids)).delete(synchronize_session=False)
    db.query(AtivoImpressora).filter(AtivoImpressora.ativo_id.in_(ids)).delete(synchronize_session=False)
    db.query(Ativo).filter(Ativo.id.in_(ids)).delete(synchronize_session=False)

    contratos = db.query(Contrato).filter(Contrato.observacoes.like(f"{MARCA}%")).all()
    for c in contratos:
        db.delete(c)

    db.commit()
    print(f"  Removidos {len(ids)} ativo(s) e {len(contratos)} contrato(s) de amostra.")


def main() -> None:
    p = argparse.ArgumentParser(description="Gera ativos de amostra.")
    p.add_argument("--quantos", type=int, default=QUANTOS, help="Por inventário.")
    p.add_argument("--limpar", action="store_true", help="Remove a amostra e sai.")
    p.add_argument("--semente", type=int, default=42, help="Para o resultado ser repetível.")
    args = p.parse_args()

    # Semente fixa: dois `--limpar` + gerar produzem o mesmo parque, o que
    # torna possível comparar uma medição com a outra.
    random.seed(args.semente)

    db = SessionLocal()
    try:
        if args.limpar:
            limpar(db)
            return

        apoio = garantir_apoio(db)
        if not apoio["planta"]:
            print("  ! Nenhuma planta cadastrada — crie uma antes.")
            return

        contratos = criar_contratos(db, apoio)
        print(f"  Contratos de locação: {len(contratos)}")

        gerar(db, "ti", args.quantos, apoio, contratos)
        gerar(db, "impressora", args.quantos, apoio, contratos)

        total = db.query(func.count(Ativo.id)).scalar()
        print(f"\n  Total de ativos no banco: {total}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
