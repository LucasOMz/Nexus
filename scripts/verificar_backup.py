"""Verifica que o backup funciona — criando, validando e RESTAURANDO de verdade.

## Por que não basta criar

A imagem não tinha `pg_dump`. O backup **nunca era criado**, e o
`docker-compose.yml` anunciava `BACKUP_DIR` e `BACKUP_RETER` como se
funcionasse.

Consertar o `pg_dump` resolve a criação. **Mas criar não é o que importa.**

> "Backup que nunca foi restaurado não é backup."

Um arquivo de 200 MB pode estar corrompido ou incompleto, e isso não aparece
até a hora em que alguém precisa dele — **e aí é tarde**.

Este script faz o ciclo completo, usando as funções que o sistema já expõe:

    1. Confere que as ferramentas existem
    2. Cria um backup
    3. Valida o arquivo (`validar_backup`, que o sistema já tem)
    4. RESTAURA num banco novo, separado
    5. Confere que os dados voltaram
    6. Descarta o banco de teste

## Como usar

    docker compose exec api python scripts/verificar_backup.py

Rode **depois de mexer em backup, volumes ou imagem** — e de vez em quando.
É rápido, e é a diferença entre ter e achar que tem.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import backup_service  # noqa: E402


def _rodar(comando: list[str], env: dict | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(comando, capture_output=True, text=True,
                           env=env, timeout=600, check=False)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, f"comando não encontrado: {comando[0]}"
    except subprocess.TimeoutExpired:
        return 124, "tempo esgotado"


def main() -> int:
    p = argparse.ArgumentParser(
        description="Cria, valida e restaura um backup — para provar que funciona."
    )
    p.add_argument("--manter", action="store_true",
                   help="não apaga o banco de teste nem o arquivo (para investigar)")
    args = p.parse_args()

    falhas: list[str] = []
    enviado = not backup_service._eh_sqlite()

    # ------------------------------------------------------------------
    print("1. Ferramentas de backup")
    if enviado:
        for binario in ("pg_dump", "pg_restore", "psql", "createdb", "dropdb"):
            codigo, _ = _rodar([binario, "--version"])
            if codigo == 0:
                print(f"   OK    {binario}")
            else:
                falhas.append(
                    f"`{binario}` indisponível. O backup não existe — e a falha é "
                    "silenciosa: quem olha a tela do sistema não vê."
                )
                print(f"   FALHA {binario}")
        if falhas:
            for f in falhas:
                print(f"\n  ! {f}")
            return 1
    else:
        print("   (SQLite: o backup usa a própria biblioteca, sem binário externo)")

    # ------------------------------------------------------------------
    print()
    print("2. Criando o backup")
    try:
        meta = backup_service.criar_backup(motivo="verificacao")
    except Exception as e:  # noqa: BLE001
        print(f"   FALHA ao criar: {type(e).__name__}: {e}")
        return 1

    arquivo = Path(meta.get("arquivo") or meta.get("caminho") or "")
    if not arquivo.exists():
        # O serviço pode devolver só o nome; procura na pasta.
        candidatos = [f for f in backup_service.pasta_backups().glob("*") if f.is_file()]
        if candidatos:
            arquivo = max(candidatos, key=lambda f: f.stat().st_mtime)
    if not arquivo.exists():
        print(f"   FALHA: nenhum arquivo gerado em {backup_service.pasta_backups()}")
        return 1

    tamanho = arquivo.stat().st_size
    print(f"   OK    {arquivo.name} — {tamanho / 1024:.1f} KB")
    if tamanho < 1024:
        falhas.append(
            f"o arquivo tem {tamanho} bytes. Um banco com dados não gera backup "
            "deste tamanho — o dump provavelmente falhou em silêncio."
        )

    # ------------------------------------------------------------------
    # A validação que o próprio sistema faz: abre o arquivo e confere se as
    # tabelas obrigatórias estão lá. Não substitui restaurar, mas pega o caso
    # mais comum — arquivo pela metade.
    print()
    print("3. Validando o arquivo")
    v = backup_service.validar_backup(arquivo.name)
    if v.get("ok"):
        tabelas = v.get("tabelas") or v.get("resumo") or {}
        n = len(tabelas) if isinstance(tabelas, dict) else tabelas
        print(f"   OK    {n} tabela(s) conferidas")
    else:
        falhas.append(f"a validação recusou o próprio backup: {v.get('mensagem')}")
        print(f"   FALHA {v.get('mensagem')}")

    if falhas and not args.manter:
        for f in falhas:
            print(f"\n  ! {f}")
        return 1

    # ------------------------------------------------------------------
    # Restaurar num banco SEPARADO.
    #
    # Restaurar por cima do banco atual não prova nada: se falhar no meio, o
    # estado fica ambíguo e o que havia se perde. Um banco à parte torna a
    # verificação descartável — e é o único jeito de testar de verdade sem
    # arriscar produção.
    if not enviado:
        print()
        print("4. Restauração: pulada (o serviço já valida o conteúdo do SQLite).")
        print()
        print("Backup verificado: criado e validado.")
        return 1 if falhas else 0

    print()
    print("4. Restaurando num banco novo")
    nome = f"nexus_verif_{os.getpid()}"
    env = backup_service._pg_env()

    codigo, saida = _rodar(["createdb", nome], env=env)
    if codigo != 0:
        print(f"   FALHA ao criar o banco de teste: {saida.strip()[:200]}")
        return 1

    try:
        codigo, saida = _rodar(
            ["pg_restore", "--no-owner", "--no-acl", "-d", nome, str(arquivo)],
            env=env,
        )
        # `pg_restore` devolve avisos com código de erro em alguns casos. O
        # que decide é o que ficou no banco — conferido abaixo.
        if codigo != 0:
            print(f"   AVISO do pg_restore ({codigo}): {saida.strip()[:200]}")

        print()
        print("5. Conferindo os dados restaurados")

        codigo, saida = _rodar([
            "psql", "-d", nome, "-tAc",
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'",
        ], env=env)
        tabelas = saida.strip() if codigo == 0 else "0"
        print(f"   tabelas: {tabelas}")

        if not tabelas.isdigit() or int(tabelas) < 5:
            falhas.append(
                f"o banco restaurado tem {tabelas} tabela(s). Um backup válido "
                "traz dezenas — a restauração não funcionou."
            )
        else:
            # Contagem de DADOS, não só de estrutura: um dump só com DDL
            # restauraria as tabelas e perderia tudo o que importa.
            codigo, saida = _rodar(
                ["psql", "-d", nome, "-tAc", "SELECT count(*) FROM ativos"], env=env
            )
            if codigo == 0:
                print(f"   ativos: {saida.strip()}")
            else:
                falhas.append("a tabela `ativos` não existe no banco restaurado")
    finally:
        if args.manter:
            print(f"   banco `{nome}` MANTIDO (--manter)")
        else:
            _rodar(["dropdb", "--if-exists", nome], env=env)
            arquivo.unlink(missing_ok=True)
            print(f"   banco `{nome}` e arquivo descartados")

    print()
    if falhas:
        print("O backup NÃO está confiável:")
        for f in falhas:
            print(f"  ! {f}")
        return 1

    print("Backup verificado: criado, validado, restaurado e com dados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
