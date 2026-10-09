"""Gerador de carga — cria ativos de teste espalhados pelas plantas.

Serve para medir o desempenho do sistema com volume real (listas, filtros,
paginação, relatórios) antes de colocar em produção.

Os registros nascem com o patrimônio prefixado por ``LOAD-``, então dá para
apagá-los depois com ``--limpar`` sem tocar em nada real.

Uso (na raiz do projeto, com o ambiente virtual ativo):

    python scripts/gerar_carga.py --total 5000 --banco loadtest.db
    python scripts/gerar_carga.py --banco loadtest.db --limpar
    python scripts/gerar_carga.py --total 5000 --banco estoque.db   # banco real

Por padrão o script **aborta** se você apontar para ``estoque.db`` sem passar
``--eu-sei-o-que-estou-fazendo`` — foi assim que um banco de trabalho foi
zerado uma vez, e não quero repetir isso.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from sqlalchemy import create_engine, delete, func, insert, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.models import Base  # noqa: E402
from app.models.core import (  # noqa: E402
    Ativo,
    Categoria,
    Departamento,
    Fornecedor,
    Localizacao,
    Planta,
    Usuario,
)
from app.models.enums import (  # noqa: E402
    Conectividade,
    Dominio,
    StatusAtivo,
    StatusManut,
    TipoImpressao,
    TipoItem,
    TipoMov,
)
from app.models.impressora import AtivoImpressora  # noqa: E402
from app.models.ti import AtivoTI  # noqa: E402

PREFIXO = "LOAD-"

MODELOS_TI = [
    ("Dell", "Latitude 5420"), ("Dell", "OptiPlex 7090"), ("HP", "ProDesk 400 G7"),
    ("HP", "EliteBook 840 G8"), ("Lenovo", "ThinkPad T14"), ("Lenovo", "ThinkCentre M70q"),
    ("Acer", "Aspire 5"), ("Samsung", "Book NP550"), ("Positivo", "Master D570"),
    ("Apple", "MacBook Pro 14"), ("Asus", "ExpertBook B1"), ("LG", "Gram 15"),
]
MODELOS_IMP = [
    ("HP", "LaserJet Pro M404dn"), ("HP", "LaserJet MFP M428fdw"), ("Brother", "HL-L6202DW"),
    ("Epson", "EcoTank L6270"), ("Canon", "imageCLASS MF445dw"), ("Zebra", "ZQ521"),
    ("Zebra", "ZD421"), ("Elgin", "i9"), ("Samsung", "Xpress M2020"), ("Lexmark", "MX622ade"),
]
SISTEMAS = ["Windows 11 Pro", "Windows 10 Pro", "Windows Server 2019", "Ubuntu 22.04", "Ubuntu 24.04"]
RAMS = ["4 GB", "8 GB", "8 GB", "16 GB", "16 GB", "32 GB", "64 GB"]
ARMAZENAMENTO = ["SSD 240 GB", "SSD 480 GB", "SSD 512 GB", "HD 1 TB", "SSD 1 TB"]
SETORES = ["Administrativo", "Financeiro", "RH", "Produção", "Qualidade", "Logística", "Engenharia", "TI", "Comercial", "Diretoria"]
PREDIOS = ["Prédio A", "Prédio B", "Prédio C", "Galpão 1", "Galpão 2", "Portaria", "Expedição"]
MARCA_TEXTO = "Registro de teste de carga"
SKU_PREFIXO = f"{PREFIXO}SKU-"
CIDADES = [("Campinas", "SP"), ("Recife", "PE"), ("Curitiba", "PR"), ("Salvador", "BA"), ("Manaus", "AM"), ("Porto Alegre", "RS")]

CONSUMIVEIS = [
    ("Toner HP 26A preto", "un"), ("Toner HP 58A preto", "un"), ("Toner Brother TN-3472", "un"),
    ("Cartucho Epson 664 preto", "un"), ("Cartucho Epson 664 colorido", "un"),
    ("Cabo de rede Cat6 1 m", "un"), ("Cabo de rede Cat6 3 m", "un"), ("Cabo HDMI 2 m", "un"),
    ("Cabo VGA 1,8 m", "un"), ("Mouse óptico USB", "un"), ("Teclado ABNT2 USB", "un"),
    ("Headset com microfone", "un"), ("Webcam Full HD", "un"), ("Suporte para notebook", "un"),
    ("Papel A4 75 g (resma)", "resma"), ("Etiqueta adesiva 100x50 mm (rolo)", "rolo"),
    ("Ribbon resina 110 mm", "rolo"), ("Fita matricial Epson", "un"),
    ("Pilha alcalina AA (par)", "par"), ("Fonte ATX 500 W", "un"),
    ("SSD 480 GB", "un"), ("Memória DDR4 8 GB", "un"), ("Estabilizador 300 VA", "un"),
    ("Nobreak 1200 VA", "un"), ("Limpa contato spray", "un"),
]
DESCRICOES_MANUT = [
    "Troca de toner e limpeza interna", "Substituição de fonte de alimentação",
    "Reparo na placa-mãe", "Troca de disco por SSD", "Formatação e reinstalação do sistema",
    "Limpeza e troca de pasta térmica", "Substituição de teclado", "Troca de tela",
    "Reparo no mecanismo de tração do papel", "Substituição do fusor",
    "Troca de bateria", "Atualização de memória RAM", "Reparo na porta USB",
    "Manutenção preventiva semestral", "Substituição de rolete de alimentação",
    "Recarga de cartucho", "Troca de cabeça de impressão", "Reparo na dobradiça",
]
TECNICOS = ["Carlos Silva", "Marcos Oliveira", "Ana Paula", "Rafael Souza", "Juliana Costa", "Bruno Almeida", "Fernanda Lima"]



def _colunas(modelo) -> set[str]:
    return {c.name for c in modelo.__table__.columns}


def _filtrar(modelo, dados: dict) -> dict:
    """Mantém só as colunas que existem de fato no modelo."""
    validas = _colunas(modelo)
    return {k: v for k, v in dados.items() if k in validas}


def _criar_apoio(db, quantidade: int) -> dict:
    """Categorias, locais, departamentos e fornecedores para variar os dados."""
    if not db.query(Categoria).first():
        db.add_all([Categoria(nome=n) for n in ["Notebook", "Desktop", "Monitor", "Impressora", "Celular", "Rede", "Periférico", "Servidor"]])
    if not db.query(Localizacao).first():
        db.add_all([Localizacao(nome=p) for p in PREDIOS])
    if not db.query(Departamento).first():
        db.add_all([Departamento(nome=s) for s in SETORES])
    if not db.query(Fornecedor).first():
        db.add_all([Fornecedor(nome=n) for n in ["Dell Brasil", "HP Brasil", "Lenovo", "Zebra Technologies", "Elgin", "Kalunga"]])
    db.commit()
    return {
        "categorias": [c.id for c in db.query(Categoria).all()],
        "localizacoes": [loc.id for loc in db.query(Localizacao).all()],
        "departamentos": [d.id for d in db.query(Departamento).all()],
        "fornecedores": [f.id for f in db.query(Fornecedor).all()],
    }


def _criar_plantas(db, quantidade: int) -> list[int]:
    """Garante plantas suficientes para espalhar os ativos."""
    existentes = db.query(Planta).all()
    if len(existentes) >= quantidade:
        return [p.id for p in existentes]

    faltam = quantidade - len(existentes)
    for i in range(faltam):
        cidade, uf = CIDADES[(len(existentes) + i) % len(CIDADES)]
        sigla = f"{cidade[:3].upper()}{len(existentes) + i + 1}"
        if db.query(Planta).filter(Planta.sigla == sigla).first():
            sigla = f"PL{len(existentes) + i + 1:03d}"
        db.add(Planta(nome=f"Unidade {cidade}", sigla=sigla, cidade=cidade, uf=uf, ativa=True))
    db.commit()
    return [p.id for p in db.query(Planta).all()]


def gerar_extras(db, quantidade: int, rnd: random.Random, apoio: dict, usuario_ids: list[int]) -> dict:
    """Cria consumíveis, movimentações e manutenções de demonstração.

    As movimentações são espalhadas nos últimos 6 meses (para o gráfico de
    "movimentações por mês" ficar populado) e as manutenções nos últimos 2 anos.
    """
    from app.models.core import Manutencao, Movimentacao, Produto

    hoje = datetime.now(timezone.utc)
    resultado = {}

    # --- Consumíveis ------------------------------------------------------
    produtos = []
    for i in range(quantidade):
        nome, unidade = CONSUMIVEIS[i % len(CONSUMIVEIS)]
        produtos.append({
            "sku": f"{SKU_PREFIXO}{i:06d}",
            "nome": f"{nome} — lote {i % 97 + 1:02d}",
            "descricao": f"{MARCA_TEXTO} #{i}",
            "categoria_id": rnd.choice(apoio["categorias"]),
            "fornecedor_id": rnd.choice(apoio["fornecedores"]),
            "dominio": Dominio.IMPRESSORA if rnd.random() < 0.6 else Dominio.TI,
            "tipo_item": TipoItem.CONSUMIVEL,
            "unidade": unidade,
            "estoque_minimo": rnd.choice([0, 2, 5, 5, 10, 20]),
            "preco_unitario": round(rnd.uniform(5, 900), 2),
        })
    db.execute(insert(Produto), produtos)
    db.commit()
    ids_produto = [r[0] for r in db.execute(select(Produto.id).where(Produto.sku.like(f"{SKU_PREFIXO}%"))).all()]
    resultado["produtos"] = len(produtos)

    # --- Ativos por planta (para as movimentações/manutenções) ------------
    linhas = db.execute(
        select(Ativo.id, Ativo.planta_id).where(Ativo.deleted_at.is_(None)).order_by(Ativo.id)
    ).all()
    if not linhas:
        return resultado

    # --- Movimentações ----------------------------------------------------
    movimentos = []
    for i in range(quantidade):
        ativo_id, _planta = linhas[i % len(linhas)]
        tipo = rnd.choices(
            [TipoMov.ENTRADA, TipoMov.SAIDA, TipoMov.TRANSFERENCIA,
             TipoMov.ATRIBUICAO, TipoMov.DEVOLUCAO, TipoMov.BAIXA],
            weights=[25, 25, 15, 15, 15, 5],
        )[0]
        # Espalha nos últimos 6 meses para o gráfico mensal.
        dias = rnd.randint(0, 180)
        movimentos.append({
            "tipo": tipo,
            "ativo_id": ativo_id if rnd.random() < 0.7 else None,
            "produto_id": rnd.choice(ids_produto) if ids_produto and rnd.random() < 0.4 else None,
            "quantidade": rnd.randint(1, 10),
            "origem_localizacao_id": rnd.choice(apoio["localizacoes"]),
            "destino_localizacao_id": rnd.choice(apoio["localizacoes"]),
            "origem_usuario_id": rnd.choice(usuario_ids) if usuario_ids else None,
            "destino_usuario_id": rnd.choice(usuario_ids) if usuario_ids else None,
            "data_mov": hoje - timedelta(days=dias, hours=rnd.randint(0, 23), minutes=rnd.randint(0, 59)),
            "observacoes": f"{MARCA_TEXTO} #{i}",
            "usuario_id": rnd.choice(usuario_ids) if usuario_ids else None,
        })
    db.execute(insert(Movimentacao), movimentos)
    db.commit()
    resultado["movimentacoes"] = len(movimentos)

    # --- Manutenções ------------------------------------------------------
    manutencoes = []
    for i in range(quantidade):
        ativo_id, _planta = linhas[i % len(linhas)]
        status = rnd.choices(
            [StatusManut.ABERTA, StatusManut.EM_ANDAMENTO, StatusManut.CONCLUIDA, StatusManut.CANCELADA],
            weights=[15, 20, 60, 5],
        )[0]
        abertura = hoje - timedelta(days=rnd.randint(0, 730), hours=rnd.randint(0, 23))
        concluida = status == StatusManut.CONCLUIDA
        manutencoes.append({
            "ativo_id": ativo_id,
            "fornecedor_id": rnd.choice(apoio["fornecedores"]),
            "status": status,
            "descricao": f"{rnd.choice(DESCRICOES_MANUT)} ({MARCA_TEXTO} #{i})",
            "custo": round(rnd.uniform(50, 4500), 2) if status != StatusManut.CANCELADA else None,
            "data_abertura": abertura,
            "data_conclusao": abertura + timedelta(days=rnd.randint(1, 45)) if concluida else None,
            "tecnico": rnd.choice(TECNICOS),
            "observacoes": f"{MARCA_TEXTO} #{i}",
        })
    db.execute(insert(Manutencao), manutencoes)
    db.commit()
    resultado["manutencoes"] = len(manutencoes)
    return resultado


def gerar(banco: str, total: int, plantas_alvo: int, semente: int = 42, extras: int = 0) -> None:
    rnd = random.Random(semente)
    url = f"sqlite:///{banco}"
    engine = create_engine(url)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    print(f"Banco: {banco}")
    t0 = time.perf_counter()

    apoio = _criar_apoio(db, total)
    plantas = _criar_plantas(db, plantas_alvo)
    print(f"  apoio criado ({time.perf_counter() - t0:.2f}s)")

    inicio = db.query(func.count(Ativo.id)).scalar() or 0
    print(f"  ativos hoje: {inicio}")
    print(f"  plantas: {len(plantas)}")

    hoje = date.today()
    ativos, extensoes_ti, extensoes_imp = [], [], []

    for i in range(total):
        planta_id = plantas[i % len(plantas)]
        dominio = Dominio.TI if i % 5 != 0 else Dominio.IMPRESSORA  # ~20% impressoras
        marca, modelo = rnd.choice(MODELOS_TI if dominio == Dominio.TI else MODELOS_IMP)
        status = rnd.choices(
            [StatusAtivo.ESTOQUE, StatusAtivo.EM_USO, StatusAtivo.MANUTENCAO,
             StatusAtivo.RESERVADO, StatusAtivo.EMPRESTADO, StatusAtivo.DESCARTADO],
            weights=[30, 45, 8, 7, 7, 3],
        )[0]
        adq = hoje - timedelta(days=rnd.randint(30, 2000))
        # Garantia variada: alguns já vencidos, outros vencendo nos próximos 90 dias.
        garantia = adq + timedelta(days=rnd.choice([365, 730, 1095])) if rnd.random() < 0.75 else None

        dados = {
            "patrimonio": f"{PREFIXO}{i:06d}",
            "planta_id": planta_id,
            "dominio": dominio,
            "tipo_item": TipoItem.ATIVO,
            "numero_serie": f"SN{rnd.randint(10**8, 10**9 - 1)}",
            "modelo": modelo,
            "marca": marca,
            "status": status,
            "categoria_id": rnd.choice(apoio["categorias"]),
            "fornecedor_id": rnd.choice(apoio["fornecedores"]),
            "localizacao_id": rnd.choice(apoio["localizacoes"]),
            "departamento_id": rnd.choice(apoio["departamentos"]),
            "data_aquisicao": adq,
            "data_garantia": garantia,
            "valor": round(rnd.uniform(800, 15000), 2),
            "observacoes": f"Registro de teste de carga #{i}",
        }
        ativos.append(_filtrar(Ativo, dados))

        # Guarda o ÍNDICE junto: o insert em lote não devolve os ids gerados,
        # então a extensão é ligada depois pelo id da posição correspondente.
        if dominio == Dominio.TI:
            extensoes_ti.append((i, _filtrar(AtivoTI, {
                "sistema_operacional": rnd.choice(SISTEMAS),
                "memoria_ram": rnd.choice(RAMS),
                "armazenamento": rnd.choice(ARMAZENAMENTO),
                "processador": rnd.choice(["i3-10100", "i5-11400", "i7-1165G7", "Ryzen 5 5600", "Ryzen 7 5800"]),
            })))
        else:
            extensoes_imp.append((i, _filtrar(AtivoImpressora, {
                "tipo_impressao": rnd.choice(list(TipoImpressao)),
                "conectividade": rnd.choice(list(Conectividade)),
                "contador_paginas": rnd.randint(0, 500_000),
            })))

    print(f"  dados montados em memória ({time.perf_counter() - t0:.2f}s)")
    t1 = time.perf_counter()
    # Inserção em lote: uma ida ao banco em vez de 5.000.
    # (lista vazia é ignorada — o SQLAlchemy tentaria um INSERT sem colunas)
    if ativos:
        db.execute(insert(Ativo), ativos)
        db.commit()
        print(f"  INSERT de {len(ativos)} ativos: {time.perf_counter() - t1:.2f}s")

    # Liga as extensões aos ids gerados (o lote não devolve os ids).
    ids = [r[0] for r in db.execute(select(Ativo.id).where(Ativo.patrimonio.like(f"{PREFIXO}%")).order_by(Ativo.id)).all()]
    ids = ids[len(ids) - total:]

    t2 = time.perf_counter()
    for lista, tabela in ((extensoes_ti, AtivoTI), (extensoes_imp, AtivoImpressora)):
        if not lista:
            continue
        linhas = [{**dados, "ativo_id": ids[indice]} for indice, dados in lista]
        db.execute(insert(tabela), linhas)
    db.commit()
    print(f"  extensões (TI/Impressora): {time.perf_counter() - t2:.2f}s")

    fim = db.query(func.count(Ativo.id)).scalar() or 0
    print(f"\nTotal de ativos agora: {fim}  (+{fim - inicio})")

    # --- Consumíveis, movimentações e manutenções -------------------------
    if extras:
        t3 = time.perf_counter()
        usuario_ids = [u[0] for u in db.execute(select(Usuario.id)).all()]
        criados = gerar_extras(db, extras, rnd, apoio, usuario_ids)
        for nome, qtd in criados.items():
            print(f"  {nome}: +{qtd}")
        print(f"  extras em {time.perf_counter() - t3:.2f}s")

    print(f"Tempo total: {time.perf_counter() - t0:.2f}s")

    por_planta = db.execute(
        select(Planta.sigla, func.count(Ativo.id)).join(Ativo, Ativo.planta_id == Planta.id).group_by(Planta.sigla).order_by(func.count(Ativo.id).desc())
    ).all()
    print("\nAtivos por planta:")
    for sigla, qtd in por_planta:
        print(f"   {sigla:<12} {qtd}")

    db.close()


def limpar(banco: str) -> None:
    from app.models.core import Manutencao, Movimentacao, Produto

    engine = create_engine(f"sqlite:///{banco}")
    db = sessionmaker(bind=engine)()
    ids = [r[0] for r in db.execute(select(Ativo.id).where(Ativo.patrimonio.like(f"{PREFIXO}%"))).all()]

    # Consumíveis, movimentações e manutenções de demonstração.
    n_mov = db.execute(delete(Movimentacao).where(Movimentacao.observacoes.like(f"{MARCA_TEXTO}%"))).rowcount
    n_man = db.execute(delete(Manutencao).where(Manutencao.observacoes.like(f"{MARCA_TEXTO}%"))).rowcount
    n_pro = db.execute(delete(Produto).where(Produto.sku.like(f"{SKU_PREFIXO}%"))).rowcount

    if ids:
        db.execute(delete(AtivoTI).where(AtivoTI.ativo_id.in_(ids)))
        db.execute(delete(AtivoImpressora).where(AtivoImpressora.ativo_id.in_(ids)))
        db.execute(delete(Ativo).where(Ativo.id.in_(ids)))
    db.commit()

    print(f"Removidos {len(ids)} ativos, {n_pro} consumíveis, {n_mov} movimentações e {n_man} manutenções de teste.")
    db.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Gera carga de teste no inventário.")
    p.add_argument("--banco", default="loadtest.db", help="arquivo do banco (padrão: loadtest.db)")
    p.add_argument("--total", type=int, default=5000, help="quantos ativos criar (padrão: 5000)")
    p.add_argument("--plantas", type=int, default=6, help="quantas plantas usar (padrão: 6)")
    p.add_argument("--extras", type=int, default=0,
                   help="quantos CONSUMÍVEIS, MOVIMENTAÇÕES e MANUTENÇÕES criar (um número para cada tipo)")
    p.add_argument("--semente", type=int, default=42, help="semente aleatória (reproduzível)")
    p.add_argument("--limpar", action="store_true", help="remove os registros LOAD-* e sai")
    p.add_argument("--eu-sei-o-que-estou-fazendo", dest="confirmado", action="store_true",
                   help="permite rodar contra estoque.db (banco real)")
    args = p.parse_args()

    if not os.path.exists(args.banco) and not args.limpar:
        print(f"AVISO: '{args.banco}' não existe; será criado do zero.")

    if os.path.basename(args.banco) == "estoque.db" and not args.confirmado:
        print(
            "RECUSADO: você apontou para o banco REAL (estoque.db).\n"
            "  Para testar com segurança, use uma cópia:\n"
            "      copy estoque.db loadtest.db\n"
            "      python scripts/gerar_carga.py --banco loadtest.db\n"
            "  Se realmente quer poluir o banco real, repita com --eu-sei-o-que-estou-fazendo."
        )
        sys.exit(2)

    if args.limpar:
        limpar(args.banco)
    else:
        gerar(args.banco, args.total, args.plantas, args.semente, args.extras)


if __name__ == "__main__":
    main()
