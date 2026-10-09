"""Zera a instalação para refazer a configuração inicial.

**Não depende das bibliotecas do sistema.** O caso comum (SQLite) usa só o que
vem no Python: ler o `.env`, copiar o arquivo e apagá-lo. Assim funciona com o
`python` do PATH, sem precisar lembrar de chamar o Python do `.venv` — que foi
exatamente o tropeço na primeira tentativa de uso.

Ordem das operações (a ordem importa):

1. **Cópia de segurança** do banco e do `.env` para `backups/`. Se ela falhar,
   o script PARA. Sem isso, um erro no meio deixaria o sistema sem banco e sem
   volta.
2. Apaga os dados (o arquivo, no SQLite; as tabelas, nos bancos de servidor).
3. Remove o marcador `.instalado`, para o assistente voltar a abrir.
4. Recolhe os arquivos de marca da empresa (logo/favicon).

Uso:

    python scripts/reiniciar_setup.py --listar     # só mostra o que será apagado
    python scripts/reiniciar_setup.py --confirmo   # faz, com backup

O `--confirmo` é obrigatório de propósito: é um comando que apaga tudo.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ARQUIVO_ENV = RAIZ / ".env"
ARQUIVO_MARCADOR = RAIZ / ".instalado"
PASTA_MARCA = RAIZ / "media" / "empresa"
PASTA_BACKUPS = RAIZ / "backups"

# Mesmo padrão do app/config.py — usado quando o .env não define nada.
URL_PADRAO = "sqlite:///./estoque.db"


# ---------------------------------------------------------------------------
# Leitura do .env (sem dependências)
# ---------------------------------------------------------------------------
def ler_env() -> dict[str, str]:
    """Lê o .env como pares chave/valor, ignorando comentários."""
    if not ARQUIVO_ENV.exists():
        return {}
    valores: dict[str, str] = {}
    for linha in ARQUIVO_ENV.read_text(encoding="utf-8").splitlines():
        limpa = linha.strip()
        if not limpa or limpa.startswith("#") or "=" not in limpa:
            continue
        chave, _, valor = limpa.partition("=")
        valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def url_do_banco() -> str:
    return ler_env().get("DATABASE_URL") or URL_PADRAO


def alvo_sqlite(url: str) -> Path | None:
    """Caminho do arquivo quando o banco é SQLite (None nos bancos de servidor)."""
    if not url.startswith("sqlite"):
        return None
    caminho = url.split("sqlite:///", 1)[-1]
    if not caminho or caminho == ":memory:":
        return None
    p = Path(caminho)
    return p if p.is_absolute() else (RAIZ / p).resolve()


def _tamanho(caminho: Path) -> str:
    if not caminho.exists():
        return "—"
    b = float(caminho.stat().st_size)
    for u in ("B", "KB", "MB", "GB"):
        if b < 1024 or u == "GB":
            return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} GB"


# ---------------------------------------------------------------------------
def listar() -> dict:
    url = url_do_banco()
    arquivo = alvo_sqlite(url)
    arquivos_marca = sorted(PASTA_MARCA.glob("*")) if PASTA_MARCA.exists() else []

    print("\n  O que será apagado:")
    if arquivo:
        print(f"    banco SQLite ............... {arquivo}")
        print(f"    tamanho do arquivo ......... {_tamanho(arquivo)}")
    else:
        print(f"    banco no servidor .......... {url.split('@')[-1]}")
    print(f"    marcador de instalação ..... {ARQUIVO_MARCADOR}")
    print(f"    arquivos de marca .......... {len(arquivos_marca)} em {PASTA_MARCA}")

    print("\n  O que será PRESERVADO:")
    print("    arquivo .env (com seus segredos)")
    print("    pasta de backups")
    print("    códigos-fonte e configuração do sistema")

    if arquivo and arquivo.exists():
        try:
            con = sqlite3.connect(arquivo)
            print("\n  Conteúdo que será perdido:")
            for tabela in ("ativos", "produtos", "movimentacoes", "manutencoes",
                           "usuarios", "plantas", "transferencias"):
                try:
                    n = con.execute(f'SELECT COUNT(*) FROM "{tabela}"').fetchone()[0]
                    print(f"    {tabela:<16} {n:>7}")
                except sqlite3.Error:
                    pass
            con.close()
        except sqlite3.Error as e:
            print(f"    (não foi possível ler as contagens: {e})")

    return {"arquivo": arquivo, "marca": arquivos_marca, "url": url}


def backup(arquivo: Path | None) -> None:
    """Cópia de segurança — se ela não puder ser feita, o script desiste."""
    PASTA_BACKUPS.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    if arquivo and arquivo.exists():
        copia = PASTA_BACKUPS / f"estoque-antes-do-reset_{carimbo}.db"
        shutil.copy2(arquivo, copia)
        print(f"  [ok] Banco copiado para {copia.name} ({_tamanho(copia)})")

    if ARQUIVO_ENV.exists():
        copia_env = PASTA_BACKUPS / f"env-antes-do-reset_{carimbo}.txt"
        shutil.copy2(ARQUIVO_ENV, copia_env)
        print(f"  [ok] .env copiado para {copia_env.name}")


def _apagar_tabelas_do_servidor(url: str) -> None:
    """Bancos de servidor usam o SQLAlchemy — que vive no .venv."""
    try:
        from sqlalchemy import create_engine, inspect
    except ModuleNotFoundError:
        print("\n  [ERRO] Para apagar um banco de servidor é preciso o ambiente do sistema:")
        print(r"         .venv\Scripts\python.exe scripts\reiniciar_setup.py --confirmo")
        print("         (no Linux: .venv/bin/python scripts/reiniciar_setup.py --confirmo)\n")
        raise SystemExit(1) from None

    sys.path.insert(0, str(RAIZ))
    from app.models import Base

    motor = create_engine(url, pool_pre_ping=True)
    try:
        existentes = inspect(motor).get_table_names()
        Base.metadata.drop_all(motor)
        print(f"  [ok] {len(existentes)} tabela(s) removida(s) do servidor")
    finally:
        motor.dispose()


def apagar(info: dict) -> None:
    arquivo = info["arquivo"]

    if arquivo and arquivo.exists():
        try:
            arquivo.unlink()
            print(f"  [ok] Banco apagado: {arquivo.name}")
        except PermissionError:
            print("\n  [ERRO] O banco está em uso por outro processo.")
            print("         Feche a janela do run.bat (ou Ctrl+C) e rode de novo.")
            print("         A cópia de segurança já foi feita — nada se perdeu.\n")
            raise SystemExit(1) from None
    elif arquivo is None:
        _apagar_tabelas_do_servidor(info["url"])

    if ARQUIVO_MARCADOR.exists():
        ARQUIVO_MARCADOR.unlink()
        print("  [ok] Marcador de instalação removido")

    removidos = 0
    for f in info["marca"]:
        try:
            f.unlink()
            removidos += 1
        except OSError:
            pass
    if removidos:
        print(f"  [ok] {removidos} arquivo(s) de marca removido(s)")


def main() -> int:
    p = argparse.ArgumentParser(description="Zera a instalação para refazer o setup inicial.")
    p.add_argument("--listar", action="store_true", help="só mostra o que seria apagado")
    p.add_argument("--confirmo", action="store_true", help="confirma a exclusão (obrigatório)")
    args = p.parse_args()

    print("\n  === Reiniciar a configuração inicial ===")
    info = listar()

    if args.listar:
        print("\n  Nada foi apagado (--listar).\n")
        return 0

    if not args.confirmo:
        print("\n  Nada foi apagado.")
        print("  Para confirmar, rode com --confirmo\n")
        return 1

    print("\n  Fazendo cópia de segurança antes de apagar...")
    try:
        backup(info["arquivo"])
    except Exception as e:  # noqa: BLE001 — sem backup, não se apaga nada
        print(f"\n  [ERRO] Não foi possível fazer a cópia: {e}")
        print("         Nada foi apagado.\n")
        return 1

    print("\n  Apagando...")
    apagar(info)

    print("\n  Pronto. Ao rodar o run.bat, o assistente abre em /instalacao\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
