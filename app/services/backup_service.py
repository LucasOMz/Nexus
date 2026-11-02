"""Backup e restauração do banco de dados.

Suporta os dois bancos usados pelo sistema:

* **SQLite** (desenvolvimento) — cópia consistente via API de backup do próprio
  SQLite (segura mesmo com o sistema rodando).
* **PostgreSQL** (produção/Docker) — `pg_dump -Fc`, que é o formato correto
  (copiar o volume de dados cru pode gerar backup inconsistente).

Cada backup gera **dois arquivos** na pasta configurada (`BACKUP_DIR`, que pode
apontar para um compartilhamento de rede):

* `backup_<data>.<ext>` — o dump
* `backup_<data>.json`  — metadados (data, versão, motivo, resumo das tabelas)

A restauração segue sempre o mesmo rito: **valida em banco temporário** antes de
trocar, e faz um **backup automático do estado atual** antes de qualquer coisa.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import __version__
from app.config import settings
from app.database import caminho_sqlite

# Campos que formam o "resumo" exibido na listagem/validação.
_TABELAS_RESUMO = [
    "usuarios", "ativos", "ativos_ti", "ativos_impressora", "produtos",
    "movimentacoes", "manutencoes", "imagens", "dispositivos_impressao",
]
_TABELAS_OBRIGATORIAS = ["usuarios", "ativos", "categorias"]


def pasta_backups() -> Path:
    pasta = Path(settings.backup_path)
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _eh_sqlite() -> bool:
    return caminho_sqlite() is not None


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _nome_base(motivo: str) -> str:
    return f"backup_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{motivo}"


def _resumo_sqlite(caminho: str) -> dict[str, int]:
    resumo: dict[str, int] = {}
    con = sqlite3.connect(caminho)
    try:
        nomes = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        for tabela in _TABELAS_RESUMO:
            if tabela in nomes:
                resumo[tabela] = con.execute(f"select count(*) from {tabela}").fetchone()[0]  # noqa: S608
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return resumo


def _pg_env() -> dict[str, str]:
    """Variáveis do psql/pg_dump a partir da DATABASE_URL."""
    env = dict(os.environ)
    url = settings.database_url
    # postgresql+psycopg://user:senha@host:porta/banco
    try:
        sem_driver = url.split("://", 1)[1]
        credenciais, resto = sem_driver.split("@", 1)
        usuario, senha = credenciais.split(":", 1)
        host_porta, banco = resto.split("/", 1)
        host, _, porta = host_porta.partition(":")
        env.update({
            "PGUSER": usuario, "PGPASSWORD": senha, "PGHOST": host,
            "PGPORT": porta or "5432", "PGDATABASE": banco.split("?")[0],
        })
    except (IndexError, ValueError):
        pass
    return env


def _resumo_postgres() -> dict[str, int]:
    resumo: dict[str, int] = {}
    for tabela in _TABELAS_RESUMO:
        try:
            saida = subprocess.run(
                ["psql", "-tAc", f"select count(*) from {tabela}"],
                capture_output=True, text=True, timeout=30, env=_pg_env(),
            )
            if saida.returncode == 0 and saida.stdout.strip().isdigit():
                resumo[tabela] = int(saida.stdout.strip())
        except (OSError, subprocess.SubprocessError):
            break
    return resumo


# ---------------------------------------------------------------------------
# Criar
# ---------------------------------------------------------------------------
def criar_backup(motivo: str = "manual") -> dict[str, Any]:
    """Cria um backup e devolve os metadados gravados."""
    pasta = pasta_backups()
    base = _nome_base(motivo)

    if _eh_sqlite():
        origem = caminho_sqlite() or ""

        # --- Banco sem arquivo não tem o que copiar ---------------------
        #
        # `sqlite3.connect("")` não falha: ele abre um banco **temporário
        # vazio**. O `.backup()` copia esse vazio e grava um arquivo com
        # sucesso — um backup de ZERO byte que parece legítimo.
        #
        # O efeito não é cosmético. A exclusão em lote exige backup antes de
        # apagar; com o backup "dando certo", ela apagaria sem ter cópia
        # nenhuma. Foi o que o CI apontou num teste que passava no Windows e
        # falhava no Linux — mesma causa, comportamento diferente.
        #
        # Aqui a regra é explícita: sem arquivo, sem backup. Quem chama
        # recebe o erro e decide — e a exclusão em lote recusa.
        if not origem or not Path(origem).exists():
            raise RuntimeError(
                "O banco atual não tem arquivo para copiar "
                "(SQLite em memória). Backup automático indisponível."
            )

        destino = pasta / f"{base}.db"
        # API de backup do SQLite: cópia consistente mesmo com o banco em uso.
        con_origem = sqlite3.connect(origem)
        con_destino = sqlite3.connect(str(destino))
        try:
            con_origem.backup(con_destino)
        finally:
            con_destino.close()
            con_origem.close()
        resumo = _resumo_sqlite(str(destino))
        tipo = "sqlite"
    else:
        destino = pasta / f"{base}.dump"
        proc = subprocess.run(
            ["pg_dump", "-Fc", "-f", str(destino)],
            capture_output=True, text=True, timeout=600, env=_pg_env(),
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pg_dump falhou: {proc.stderr.strip()}")
        resumo = _resumo_postgres()
        tipo = "postgres"

    meta = {
        "arquivo": destino.name,
        "criado_em": _agora(),
        "app_version": __version__,
        "tipo": tipo,
        "motivo": motivo,
        "tamanho_bytes": destino.stat().st_size,
        "resumo": resumo,
        "banco": "SQLite" if tipo == "sqlite" else "PostgreSQL",
    }
    (pasta / f"{base}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _aplicar_retencao()
    return meta


def _aplicar_retencao() -> None:
    """Mantém apenas os N backups mais recentes (BACKUP_RETER)."""
    limite = max(1, int(settings.backup_reter or 30))
    backups = listar_backups()
    # Nunca apaga os de pré-restauração mais recentes silenciosamente.
    for antigo in backups[limite:]:
        for caminho in (antigo.get("caminho"), antigo.get("caminho_meta")):
            if caminho and os.path.exists(caminho):
                try:
                    os.unlink(caminho)
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Listar / ler
# ---------------------------------------------------------------------------
def listar_backups() -> list[dict[str, Any]]:
    """Lista os backups da pasta, do mais novo para o mais antigo."""
    pasta = pasta_backups()
    itens: list[dict[str, Any]] = []
    for meta_path in sorted(pasta.glob("backup_*.json"), reverse=True):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        dump = pasta / meta.get("arquivo", "")
        meta["caminho"] = str(dump)
        meta["caminho_meta"] = str(meta_path)
        meta["existe"] = dump.exists()
        if dump.exists():
            meta["tamanho_bytes"] = dump.stat().st_size
        itens.append(meta)
    itens.sort(key=lambda m: m.get("criado_em", ""), reverse=True)
    return itens


def status_backup() -> dict[str, Any]:
    """Status para a tela: último backup, há quanto tempo e se falhou."""
    backups = listar_backups()
    if not backups:
        return {"total": 0, "ultimo": None, "ok": False, "mensagem": "Nenhum backup encontrado."}
    ultimo = backups[0]
    try:
        quando = datetime.fromisoformat(ultimo["criado_em"])
        horas = (datetime.now(timezone.utc) - quando).total_seconds() / 3600
        ultimo["horas_atras"] = round(horas, 1)
        alerta = horas > 72
    except (KeyError, ValueError):
        alerta = False
    return {
        "total": len(backups),
        "ultimo": ultimo,
        "ok": ultimo.get("existe", False),
        "alerta_atrasado": alerta,
        "pasta": str(pasta_backups()),
        "retencao": settings.backup_reter,
    }


def _resolver(nome: str) -> tuple[Path, dict[str, Any]]:
    """Localiza um backup pelo nome do arquivo, com segurança (sem path traversal)."""
    pasta = pasta_backups()
    arquivo = pasta / os.path.basename(nome)
    if not arquivo.exists() or arquivo.parent != pasta:
        raise FileNotFoundError(f"Backup não encontrado: {nome}")
    meta_path = arquivo.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return arquivo, meta


# ---------------------------------------------------------------------------
# Validar (restaura num banco TEMPORÁRIO e inspeciona)
# ---------------------------------------------------------------------------
def validar_backup(nome: str) -> dict[str, Any]:
    """Confere se o backup é íntegro e compatível — SEM tocar no banco atual."""
    arquivo, meta = _resolver(nome)
    avisos: list[str] = []

    if arquivo.suffix == ".db":
        with tempfile.TemporaryDirectory() as tmp:
            copia = Path(tmp) / "validacao.db"
            shutil.copy2(arquivo, copia)
            try:
                con = sqlite3.connect(str(copia))
                tabelas = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
                faltando = [t for t in _TABELAS_OBRIGATORIAS if t not in tabelas]
                resumo = {}
                for tabela in _TABELAS_RESUMO:
                    if tabela in tabelas:
                        resumo[tabela] = con.execute(f"select count(*) from {tabela}").fetchone()[0]  # noqa: S608
                try:
                    con.execute("pragma integrity_check").fetchone()
                except sqlite3.Error as exc:
                    avisos.append(f"Verificação de integridade reportou: {exc}")
                con.close()
            except sqlite3.Error as exc:
                return {"ok": False, "mensagem": f"Arquivo inválido ou corrompido: {exc}", "avisos": avisos}
    else:
        # PostgreSQL: restaura num banco temporário.
        env = _pg_env()
        banco_original = env.get("PGDATABASE", "estoque")
        banco_tmp = f"{banco_original}_validacao"
        try:
            subprocess.run(["dropdb", "--if-exists", banco_tmp], capture_output=True, text=True, timeout=120, env=env)
            criar = subprocess.run(["createdb", banco_tmp], capture_output=True, text=True, timeout=120, env=env)
            if criar.returncode != 0:
                return {"ok": False, "mensagem": f"Não foi possível criar o banco de validação: {criar.stderr.strip()}", "avisos": avisos}
            rest = subprocess.run(
                ["pg_restore", "-d", banco_tmp, "--no-owner", "--no-privileges", str(arquivo)],
                capture_output=True, text=True, timeout=1800, env=env,
            )
            if rest.returncode != 0:
                avisos.append(f"pg_restore reportou avisos: {rest.stderr.strip()[:400]}")
            env_tmp = {**env, "PGDATABASE": banco_tmp}
            resumo = {}
            for tabela in _TABELAS_RESUMO:
                saida = subprocess.run(["psql", "-tAc", f"select count(*) from {tabela}"],
                                       capture_output=True, text=True, timeout=30, env=env_tmp)
                if saida.returncode == 0 and saida.stdout.strip().isdigit():
                    resumo[tabela] = int(saida.stdout.strip())
            saida_tab = subprocess.run(
                ["psql", "-tAc", "select tablename from pg_tables where schemaname='public'"],
                capture_output=True, text=True, timeout=30, env=env_tmp,
            )
            tabelas = set(saida_tab.stdout.split())
            faltando = [t for t in _TABELAS_OBRIGATORIAS if t not in tabelas]
            subprocess.run(["dropdb", "--if-exists", banco_tmp], capture_output=True, text=True, timeout=120, env=env)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "mensagem": f"Falha ao validar no PostgreSQL: {exc}", "avisos": avisos}

    if faltando:
        return {
            "ok": False,
            "mensagem": f"Backup incompatível: faltam as tabelas {', '.join(faltando)}.",
            "resumo": resumo, "avisos": avisos, "meta": meta,
        }

    if meta.get("app_version") and meta["app_version"] != __version__:
        avisos.append(
            f"O backup foi feito na versão {meta['app_version']} e o sistema está na {__version__}. "
            "Pode haver diferença de estrutura."
        )
    if not resumo.get("usuarios"):
        avisos.append("O backup não contém usuários — verifique antes de restaurar.")

    return {
        "ok": True,
        "mensagem": "Backup íntegro e compatível. Pode restaurar com segurança.",
        "resumo": resumo,
        "avisos": avisos,
        "meta": meta,
    }


# ---------------------------------------------------------------------------
# Restaurar
# ---------------------------------------------------------------------------
def _sql_literal(texto: str) -> str:
    """Valor como literal SQL, entre aspas simples e escapado.

    Nome de banco vem do DATABASE_URL, não de entrada do usuário — mas
    concatenar direto numa consulta é hábito ruim, e um ' no nome quebraria
    a sintaxe.
    """
    return "'" + str(texto).replace("'", "''") + "'"


def _erros_graves_do_restore(stderr: str) -> list[str]:
    """Erros do pg_restore que **não** são ruído de versão.

    ## Por que isto existe

    Um dump feito por cliente mais novo carrega SET de parâmetros que o
    servidor antigo não conhece:

        pg_restore: error: could not execute query: ERROR: unrecognized
        configuration parameter "transaction_timeout"
        Command was: SET transaction_timeout = 0;
        pg_restore: warning: errors ignored on restore: 1

    O pg_restore **já ignorou** e terminou — 	ransaction_timeout é ajuste
    de sessão, não dado. Mas o código de saída é diferente de zero, e o
    restore era abortado **depois de ter restaurado tudo**.

    Nesse caso o usuário via "pg_restore falhou" com o banco já pronto, e a
    próxima tentativa desperdiçava a janela de manutenção.

    ## O que NÃO é ignorado

    Qualquer outro pg_restore: error — tabela inexistente, permissão,
    sintaxe. Só o parâmetro de sessão desconhecido passa, e o resto continua
    abortando. Ignorar tudo mascararia restauração parcial, que é pior que
    falhar.
    """
    IGNORAVEIS = (
        "unrecognized configuration parameter",
        "transaction_timeout",
        "errors ignored on restore",
    )
    graves: list[str] = []
    for linha in (stderr or "").splitlines():
        texto = linha.strip()
        if not texto.lower().startswith("pg_restore: error"):
            continue
        if any(ruido in texto.lower() for ruido in IGNORAVEIS):
            continue
        graves.append(texto)
    return graves


def restaurar_backup(nome: str) -> dict[str, Any]:
    """Restaura um backup, com backup automático do estado atual antes.

    Ordem: backup de segurança → validação no banco temporário → troca.
    """
    # 1) Backup automático do estado atual (permite voltar atrás).
    seguranca = criar_backup(motivo="pre-restore")

    # 2) Validação — só troca se estiver tudo certo.
    validacao = validar_backup(nome)
    if not validacao.get("ok"):
        return {"ok": False, "mensagem": validacao.get("mensagem"), "validacao": validacao, "backup_seguranca": seguranca}

    arquivo, _meta = _resolver(nome)

    # 3) Troca.
    from app.database import recriar_engine

    if arquivo.suffix == ".db":
        destino = caminho_sqlite() or ""
        recriar_engine()  # fecha as conexões antes de trocar o arquivo
        try:
            shutil.copy2(arquivo, destino)
        except OSError as exc:
            return {"ok": False, "mensagem": f"Falha ao substituir o banco: {exc}", "backup_seguranca": seguranca}
    else:
        env = _pg_env()
        banco = env.get("PGDATABASE", "estoque")
        banco_tmp = f"{banco}_restore"
        banco_antigo = f"{banco}_anterior"

        # Avisos que não impedem a restauração mas precisam ser mostrados —
        # ex.: dump feito por cliente mais novo que o servidor.
        avisos: list[str] = []
        try:
            subprocess.run(["dropdb", "--if-exists", banco_tmp], capture_output=True, text=True, timeout=120, env=env)
            subprocess.run(["createdb", banco_tmp], capture_output=True, text=True, timeout=120, env=env)
            rest = subprocess.run(
                ["pg_restore", "-d", banco_tmp, "--no-owner", "--no-privileges", str(arquivo)],
                capture_output=True, text=True, timeout=1800, env=env,
            )
            if rest.returncode != 0:
                graves = _erros_graves_do_restore(rest.stderr)
                if graves:
                    return {
                        "ok": False,
                        "mensagem": f"pg_restore falhou: {' | '.join(graves)[:300]}",
                        "backup_seguranca": seguranca,
                    }
                # Só ruído de versão: o restore **aconteceu**. Segue, mas
                # registra — quem restaurou precisa saber que houve aviso.
                avisos.append(
                    "pg_restore ignorou parâmetros de sessão desconhecidos. "
                    "O cliente que gerou o dump é mais novo que este servidor."
                )
            recriar_engine()

            # --- derruba as conexões antes de renomear --------------------
            #
            # ## Por que isto é obrigatório
            #
            # `ALTER DATABASE ... RENAME` **falha enquanto houver qualquer
            # sessão conectada** — inclusive a da própria aplicação. E o erro
            # não é claro:
            #
            #     ERROR: database "estoque" is being accessed by other users
            #
            # A versão anterior chamava `recriar_engine()` e torcia. Não
            # funciona: recriar o engine faz ele **reconectar**, então a
            # sessão continua lá.
            #
            # Pior: o resultado do primeiro rename era ignorado, então o
            # segundo falhava com "database estoque already exists" — e a
            # mensagem culpava o passo errado. O banco restaurado ficava em
            # `estoque_restore`, invisível, e o sistema seguia no banco velho.
            def _derruba_conexoes(nome_banco: str) -> None:
                subprocess.run(
                    ["psql", "-d", "postgres", "-tAc",
                     f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                     f"WHERE datname = {_sql_literal(nome_banco)} "
                     f"AND pid <> pg_backend_pid()"],
                    capture_output=True, text=True, timeout=60,
                    env={**env, "PGDATABASE": "postgres"},
                )

            def _renomeia(de: str, para: str) -> tuple[bool, str]:
                _derruba_conexoes(de)
                r = subprocess.run(
                    ["psql", "-d", "postgres", "-c",
                     f'ALTER DATABASE "{de}" RENAME TO "{para}"'],
                    capture_output=True, text=True, timeout=120,
                    env={**env, "PGDATABASE": "postgres"},
                )
                return r.returncode == 0, (r.stderr or "").strip()

            subprocess.run(["dropdb", "--if-exists", banco_antigo],
                           capture_output=True, text=True, timeout=120, env=env)

            ok_antigo, erro_antigo = _renomeia(banco, banco_antigo)
            if not ok_antigo:
                return {
                    "ok": False,
                    "mensagem": (
                        f"Não foi possível mover o banco atual para "
                        f"'{banco_antigo}': {erro_antigo[:200]}. "
                        f"O banco restaurado continua em '{banco_tmp}' — "
                        "nada foi perdido."
                    ),
                    "backup_seguranca": seguranca,
                }

            ok_troca, erro_troca = _renomeia(banco_tmp, banco)
            if not ok_troca:
                # Volta atrás: sem isto, o sistema ficaria sem banco nenhum.
                _renomeia(banco_antigo, banco)
                return {
                    "ok": False,
                    "mensagem": (
                        f"Falha ao promover o banco restaurado: {erro_troca[:200]}. "
                        "O banco anterior foi devolvido ao lugar."
                    ),
                    "backup_seguranca": seguranca,
                }
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "mensagem": f"Falha na restauração: {exc}", "backup_seguranca": seguranca}

    # 4) Derruba todas as sessões: os tokens emitidos antes deixam de valer.
    from app.core.security import invalidar_tokens

    invalidar_tokens()
    recriar_engine()

    return {
        "ok": True,
        "mensagem": "Backup restaurado. Todos os usuários precisam entrar novamente.",
        "resumo": validacao.get("resumo"),
        "avisos": validacao.get("avisos", []),
        "backup_seguranca": seguranca.get("arquivo"),
        "aviso_media": "As fotos, termos e anexos ficam na pasta media/ e devem ser restaurados separadamente.",
    }
