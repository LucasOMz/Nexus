"""Guarda: a imagem Docker tem tudo o que o código precisa?

## Por que existe

O usuário definiu: **tudo roda em Docker.** A partir disso, divergência entre
a máquina local e o container é defeito — porque só existe um ambiente que
importa.

Dois casos reais motivaram este guarda, e **nenhum dos dois era visível nos
1228 testes**, porque eles rodam no host:

| O que faltava | Sintoma |
|---|---|
| `requirements-snmp.txt` | monitor de impressoras só aceitava contador à mão |
| `pg_dump` e família | **backup nunca era criado**, e o compose anunciava que sim |

O segundo é o que dá o tom: *backup que falha em silêncio é pior que backup
que não existe* — ele dá a impressão de estar protegido.

## Como usar

    python scripts/auditar_docker.py            # relatório
    python scripts/auditar_docker.py --guardar  # sai 1 se houver divergência

`--guardar` é o que entra no gate: falha automática em vez de leitura atenta.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# O que a imagem PRECISA ter, por categoria.
# ---------------------------------------------------------------------------

# Binários que o código executa e cuja ausência quebra função de verdade —
# sem mensagem de erro útil para quem opera.
#
# Os demais (`lp`, `smbclient`, `cmd`) NÃO entram: o código verifica a
# ausência e responde com instrução clara ("confira se o pacote está
# instalado"). São opcionais por projeto.
BINARIOS_OBRIGATORIOS = {
    "pg_dump": "backup do PostgreSQL",
    "pg_restore": "restauração do backup",
    "psql": "restauração e consultas administrativas",
}

# Pacotes Python que a imagem DEVE instalar.
REQUIREMENTS_OBRIGATORIOS = {"requirements.txt", "requirements-snmp.txt"}

# Opcionais de propósito — a ausência é correta.
REQUIREMENTS_OPCIONAIS = {
    "requirements-dev.txt": "só desenvolvimento e testes",
    "requirements-drivers.txt": "SQL Server, precisa compilar, opcional",
}


def _ler(caminho: pathlib.Path) -> str:
    return caminho.read_text(encoding="utf-8", errors="ignore")


def binarios_no_codigo() -> dict[str, set[str]]:
    """Programas externos que o código executa, e onde."""
    achados: dict[str, set[str]] = {}
    padroes = [
        r"subprocess\.\w+\(\s*\[?\s*[\"']([A-Za-z0-9_\-]+)",
        r"shutil\.which\(\s*[\"']([A-Za-z0-9_\-]+)",
    ]
    for p in (RAIZ / "app").rglob("*.py"):
        c = _ler(p)
        for padrao in padroes:
            for m in re.finditer(padrao, c):
                achados.setdefault(m.group(1), set()).add(p.name)
    return achados


def instalados_no_dockerfile() -> tuple[set[str], str]:
    """Requirements instalados, e o texto do Dockerfile."""
    c = _ler(RAIZ / "Dockerfile")
    return set(re.findall(r"requirements[\w\-]*\.txt", c)), c


def binarios_no_dockerfile(texto: str) -> set[str]:
    """Binários que o Dockerfile instala via apt.

    Procura pelos nomes conhecidos no texto — suficiente para o que este
    guarda verifica, e sem precisar interpretar o Dockerfile.
    """
    return {b for b in BINARIOS_OBRIGATORIOS if b.replace("pg_", "postgresql-") in texto
            or b in texto}


def verificar() -> list[str]:
    """Os problemas encontrados. Lista vazia = tudo certo."""
    problemas: list[str] = []

    instalados, dockerfile = instalados_no_dockerfile()

    # --- 1. Requirements obrigatórios -----------------------------------
    for arq in sorted(REQUIREMENTS_OBRIGATORIOS):
        if not (RAIZ / arq).exists():
            continue  # não existe no projeto: nada a exigir
        if arq not in instalados:
            deps = [
                linha.strip() for linha in _ler(RAIZ / arq).split("\n")
                if linha.strip() and not linha.strip().startswith("#")
                and not linha.startswith("-r")
            ]
            problemas.append(
                f"`{arq}` não é instalado pela imagem — o Dockerfile só instala "
                f"{sorted(instalados)}. Pacotes que faltam: {', '.join(deps)}"
            )

    # --- 2. Binários obrigatórios ---------------------------------------
    #
    # O Dockerfile instala o cliente do PostgreSQL como
    # `postgresql-client-16`, que traz `pg_dump`, `pg_restore` e `psql` de
    # uma vez. Procurar pelo nome do pacote, e não pelo binário, é o que
    # corresponde à realidade da instalação.
    versao_cliente = _versao_do_cliente_pg(dockerfile)
    tem_cliente_pg = versao_cliente is not None
    no_codigo = binarios_no_codigo()
    for binario, para_que in BINARIOS_OBRIGATORIOS.items():
        if binario in no_codigo and not tem_cliente_pg:
            problemas.append(
                f"`{binario}` é usado por {sorted(no_codigo[binario])} para "
                f"{para_que}, e a imagem não instala o cliente do PostgreSQL "
                f"(`postgresql-client`, `postgresql-client-N`, ou cópia da "
                f"imagem `postgres:N`). Sem ele, a função falha no container."
            )

    # --- 3. Versão do cliente x servidor ---------------------------------
    #
    # `pg_dump` recusa dumpar servidor mais novo que ele.
    #
    # Este é o aviso que mais importa quando a rede corporativa obriga a usar
    # o cliente da Debian: o deploy sobe, e o backup **continua** sem
    # funcionar — agora por incompatibilidade de versão, e não por ausência
    # do binário. Silencioso, portanto.
    versao_servidor = _versao_do_postgres_no_compose()
    if versao_servidor and versao_cliente and versao_cliente < versao_servidor:
        problemas.append(
            f"o compose usa PostgreSQL {versao_servidor}, mas a imagem traz o "
            f"cliente {versao_cliente}. `pg_dump` recusa dumpar servidor mais "
            f"novo que ele — **o backup não vai funcionar**. O deploy sobe, e a "
            f"falha só aparece na hora de restaurar. Considere `Dockerfile.pg16`, "
            f"que copia o cliente 16 da imagem oficial do Postgres."
        )

    # --- 4. Arquivos copiados existem ------------------------------------
    for origem in re.findall(r"^COPY\s+(\S+)", dockerfile, re.M):
        if origem.startswith("--"):
            continue
        alvo = RAIZ / origem.rstrip("/")
        if not alvo.exists() and origem not in (".", "./"):
            problemas.append(f"o Dockerfile copia `{origem}`, que não existe")

    return problemas


def _versao_do_cliente_pg(texto: str) -> int | None:
    """A versão do cliente PostgreSQL que o Dockerfile traz.

    Três formas, e cada uma diz uma versão diferente:

    1. `postgresql-client-16` — versão explícita no nome do pacote;
    2. `COPY --from=... postgres:16` — cópia da imagem oficial;
    3. `postgresql-client` — o **padrão da Debian**, que nesta base é 15.

    O caso 3 é o que engana: parece que resolveu, e o backup continua sem
    funcionar contra um servidor 16. Por isso ele devolve o número — para o
    guarda poder comparar com a versão do servidor.
    """
    # 1. Pacote com versão explícita.
    m = re.search(r"postgresql-client-(\d+)", texto)
    if m:
        return int(m.group(1))

    # 2. Cópia de uma imagem oficial `postgres:N`.
    #
    # Três formas, e todas aparecem na prática:
    #   COPY --from=postgres:16 /usr/lib/postgresql/16/bin/ ...
    #   FROM postgres:16 AS origem        (estágio fonte, com COPY depois)
    m = re.search(r"from=[\w./:-]*postgres:(\d+)", texto, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"^\s*FROM\s+postgres:(\d+)", texto, re.I | re.M)
    if m:
        return int(m.group(1))

    # 3. Pacote sem versão: o que a Debian da base entrega.
    #
    # `python:3.12-slim` é bookworm, e bookworm traz o cliente 15. Isto é um
    # valor **esperado**, não lido da imagem — se a base mudar, muda junto.
    if re.search(r"apt-get install[^\n]*\bpostgresql-client\b(?!-)", texto):
        return 15

    return None


def _versao_do_postgres_no_compose() -> int | None:
    compose = RAIZ / "docker-compose.yml"
    if not compose.exists():
        return None
    m = re.search(r"image:\s*postgres:(\d+)", _ler(compose))
    return int(m.group(1)) if m else None


def relatorio() -> None:
    instalados, _ = instalados_no_dockerfile()

    print("=== REQUIREMENTS ===")
    for arq in sorted(RAIZ.glob("requirements*.txt")):
        if arq.name in instalados:
            estado = "OK "
        elif arq.name in REQUIREMENTS_OPCIONAIS:
            estado = "OPC"
        else:
            estado = "FALTA"
        nota = REQUIREMENTS_OPCIONAIS.get(arq.name, "")
        print(f"  [{estado:<5}] {arq.name:<26} {nota}")

    print()
    print("=== BINÁRIOS EXTERNOS citados pelo código ===")
    no_codigo = binarios_no_codigo()
    _, dockerfile = instalados_no_dockerfile()
    tem_pg = _versao_do_cliente_pg(dockerfile) is not None
    for binario in sorted(no_codigo):
        if binario in BINARIOS_OBRIGATORIOS:
            estado = "OK " if tem_pg else "FALTA"
        else:
            estado = "OPC"
        onde = ", ".join(sorted(no_codigo[binario])[:2])
        print(f"  [{estado:<5}] {binario:<14} ({onde})")

    print()
    print("=== POSTGRESQL ===")
    v = _versao_do_postgres_no_compose()
    cli = _versao_do_cliente_pg(dockerfile)
    nota = "  <- INCOMPATIVEL: o backup nao vai funcionar" if (v and cli and cli < v) else ""
    print(f"  servidor (compose): {v or '?'}   cliente (imagem): {cli or '?'}{nota}")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Verifica se a imagem Docker tem o que o código precisa."
    )
    p.add_argument("--guardar", action="store_true",
                   help="sai com erro (1) se houver divergência")
    args = p.parse_args()

    if not args.guardar:
        relatorio()
        print()
        problemas = verificar()
        if problemas:
            print("=== DIVERGÊNCIAS ===")
            for x in problemas:
                print(f"  ! {x}")
        else:
            print("  Nenhuma divergência entre o código e a imagem.")
        return 0

    problemas = verificar()
    if problemas:
        print("A imagem Docker não tem tudo o que o código precisa:\n")
        for x in problemas:
            print(f"  ! {x}")
        print()
        print("Corrija o `Dockerfile` — em Docker, isto é o ambiente de produção.")
        return 1

    print(f"Docker OK — imagem e código em sincronia ({len(REQUIREMENTS_OBRIGATORIOS)} "
          f"conjuntos de dependências, {len(BINARIOS_OBRIGATORIOS)} binários).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
