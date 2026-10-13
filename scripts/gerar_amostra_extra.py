"""Amplia a amostra: unidades, consumíveis, manutenções, movimentações e empréstimos.

## Por que separado do `gerar_amostra.py`

Aquele cria os **ativos** — 10 mil, e leva alguns minutos. Este cria o que
acontece **em volta** deles, e é muito mais rápido. Separar permite refazer só
uma das partes.

## O que ele cria

| Entidade | Quanto | Para quê |
|---|---|---|
| Unidades (plantas) | 7 | o filtro de unidade e o isolamento têm o que mostrar |
| Consumíveis | ~50 | estoque mínimo, ruptura, custo de consumo |
| Movimentações | ~12.000 | o gráfico de entradas × saídas precisa de série |
| Manutenções | ~2.000 | TCO, manutenção por situação, histórico do ativo |
| Empréstimos | ~900 | em atraso, devolvido, ativo — e o alerta do sino |
| Leituras de contador | ~6.000 | série histórica por impressora |
| Suprimentos | ~1.500 | toner por impressora, com nível baixo |

## Como remover

    python scripts/gerar_amostra.py --limpar

A marca `AMOSTRA` está em todo registro criado aqui também — inclusive nas
observações de manutenção e empréstimo. Sem isso, a limpeza deixaria metade
para trás, e a outra metade apontando para o nada.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.core import (  # noqa: E402
    Ativo,
    Localizacao,
    Manutencao,
    Movimentacao,
    Planta,
    Produto,
    Usuario,
)
from app.models.emprestimo import Emprestimo  # noqa: E402
from app.models.impressora import LeituraContador, SuprimentoImpressora  # noqa: E402

MARCA = "AMOSTRA"
LOTE = 400

# ---------------------------------------------------------------------------
# Unidades
# ---------------------------------------------------------------------------
# Nome, sigla. A primeira já existe; as demais são criadas.
UNIDADES = [
    ("Matriz", "MAT", "São Paulo — SP"),
    ("Filial Norte", "FN", "Recife — PE"),
    ("Filial Sul", "FS", "Porto Alegre — RS"),
    ("Centro de Distribuição", "CD", "Guarulhos — SP"),
    ("Escritório Rio", "RIO", "Rio de Janeiro — RJ"),
    ("Fábrica Interior", "FAB", "Sorocaba — SP"),
    ("Filial Centro-Oeste", "FCO", "Goiânia — GO"),
]

# ---------------------------------------------------------------------------
# Consumíveis
# ---------------------------------------------------------------------------
# (nome, tipo, unidade, preço mínimo, preço máximo, estoque mínimo)
CONSUMIVEIS = [
    ("Toner HP 58A Preto", "ti", "un", 280, 420, 10),
    ("Toner HP 26A Preto", "ti", "un", 340, 520, 8),
    ("Toner Brother TN-3472", "ti", "un", 240, 380, 12),
    ("Toner Samsung MLT-D111S", "ti", "un", 190, 290, 6),
    ("Cartucho Epson 664 Preto", "ti", "un", 45, 75, 20),
    ("Cartucho Epson 664 Colorido", "ti", "un", 55, 90, 20),
    ("Cartucho Canon PG-245", "ti", "un", 90, 140, 8),
    ("Papel A4 75g — resma", "ti", "resma", 22, 32, 50),
    ("Papel A4 90g — resma", "ti", "resma", 28, 40, 20),
    ("Papel Ofício 2 — caixa", "ti", "cx", 90, 130, 10),
    ("Papel Térmico 57mm", "ti", "rolo", 3, 6, 40),
    ("Papel Térmico 80mm", "ti", "rolo", 4, 8, 40),
    ("Etiqueta Pimaco 6180", "ti", "cx", 45, 70, 15),
    ("Mouse USB óptico", "ti", "un", 25, 60, 25),
    ("Mouse sem fio", "ti", "un", 55, 120, 15),
    ("Teclado ABNT2 USB", "ti", "un", 45, 110, 20),
    ("Teclado sem fio", "ti", "un", 90, 180, 10),
    ("Headset com microfone", "ti", "un", 80, 240, 20),
    ("Webcam Full HD", "ti", "un", 120, 320, 8),
    ("Cabo de rede Cat6 — 5m", "ti", "un", 12, 25, 60),
    ("Cabo de rede Cat6 — 10m", "ti", "un", 18, 38, 40),
    ("Cabo HDMI 2m", "ti", "un", 20, 45, 30),
    ("Cabo DisplayPort 2m", "ti", "un", 30, 65, 15),
    ("Cabo de força tripolar", "ti", "un", 12, 28, 50),
    ("Estabilizador 300VA", "ti", "un", 120, 210, 8),
    ("Nobreak 600VA", "ti", "un", 320, 520, 6),
    ("Fonte ATX 500W", "ti", "un", 180, 320, 5),
    ("SSD SATA 480GB", "ti", "un", 200, 340, 10),
    ("SSD NVMe 1TB", "ti", "un", 380, 620, 6),
    ("Memória DDR4 8GB", "ti", "un", 140, 240, 10),
    ("Memória DDR4 16GB", "ti", "un", 240, 400, 8),
    ("Pilha AAA — cartela", "ti", "cartela", 8, 16, 30),
    ("Pilha AA — cartela", "ti", "cartela", 9, 18, 30),
    ("Bateria CR2032", "ti", "un", 3, 8, 20),
    ("Limpa contato spray", "ti", "un", 18, 35, 10),
    ("Álcool isopropílico 1L", "ti", "un", 25, 45, 12),
    ("Pasta térmica", "ti", "un", 15, 35, 15),
    ("Kit limpeza de teclado", "ti", "kit", 20, 45, 8),
    ("HD externo 1TB", "ti", "un", 280, 420, 5),
    ("HD externo 2TB", "ti", "un", 380, 580, 4),
    ("Pen drive 32GB", "ti", "un", 28, 55, 30),
    ("Pen drive 64GB", "ti", "un", 42, 80, 20),
    ("Suporte para notebook", "ti", "un", 60, 160, 10),
    ("Suporte articulado monitor", "ti", "un", 120, 320, 8),
    ("Filtro de linha 5 tomadas", "ti", "un", 35, 75, 25),
    ("Adaptador USB-C para HDMI", "ti", "un", 60, 140, 12),
    ("Hub USB 4 portas", "ti", "un", 35, 90, 12),
    ("Grampeador de mesa", "ti", "un", 25, 55, 10),
    ("Perfurador de papel", "ti", "un", 35, 70, 8),
    ("Grampo 26/6 — caixa", "ti", "cx", 6, 14, 40),
]

MANUTENCOES = [
    ("Troca de HD por SSD", 180, 480),
    ("Formatação e reinstalação do sistema", 0, 0),
    ("Limpeza interna e troca de pasta térmica", 40, 120),
    ("Substituição de memória RAM", 140, 400),
    ("Troca de fonte de alimentação", 180, 380),
    ("Reparo de dobradiça do notebook", 120, 320),
    ("Troca de tela de notebook", 480, 1200),
    ("Troca de teclado", 110, 280),
    ("Substituição de bateria", 180, 420),
    ("Reparo de conector de energia", 90, 260),
    ("Limpeza de impressora e cabeçote", 80, 220),
    ("Troca de fusor de impressora", 380, 850),
    ("Substituição de rolete de tração", 90, 240),
    ("Reparo de bandeja de papel", 60, 180),
    ("Atualização de firmware", 0, 0),
    ("Diagnóstico sem defeito encontrado", 0, 0),
    ("Troca de placa-mãe", 620, 1600),
    ("Reparo de porta USB", 90, 220),
    ("Substituição de cooler", 70, 190),
    ("Recuperação de dados", 250, 800),
]

TECNICOS = [
    "Carlos Menezes", "Fernanda Lima", "Rafael Souza", "Juliana Prado",
    "Marcos Vinícius", "Patrícia Rocha", "Bruno Almeida", "Tatiane Correia",
    "Suporte Externo — Dell", "Suporte Externo — HP", "Assistência Local",
]

FINALIDADES = [
    "Uso em home office", "Substituição de equipamento com defeito",
    "Projeto temporário", "Treinamento", "Evento externo",
    "Empréstimo entre unidades", "Atendimento a cliente",
    "Cobertura de férias", "Equipamento reserva",
]


def _sorteio_status_manut() -> str:
    r = random.random()
    if r < 0.55:
        return "concluida"
    if r < 0.75:
        return "aberta"
    if r < 0.92:
        return "em_andamento"
    return "cancelada"


# ---------------------------------------------------------------------------
def criar_unidades(db) -> list[Planta]:
    """Cria as unidades que faltam. A Matriz normalmente já existe."""
    plantas = []
    for nome, sigla, _cidade in UNIDADES:
        p = db.query(Planta).filter(Planta.sigla == sigla).first()
        if not p:
            p = Planta(nome=nome, sigla=sigla, ativa=True)
            db.add(p)
            db.flush()
        plantas.append(p)
    db.commit()
    return plantas


def distribuir_ativos(db, plantas: list[Planta]) -> int:
    """Espalha os ativos pelas unidades.

    ## Por que redistribuir

    Todos nasceram numa planta só. Com uma unidade, o filtro de unidade não
    filtra nada, o isolamento entre plantas não tem o que provar e o
    relatório por unidade mostra uma linha. **A amostra não exercita o que
    existe justamente para separar.**

    A distribuição é desigual de propósito: unidades grandes e pequenas
    revelam problemas que uma divisão igual esconde — como um alerta que só
    dispara na unidade com 3 equipamentos.
    """
    pesos = [0.40, 0.14, 0.13, 0.11, 0.09, 0.08, 0.05]
    ids = [a.id for a in db.query(Ativo.id).filter(Ativo.deleted_at.is_(None)).all()]
    random.shuffle(ids)

    corte = 0
    mudados = 0
    for planta, peso in zip(plantas, pesos):
        quantos = int(len(ids) * peso)
        for ativo_id in ids[corte:corte + quantos]:
            db.query(Ativo).filter(Ativo.id == ativo_id).update(
                {"planta_id": planta.id}, synchronize_session=False)
            mudados += 1
        corte += quantos
        db.commit()
    return mudados


def criar_consumiveis(db, plantas: list[Planta]) -> list[Produto]:
    """Os itens de consumo, com preço e estoque mínimo."""
    existentes = (
        db.query(Produto)
        .filter(Produto.descricao.like(f"{MARCA}%"))
        .count()
    )
    if existentes:
        return db.query(Produto).filter(Produto.descricao.like(f"{MARCA}%")).all()

    from app.models.core import Fornecedor

    fornecedores = db.query(Fornecedor).all()
    produtos = []
    for i, (nome, dominio, unidade, pmin, pmax, minimo) in enumerate(CONSUMIVEIS, 1):
        p = Produto(
            sku=f"AMO-{i:04d}",
            nome=nome,
            descricao=f"{MARCA} — consumível de exemplo",
            dominio=dominio,
            tipo_item="consumivel",
            unidade=unidade,
            estoque_minimo=minimo,
            preco_unitario=Decimal(str(random.randrange(pmin, pmax, 5))),
            fornecedor_id=random.choice(fornecedores).id if fornecedores else None,
        )
        db.add(p)
        produtos.append(p)
    db.commit()
    return produtos


def criar_movimentacoes(db, ativos: list[int], produtos: list[Produto],
                        plantas: list[Planta], quantas: int) -> int:
    """Entradas e saídas, espalhadas nos últimos 18 meses.

    ## Por que 18 meses

    O relatório tem filtro de período. Com histórico de poucas semanas, o
    recorte "últimos 12 meses" mostraria o mesmo que "últimos 30 dias" — e o
    gráfico de evolução não teria série para desenhar.
    """
    locais = db.query(Localizacao).all()
    usuarios = db.query(Usuario).all()
    hoje = date.today()
    criadas = 0

    for inicio in range(0, quantas, LOTE):
        tamanho = min(LOTE, quantas - inicio)
        for _ in range(tamanho):
            dias = random.randint(0, 540)
            data_mov = datetime.combine(hoje - timedelta(days=dias),
                                        datetime.min.time()).replace(tzinfo=timezone.utc)

            # 60% saída de consumível (o dia a dia), 40% movimentação de ativo.
            consumivel = produtos and random.random() < 0.60
            if consumivel:
                p = random.choice(produtos)
                db.add(Movimentacao(
                    tipo=random.choice(["entrada", "saida", "saida", "saida"]),
                    produto_id=p.id,
                    quantidade=random.randint(1, 8),
                    data_mov=data_mov,
                    origem_localizacao_id=random.choice(locais).id if locais else None,
                    destino_usuario_id=random.choice(usuarios).id if usuarios else None,
                    usuario_id=random.choice(usuarios).id if usuarios else None,
                    finalidade=random.choice(["consumo", "instalacao", "compra"]),
                    observacoes=f"{MARCA} — movimentação de exemplo",
                ))
            else:
                db.add(Movimentacao(
                    tipo=random.choice(["entrada", "saida"]),
                    ativo_id=random.choice(ativos),
                    quantidade=1,
                    data_mov=data_mov,
                    origem_localizacao_id=random.choice(locais).id if locais else None,
                    destino_localizacao_id=random.choice(locais).id if locais else None,
                    usuario_id=random.choice(usuarios).id if usuarios else None,
                    observacoes=f"{MARCA} — movimentação de exemplo",
                ))
            criadas += 1
        db.commit()
    return criadas


def criar_manutencoes(db, ativos: list[int], quantas: int) -> int:
    """Ordens de serviço com custo e desfecho."""
    from app.models.core import Fornecedor

    fornecedores = db.query(Fornecedor).all()
    criadas = 0
    hoje = date.today()

    for inicio in range(0, quantas, LOTE):
        tamanho = min(LOTE, quantas - inicio)
        for _ in range(tamanho):
            descricao, cmin, cmax = random.choice(MANUTENCOES)
            status = _sorteio_status_manut()
            abertura = hoje - timedelta(days=random.randint(0, 700))

            m = Manutencao(
                ativo_id=random.choice(ativos),
                fornecedor_id=random.choice(fornecedores).id if fornecedores and random.random() < 0.4 else None,
                status=status,
                descricao=descricao,
                # Cancelada e "sem defeito" não custam — é o que dá sentido ao
                # número do TCO. Custo em toda linha faria a manutenção
                # parecer mais cara do que é.
                custo=(
                    Decimal(str(random.randrange(cmin, max(cmax, cmin + 10), 10)))
                    if status == "concluida" and cmax > 0 else Decimal("0")
                ),
                data_abertura=abertura,
                data_conclusao=(abertura + timedelta(days=random.randint(1, 45))
                                if status == "concluida" else None),
                tecnico=random.choice(TECNICOS),
                observacoes=f"{MARCA} — ordem de exemplo",
                comentario_conclusao=("Equipamento testado e liberado."
                                      if status == "concluida" else None),
            )
            db.add(m)
            criadas += 1
        db.commit()
    return criadas


def criar_emprestimos(db, ativos: list[int], plantas: list[Planta], quantos: int) -> int:
    """Empréstimos em todas as situações, inclusive em atraso."""
    from app.models.core import Departamento

    departamentos = db.query(Departamento).all()
    usuarios = db.query(Usuario).all()
    hoje = date.today()
    criados = 0

    for inicio in range(0, quantos, LOTE):
        tamanho = min(LOTE, quantos - inicio)
        for _ in range(tamanho):
            # Cada situação existe para uma tela diferente: o alerta de
            # atraso, o termo de devolução, o histórico.
            # Valores do enum `SituacaoEmprestimo`: reservado, retirado,
            # devolvido, vistoriado, cancelado.
            #
            # "atrasado" NÃO é situação — é derivado: `retirado` com a
            # `devolucao_prevista` no passado. Gravar "atrasado" como status
            # deixaria o registro ilegível (o enum não o reconhece) e a tela
            # quebraria ao ler. Foi o que aconteceu na primeira versão.
            r = random.random()
            # devolucao_prevista no passado. Gravar "atrasado" como status
            # deixaria o registro ilegível (o enum não o reconhece) e a tela
            # quebraria ao ler. Foi o que aconteceu na primeira versão.
            r = random.random()
            if r < 0.45:
                situacao = "devolvido"
            elif r < 0.75:
                situacao = "retirado"       # inclui os em atraso, pela data
            elif r < 0.85:
                situacao = "reservado"
            elif r < 0.93:
                situacao = "vistoriado"
            else:
                situacao = "cancelado"

            retirada = hoje - timedelta(days=random.randint(1, 400))
            prevista = retirada + timedelta(days=random.choice([7, 15, 30, 60, 90]))

            db.add(Emprestimo(
                ativo_id=random.choice(ativos),
                planta_id=random.choice(plantas).id,
                usuario_id=random.choice(usuarios).id if usuarios else None,
                retirado_por_nome=random.choice(TECNICOS),
                departamento_id=random.choice(departamentos).id if departamentos else None,
                situacao=situacao,
                finalidade=random.choice(FINALIDADES),
                observacoes=f"{MARCA} — empréstimo de exemplo",
                reservado_em=datetime.combine(retirada - timedelta(days=2),
                                              datetime.min.time()).replace(tzinfo=timezone.utc),
                retirada_prevista=retirada,
                retirado_em=(datetime.combine(retirada, datetime.min.time()).replace(tzinfo=timezone.utc)
                             if situacao != "reservado" else None),
                devolucao_prevista=prevista,
                devolvido_em=(datetime.combine(prevista - timedelta(days=random.randint(0, 5)),
                                               datetime.min.time()).replace(tzinfo=timezone.utc)
                              if situacao == "devolvido" else None),
                bloqueado=False,
            ))
            criados += 1
        db.commit()
    return criados


def criar_contadores(db, ativos: list[int], quantas: int) -> int:
    """Série histórica de contador de páginas.

    Sem série, a tela de contador mostra um número. Com série, mostra a
    evolução e o custo por página — que é o que interessa em impressora.
    """
    criadas = 0
    for inicio in range(0, quantas, LOTE):
        tamanho = min(LOTE, quantas - inicio)
        for _ in range(tamanho):
            ativo_id = random.choice(ativos)
            base = random.randint(1000, 400000)
            for mes in range(random.randint(3, 12)):
                db.add(LeituraContador(
                    ativo_id=ativo_id,
                    data_leitura=date.today() - timedelta(days=30 * mes),
                    contador=base + mes * random.randint(800, 12000),
                    observacoes=f"{MARCA} — leitura de exemplo",
                ))
                criadas += 1
        db.commit()
    return criadas


def criar_suprimentos(db, impressoras: list[int]) -> int:
    """Toner por impressora, com vários abaixo do mínimo.

    O nível baixo é de propósito: é o que faz o alerta do sino e o relatório
    de reposição aparecerem. Tudo acima do mínimo deixaria a tela vazia.
    """
    cores = ["preto", "ciano", "magenta", "amarelo"]
    modelos = ["HP 58A", "HP 26A", "Brother TN-3472", "Epson 664", "Canon PG-245"]
    criados = 0

    for ativo_id in impressoras:
        for _ in range(random.randint(1, 4)):
            minimo = random.choice([2, 3, 5])
            db.add(SuprimentoImpressora(
                ativo_id=ativo_id,
                tipo=random.choice(["toner", "tinta", "cilindro"]),
                modelo=random.choice(modelos),
                cor=random.choice(cores),
                rendimento_paginas=random.choice([1500, 3000, 6000, 12000]),
                # 35% abaixo do mínimo — proporção suficiente para a tela ter
                # o que mostrar sem virar um parque inteiro em ruptura.
                estoque_atual=(random.randint(0, minimo) if random.random() < 0.35
                               else random.randint(minimo + 1, minimo + 12)),
                estoque_minimo=minimo,
            ))
            criados += 1
        if criados % 500 < 5:
            db.commit()
    db.commit()
    return criados


# ---------------------------------------------------------------------------
def main() -> None:
    p = argparse.ArgumentParser(description="Amplia a amostra do sistema.")
    p.add_argument("--semente", type=int, default=42)
    args = p.parse_args()
    random.seed(args.semente)

    db = SessionLocal()
    try:
        plantas = criar_unidades(db)
        print(f"  Unidades: {len(plantas)}")

        ativos = [a.id for a in db.query(Ativo.id).filter(Ativo.deleted_at.is_(None)).all()]
        if not ativos:
            print("  ! Nenhum ativo. Rode antes: python scripts/gerar_amostra.py")
            return

        print(f"  Ativos: {len(ativos)}")
        print(f"  Redistribuídos entre unidades: {distribuir_ativos(db, plantas)}")

        produtos = criar_consumiveis(db, plantas)
        print(f"  Consumíveis: {len(produtos)}")

        # Impressoras de verdade: as de TI não têm contador nem toner.
        impressoras = [
            a.id for a in db.query(Ativo.id).filter(
                Ativo.deleted_at.is_(None), Ativo.dominio == "impressora"
            ).all()
        ]
        ti = [
            a.id for a in db.query(Ativo.id).filter(
                Ativo.deleted_at.is_(None), Ativo.dominio == "ti"
            ).all()
        ]

        print(f"  Movimentações: {criar_movimentacoes(db, ativos, produtos, plantas, 12000)}")
        print(f"  Manutenções: {criar_manutencoes(db, ativos, 2000)}")
        print(f"  Empréstimos: {criar_emprestimos(db, ti, plantas, 900)}")
        print(f"  Leituras de contador: {criar_contadores(db, impressoras, 600)}")
        print(f"  Suprimentos: {criar_suprimentos(db, impressoras)}")

        print()
        for nome, modelo in (
            ("Plantas", Planta), ("Ativos", Ativo), ("Produtos", Produto),
            ("Movimentações", Movimentacao), ("Manutenções", Manutencao),
            ("Empréstimos", Emprestimo), ("Leituras", LeituraContador),
            ("Suprimentos", SuprimentoImpressora),
        ):
            total = db.query(func.count(modelo.id)).scalar()
            print(f"  {nome:<16} {total:>7}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
