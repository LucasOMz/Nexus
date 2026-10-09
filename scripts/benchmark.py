"""Mede o desempenho das telas mais usadas, direto contra um banco.

Uso:
    python scripts/benchmark.py --banco loadtest.db
    python scripts/benchmark.py --banco loadtest.db --repetir 10 --saida rel.txt

Mede o tempo de resposta dos endpoints que o usuário mais toca. É o número que
importa antes de subir para produção com volume real.
"""
from __future__ import annotations

import argparse
import logging
import os
import statistics
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

LINHAS: list[str] = []


def escrever(texto: str = "") -> None:
    """Imprime e acumula, para o relatório poder ser salvo em arquivo."""
    print(texto)
    LINHAS.append(texto)


def main() -> None:
    p = argparse.ArgumentParser(description="Benchmark dos endpoints principais.")
    p.add_argument("--banco", default="loadtest.db")
    p.add_argument("--repetir", type=int, default=7)
    p.add_argument("--planta", type=int, default=None, help="testa focando numa planta")
    p.add_argument("--saida", default=None, help="salva o relatório num arquivo texto")
    args = p.parse_args()

    os.environ["DATABASE_URL"] = f"sqlite:///{args.banco}"
    os.environ["AUTO_CREATE_TABLES"] = "true"

    # O log de cada requisição polui o relatório; aqui só interessam os tempos.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("app").setLevel(logging.WARNING)

    from fastapi.testclient import TestClient

    from app.main import app

    cliente = TestClient(app)
    r = cliente.post("/api/v1/auth/login", data={"username": "admin@empresa.com", "password": "admin123"})
    if r.status_code != 200:
        escrever(f"Falha no login: {r.status_code} {r.text[:200]}")
        sys.exit(1)
    cabecalhos = {"Authorization": f"Bearer {r.json()['access_token']}"}
    if args.planta:
        cabecalhos["X-Planta-Id"] = str(args.planta)

    total = cliente.get("/api/v1/ativos", params={"size": 1}, headers=cabecalhos).json()["total"]
    escrever(f"Banco: {args.banco}   ativos: {total}   repeticoes: {args.repetir}")
    escrever()

    # (rótulo, método, caminho, params)
    cenarios = [
        ("Lista de ativos (1a pagina)", "get", "/api/v1/ativos", {"page": 1, "size": 20}),
        ("Lista de ativos (ultima pagina)", "get", "/api/v1/ativos", {"page": max(1, total // 20), "size": 20}),
        ("Ordenacao por patrimonio", "get", "/api/v1/ativos", {"size": 20, "sort": "patrimonio"}),
        ("Ordenacao por modelo", "get", "/api/v1/ativos", {"size": 20, "sort": "modelo"}),
        ("Filtro por status", "get", "/api/v1/ativos", {"size": 20, "status": "em_uso"}),
        ("Filtro por inventario", "get", "/api/v1/ativos", {"size": 20, "dominio": "impressora"}),
        ("Busca por texto", "get", "/api/v1/ativos", {"size": 20, "search": "Dell"}),
        ("Busca por numero de serie", "get", "/api/v1/ativos", {"size": 20, "search": "SN123"}),
        ("Relatorios - graficos", "get", "/api/v1/relatorios/graficos", {"dominio": "ti", "meses": 6}),
        ("KPIs do topo", "get", "/api/v1/dashboard/stats", {"dominio": "ti"}),
        ("Plantas (com contagem)", "get", "/api/v1/admin/plantas", {}),
        ("Impressoras", "get", "/api/v1/admin/dispositivos", {}),
        ("Cadastros auxiliares", "get", "/api/v1/categorias", {}),
        ("Auditoria", "get", "/api/v1/admin/auditoria", {"por_pagina": 50}),
        ("Etiquetas (templates)", "get", "/api/v1/admin/etiquetas", {}),
        ("Somente o total (size=1)", "get", "/api/v1/ativos", {"size": 1}),
    ]

    escrever(f"{'cenario':<34} {'min':>8} {'medio':>8} {'p95':>8} {'max':>8}  {'HTTP':>5}")
    escrever("-" * 82)
    problemas = []
    for rotulo, metodo, caminho, params in cenarios:
        tempos, codigo = [], 0
        for _ in range(args.repetir):
            t = time.perf_counter()
            resp = getattr(cliente, metodo)(caminho, params=params, headers=cabecalhos)
            tempos.append((time.perf_counter() - t) * 1000)
            codigo = resp.status_code
        tempos.sort()
        p95 = tempos[min(len(tempos) - 1, int(len(tempos) * 0.95))]
        media = statistics.mean(tempos)
        marca = ""
        if media > 500:
            marca = "  <-- LENTO"
            problemas.append(rotulo)
        elif media > 200:
            marca = "  <-- atencao"
        escrever(f"{rotulo:<34} {tempos[0]:>7.0f}ms {media:>7.0f}ms {p95:>7.0f}ms {tempos[-1]:>7.0f}ms  {codigo:>5}{marca}")

    escrever()
    if problemas:
        escrever("Cenarios acima de 500ms (candidatos a otimizacao):")
        for x in problemas:
            escrever("   - " + x)
    else:
        escrever("Nenhum cenario acima de 500ms.")

    if args.saida:
        with open(args.saida, "w", encoding="utf-8") as fh:
            fh.write("\n".join(LINHAS) + "\n")
        print(f"\nRelatorio salvo em {args.saida}")


if __name__ == "__main__":
    main()
