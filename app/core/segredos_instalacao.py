"""Segredos de instalação — gerados no primeiro boot, persistidos em volume.

## O conflito que este módulo resolve

O `docker-compose.yml` marcava três segredos como **obrigatórios**:

```yaml
JWT_SECRET: ${JWT_SECRET:?defina JWT_SECRET no stack}
```

`docker compose up` **aborta** se não estiverem definidos. É a atitude certa
contra segredo fraco — os padrões no código eram `"troque-este-segredo-jwt"`,
que qualquer um lê no repositório.

Mas o efeito prático era: **criar a stack falhava** até alguém gerar três
valores à mão. Quem subia pela primeira vez via um erro, não um sistema.

## A saída

**Gerar na primeira execução e guardar num volume.** Assim:

- **Não existe segredo padrão** — o que está no código nunca é usado
- **Não existe passo manual** — a stack sobe vazia e funciona
- **O segredo sobrevive** a reinício, `docker compose up` e atualização da
  imagem, porque está no volume, não na camada do container

## Onde fica

`NEXUS_SEGREDOS_DIR` (padrão `/app/segredos`, montado como volume).

Um arquivo por segredo, com permissão `0600`. O conteúdo é hexadecimal de 32
bytes — 256 bits, gerado por `secrets.token_hex`, que é a fonte
criptograficamente segura da biblioteca padrão.

## ⚠️ O que isso implica, e precisa estar escrito

**Sem o volume, os segredos não sobrevivem.** Recriar o container sem o volume
gera segredos novos — e então:

- todos os logins caem (JWT inválido)
- todas as etiquetas QR impressas deixam de validar
- as licenças de software ficam ilegíveis (a chave mestra cifra os valores)

Por isso o volume é declarado no `docker-compose.yml`, e por isso há um aviso
no log quando um segredo é gerado: se isso aparecer num reinício, o volume
está faltando.
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

log = logging.getLogger("app")

# 32 bytes = 256 bits. Hex porque é o que cabe com folga em qualquer variável
# de ambiente e em qualquer arquivo, sem escape.
TAMANHO = 32

_PADROES_CONHECIDOS = {
    "",
    "troque-este-segredo-jwt",
    "troque-este-segredo-qr-hmac",
    "admin123",
    "changeme",
    "secret",
}


def diretorio() -> Path:
    """Onde os segredos moram. `/app/segredos` dentro do container."""
    return Path(os.environ.get("NEXUS_SEGREDOS_DIR", "/app/segredos"))


def _caminho(nome: str) -> Path:
    return diretorio() / f"{nome}.txt"


def _ler(nome: str) -> str | None:
    try:
        arquivo = _caminho(nome)
        if not arquivo.is_file():
            return None
        valor = arquivo.read_text(encoding="utf-8").strip()
        return valor or None
    except Exception:
        return None


def _gravar(nome: str, valor: str) -> None:
    try:
        pasta = diretorio()
        pasta.mkdir(parents=True, exist_ok=True)
        arquivo = _caminho(nome)
        arquivo.write_text(valor, encoding="utf-8")
        # Só o dono lê. Em container de usuário único, é o suficiente; num
        # host compartilhado, impede que outro usuário do sistema leia.
        os.chmod(arquivo, 0o600)
    except Exception as e:
        # Não poder gravar não pode derrubar a aplicação: o valor gerado vale
        # para esta execução. O que se perde é a persistência — e o aviso
        # abaixo é o que evita descobrir isso só no próximo reinício.
        log.warning(
            "Não foi possível gravar o segredo %r em %s (%s). Ele vale só para "
            "esta execução — reinícios invalidarão sessões e etiquetas.",
            nome, diretorio(), e,
        )


def obter(nome: str, valor_atual: str | None) -> str:
    """Devolve o segredo, resolvendo na ordem que importa.

    ## A ordem

    1. **Valor fornecido** (variável de ambiente) — quem define, manda
    2. **Arquivo no volume** — a geração anterior
    3. **Gerar agora** — primeira execução

    O passo 1 vem primeiro de propósito: um operador que define
    `JWT_SECRET` no stack assume o controle, e o arquivo passa a ser
    ignorado. É o que permite rotacionar sem apagar volume.

    Um valor **igual ao padrão do código** é tratado como ausente. Sem isso,
    a instalação que não definiu nada usaria `"troque-este-segredo-jwt"` — o
    segredo que está publicado no repositório.
    """
    fornecido = (valor_atual or "").strip()
    if fornecido and fornecido not in _PADROES_CONHECIDOS:
        return fornecido

    guardado = _ler(nome)
    if guardado:
        return guardado

    novo = secrets.token_hex(TAMANHO)
    _gravar(nome, novo)
    log.info(
        "Segredo %r gerado e guardado em %s. Se esta mensagem aparecer de novo "
        "no próximo reinício, o volume de segredos não está persistindo.",
        nome, _caminho(nome),
    )
    return novo
