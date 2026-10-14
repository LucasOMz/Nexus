"""Estado da instalação: já foi configurado?

O sistema tem **dois modos**, decididos por um arquivo marcador (`.instalado`)
na raiz do projeto:

* **sem o marcador** → modo setup: só o assistente de configuração inicial
  responde. É aqui que se escolhe o banco, a empresa e o administrador.
* **com o marcador** → o sistema normal.

O marcador é um **arquivo**, não uma verificação no banco. Isso é deliberado:
"o banco está vazio" também acontece quando alguém apaga os dados — e nesse
caso o certo é avisar do problema, nunca reabrir o assistente. Com um arquivo,
a resposta é inequívoca.

Depois de instalado, o assistente **não roda de novo**. Sem isso, quem
alcançasse o endereço poderia apontar o sistema para um banco próprio.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Raiz do projeto (uma pasta acima de app/).
RAIZ = Path(__file__).resolve().parents[2]
ARQUIVO_ENV = RAIZ / ".env"
ARQUIVO_MARCADOR = RAIZ / ".instalado"
PASTA_EMPRESA = RAIZ / "media" / "empresa"


def instalado() -> bool:
    """O sistema já está configurado?

    ## 1. Configuração por ambiente (Docker, Kubernetes, systemd)

    Quando `NEXUS_CONFIG_POR_AMBIENTE=1`, a resposta é **sim** — sem olhar
    marcador nem banco.

    **Isto existe porque o assistente e o Docker não se conhecem.**

    O assistente grava `.env` e `.instalado` em `/app`. Em container, isso
    traz dois problemas somados:

    - **`/app` não é volume** — os dois arquivos somem quando o container é
      recriado, e o assistente reabre pedindo o login de fábrica;
    - **as variáveis do compose vencem o `.env`** — o assistente escreve a
      configuração e ela é descartada, porque `os.environ` tem precedência.

    O resultado era o pior possível: o assistente **abria**, coletava as
    escolhas, e **nenhuma delas valia**. Quem instalava via Docker concluía
    que o sistema ignorou o que foi configurado — e ignorou mesmo.

    ## 2. Marcador presente

    Instalação feita pelo assistente, em ambiente onde ele funciona.

    ## 3. Banco já tem estrutura

    Quem já usava o sistema antes do assistente não tem o marcador. Nesse
    caso a resposta vem do banco, e o marcador é criado para as próximas
    vezes.

    **Sem esta checagem, reiniciar depois de atualizar mostraria o
    assistente a quem já tem o sistema em uso** — dando a impressão de que
    os dados sumiram.
    """
    if os.environ.get("NEXUS_CONFIG_POR_AMBIENTE") == "1":
        return True

    if ARQUIVO_MARCADOR.exists():
        return True

    if _banco_ja_tem_estrutura():
        instante = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            marcar_instalado({
                "versao": "anterior ao assistente",
                "banco": "detectado automaticamente",
                "empresa": None,
                "detectado_em": instante,
            })
        except OSError:  # noqa: BLE001 — sem permissão de escrita não impede o uso
            pass
        return True

    return False


def _banco_ja_tem_estrutura() -> bool:
    """O banco configurado já tem as tabelas do sistema?

    Qualquer falha conta como "não tem": é melhor abrir o assistente do que
    travar o sistema por causa de uma checagem que não deu certo.
    """
    try:
        from sqlalchemy import create_engine, inspect

        from app.config import settings

        url = settings.database_url
        if url.startswith("sqlite"):
            # sqlite:///./estoque.db  ->  ./estoque.db
            caminho = url.split("sqlite:///", 1)[-1]
            if not caminho or caminho == ":memory:" or not Path(caminho).exists():
                return False

        argumentos = {"check_same_thread": False} if url.startswith("sqlite") else {}
        motor = create_engine(url, connect_args=argumentos, pool_pre_ping=True)
        try:
            with motor.connect():
                return "usuarios" in inspect(motor).get_table_names()
        finally:
            motor.dispose()
    except Exception:  # noqa: BLE001
        return False


def ler_marcador() -> dict[str, Any]:
    """Conteúdo do marcador (para diagnóstico). Nunca levanta exceção."""
    if not instalado():
        return {}
    try:
        return json.loads(ARQUIVO_MARCADOR.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"aviso": "marcador ilegível"}


def marcar_instalado(resumo: dict[str, Any]) -> None:
    """Grava o marcador. Só é chamado quando o setup termina com sucesso."""
    dados = {
        "instalado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "versao": resumo.get("versao"),
        "banco": resumo.get("banco"),
        "empresa": resumo.get("empresa"),
    }
    ARQUIVO_MARCADOR.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# .env
# ---------------------------------------------------------------------------
def ler_env() -> dict[str, str]:
    """Lê o .env como pares chave/valor (ignora comentários e linhas vazias)."""
    if not ARQUIVO_ENV.exists():
        return {}
    valores: dict[str, str] = {}
    for linha in ARQUIVO_ENV.read_text(encoding="utf-8").splitlines():
        limpa = linha.strip()
        if not limpa or limpa.startswith("#") or "=" not in limpa:
            continue
        chave, _, valor = limpa.partition("=")
        valores[chave.strip()] = valor.strip()
    return valores


def gravar_env(novos: dict[str, str]) -> None:
    """Escreve/atualiza chaves no .env **preservando** o que já existe.

    Reescrever o arquivo inteiro apagaria comentários e ajustes feitos à mão —
    o tipo de estrago que só se percebe quando algo para de funcionar.
    """
    linhas = ARQUIVO_ENV.read_text(encoding="utf-8").splitlines() if ARQUIVO_ENV.exists() else []
    faltando = dict(novos)

    saida: list[str] = []
    for linha in linhas:
        limpa = linha.strip()
        if limpa and not limpa.startswith("#") and "=" in limpa:
            chave = limpa.split("=", 1)[0].strip()
            if chave in faltando:
                saida.append(f"{chave}={faltando.pop(chave)}")
                continue
        saida.append(linha)

    if faltando:
        if saida and saida[-1].strip():
            saida.append("")
        saida.append("# --- Definido pelo assistente de configuração inicial ---")
        for chave, valor in faltando.items():
            saida.append(f"{chave}={valor}")

    ARQUIVO_ENV.write_text("\n".join(saida).rstrip() + "\n", encoding="utf-8")


def segredo_novo() -> str:
    """Segredo aleatório para JWT/QR — nada de valor padrão em produção."""
    return secrets.token_urlsafe(48)


# ---------------------------------------------------------------------------
# Marca da empresa (nome, logo, favicon)
# ---------------------------------------------------------------------------
def pasta_empresa() -> Path:
    PASTA_EMPRESA.mkdir(parents=True, exist_ok=True)
    return PASTA_EMPRESA


def salvar_arquivo_marca(nome: str, conteudo: bytes) -> str:
    """Grava logo/favicon e devolve o caminho relativo para guardar no banco.

    O nome ganha um sufixo aleatório: assim trocar a imagem não deixa a antiga
    presa no cache do navegador, que continuaria mostrando a versão anterior.
    """
    pasta = pasta_empresa()
    sufixo = Path(nome).suffix.lower() or ".png"
    if sufixo not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico"):
        sufixo = ".png"
    arquivo = f"{secrets.token_hex(6)}{sufixo}"
    (pasta / arquivo).write_bytes(conteudo)
    return f"empresa/{arquivo}"


def caminho_marca(relativo: str | None) -> Path | None:
    """Caminho absoluto de um arquivo de marca, se ele existir."""
    if not relativo:
        return None
    # Impede sair da pasta com "../" — o valor vem do banco, mas nem por isso
    # deixa de ser conferido.
    alvo = (PASTA_EMPRESA / os.path.basename(relativo)).resolve()
    if not str(alvo).startswith(str(PASTA_EMPRESA.resolve())):
        return None
    return alvo if alvo.exists() else None
