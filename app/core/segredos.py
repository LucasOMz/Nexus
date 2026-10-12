"""Cifra de segredos em repouso — chaves de licença de software.

## O princípio

> A chave de licença é tratada como **senha**, não como dado de cadastro.

Um número de série de equipamento vazado não faz mal. Uma chave de licença
vazada permite uso irregular e pode ser **revogada pelo fabricante** — o
prejuízo é financeiro e imediato. Por isso ela não fica em claro no banco.

## ⚠️ A regra que separa criptografia de teatro

**A chave mestra NÃO pode viver no banco de dados.**

Se ela estiver numa tabela ao lado do valor cifrado, quem lê o banco lê as
duas — e a cifra não protegeu nada. Foi só ofuscação com passos extras.

A chave mestra vem de **variável de ambiente** (`NEXUS_CHAVE_LICENCAS`), que
fica no `.env` — fora do banco e **fora do backup do banco**.

## ⚠️ Consequência que precisa estar escrita

**Sem a chave mestra, as chaves cadastradas são irrecuperáveis.** O backup do
banco não resolve, porque a chave não está nele. Isso é uma escolha, não um
defeito: é o que impede que quem rouba o backup leia as licenças.

Guarde `NEXUS_CHAVE_LICENCAS` num cofre separado.

## Rotação

Cada valor guarda a **versão** da chave usada. Trocar a chave mestra não
obriga a recadastrar: a versão 1 continua legível com a chave antiga enquanto
um comando re-cifra o resto. Sem isso, ninguém troca a chave mestra — e uma
chave que nunca gira é uma chave comprometida em algum momento.
"""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - dependência declarada no requirements
    Fernet = None  # type: ignore[assignment]

    class InvalidToken(Exception):  # type: ignore[no-redef]
        """Placeholder quando a `cryptography` não está instalada."""


VARIAVEL = "NEXUS_CHAVE_LICENCAS"
VERSAO_PADRAO = 1


def versao_atual() -> int:
    """Qual versão da chave mestra está em uso agora.

    ## Por que isto é configurável, e não uma constante

    Uma constante no código faria a rotação exigir **alterar o programa** —
    e ninguém gira uma chave que precisa de deploy. Virando variável de
    ambiente, girar passa a ser:

        NEXUS_CHAVE_LICENCAS_V1 = <a chave antiga>   # para ler o legado
        NEXUS_CHAVE_LICENCAS    = <a chave nova>
        NEXUS_CHAVE_LICENCAS_VERSAO = 2

    Valores gravados antes carregam a versão 1 e continuam legíveis; os novos
    nascem na 2. Um comando re-cifra o resto e a chave antiga pode ser
    descartada.
    """
    try:
        return max(1, int(os.environ.get(f"{VARIAVEL}_VERSAO", VERSAO_PADRAO)))
    except ValueError:
        return VERSAO_PADRAO

# Prefixos que NÃO são dado: são vazio e máscara. Cifrar vazio só produziria
# ruído, e "sem chave" precisa continuar sendo distinguível de "chave oculta".
VAZIOS = {None, "", "—", "-"}


class ChaveMestraAusente(RuntimeError):
    """A variável de ambiente não está definida.

    Erro de configuração, não de dado — a mensagem diz o que fazer.
    """


class SegredoIlegivel(RuntimeError):
    """O valor não decifra: chave mestra trocada sem rotação, ou dado corrompido."""


def disponivel() -> bool:
    """A criptografia está instalada **e** a chave mestra é alcançável?

    Consulta a configuração primeiro, e o ambiente depois — a mesma ordem de
    `_chave_mestra`. Checar só `os.environ` faria esta função responder
    "indisponível" numa instalação perfeitamente configurada pelo `.env`.
    """
    if Fernet is None:
        return False
    try:
        return bool(_chave_mestra())
    except ChaveMestraAusente:
        return False


def _da_configuracao(versao: int) -> str | None:
    """A chave mestra vinda do `Settings` — o `.env` lido pelo Pydantic.

    ## Por que isto existe

    O `Settings` do Pydantic lê o `.env` para dentro do **objeto** e **não**
    escreve em `os.environ`. Um módulo que consulte só `os.environ` recebe
    `None` numa instalação normal, **mesmo com a variável no `.env`**.

    Era o que acontecia: a cifra existia, os testes passavam (eles escrevem
    em `os.environ` de verdade, com `monkeypatch`) e cadastrar licença com
    chave falhava na implantação.

    A ordem é configuração primeiro, ambiente depois — o ambiente continua
    valendo para Docker, systemd e para os testes.
    """
    try:
        from app.config import settings
    except Exception:  # pragma: no cover - import circular improvável
        return None

    if versao == _versao_da_configuracao():
        return (settings.chave_licencas or "").strip() or None
    # Versões antigas (rotação): não têm campo próprio no Settings.
    return getattr(settings, f"chave_licencas_v{versao}", None)


def _versao_da_configuracao() -> int:
    try:
        from app.config import settings

        return max(1, int(settings.chave_licencas_versao or VERSAO_PADRAO))
    except Exception:  # pragma: no cover
        return VERSAO_PADRAO


def _chave_mestra(versao: int | None = None) -> bytes:
    """A chave mestra de uma versão.

    ## A ordem da busca importa

    Ao girar a chave, `NEXUS_CHAVE_LICENCAS` passa a ser a **nova** — e os
    valores antigos continuam cifrados com a anterior, marcados com a versão
    de origem. Se a busca preferisse sempre a variável atual, decifrar um
    valor da versão 1 usaria a chave 2 e falharia — **tornando a rotação
    impossível justamente para quem precisa dela**.

    Por isso a versão pedida manda: fora da versão atual, procura-se primeiro
    `NEXUS_CHAVE_LICENCAS_V{versao}`.

        NEXUS_CHAVE_LICENCAS       = <a chave nova>   (versão atual)
        NEXUS_CHAVE_LICENCAS_V1    = <a chave antiga>  (para ler o legado)
    """
    versao = versao_atual() if versao is None else versao
    atual = versao_atual()

    # A ORDEM é ambiente primeiro, configuração depois.
    #
    # Variável de ambiente vence o `.env` — é a convenção (o próprio
    # pydantic-settings faz assim) e é o que se espera em container: a imagem
    # traz um `.env` de referência e o operador sobrescreve pelo ambiente, sem
    # editar arquivo dentro do contêiner.
    #
    # Inverti isto na primeira versão e os testes pegaram: `monkeypatch`
    # escreve em `os.environ` justamente para simular a sobrescrita, e com a
    # configuração na frente ele não tinha efeito nenhum.
    bruta = None
    nomes = [VARIAVEL]
    if versao != atual:
        nomes = [f"{VARIAVEL}_V{versao}", VARIAVEL]
    for nome in nomes:
        achado = os.environ.get(nome)
        if achado:
            bruta = achado
            break

    # Sem nada no ambiente, a configuração do sistema — o `.env` lido pelo
    # Pydantic, que **não** popula `os.environ`. É o caminho normal de
    # implantação, e era exatamente o que faltava.
    if not bruta:
        bruta = _da_configuracao(versao)

    if not bruta:
        raise ChaveMestraAusente(
            "Defina NEXUS_CHAVE_LICENCAS no .env (ou no ambiente). Sem ela as "
            "licenças ficam irrecuperáveis — guarde-a num cofre separado do "
            "banco, porque o backup do banco não a contém."
        )

    texto = bruta.strip().encode()
    if not texto:
        raise ChaveMestraAusente(f"{VARIAVEL} está definida mas vazia.")

    # Aceita tanto a chave pronta do Fernet (44 chars base64) quanto uma
    # frase: derivar com SHA-256 evita exigir que o operador gere base64.
    try:
        base64.urlsafe_b64decode(texto)
        if len(texto) == 44:
            return texto
    except Exception:
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(texto).digest())


def gerar_chave() -> str:
    """Gera uma chave mestra nova, para colocar no `.env`."""
    if Fernet is None:
        raise ChaveMestraAusente("A biblioteca `cryptography` não está instalada.")
    return Fernet.generate_key().decode()


@dataclass(frozen=True)
class Segredo:
    """Um valor cifrado e a versão da chave que o produziu."""

    cifrado: bytes
    versao: int


def cifrar(valor: str | None) -> Segredo | None:
    """Cifra um valor. `None` e vazio passam direto — não há o que proteger."""
    if valor in VAZIOS:
        return None
    if Fernet is None:
        raise ChaveMestraAusente("A biblioteca `cryptography` não está instalada.")
    return Segredo(
        cifrado=Fernet(_chave_mestra()).encrypt(valor.strip().encode()),
        versao=versao_atual(),
    )


def decifrar(cifrado: bytes | None, versao: int | None = None) -> str | None:
    """Decifra. Devolve `None` quando não há valor — nunca levanta por isso."""
    if not cifrado:
        return None
    if Fernet is None:
        raise ChaveMestraAusente("A biblioteca `cryptography` não está instalada.")
    try:
        return Fernet(_chave_mestra(versao)).decrypt(cifrado).decode()
    except InvalidToken as e:
        raise SegredoIlegivel(
            "Não foi possível decifrar. A chave mestra foi trocada sem rotação, "
            "ou o dado está corrompido."
        ) from e


def impressao(valor: str | None) -> str | None:
    """As quatro últimas posições, para conferir DE QUAL licença se trata.

    É o que aparece na tela sem revelar nada. Serve para o operador
    responder "é essa mesma?" sem ver a chave.
    """
    if valor in VAZIOS:
        return None
    limpo = valor.strip()
    return limpo[-4:] if len(limpo) >= 4 else limpo


def impressao_hash(valor: str | None) -> str | None:
    """Hash do valor normalizado — para achar duplicata SEM decifrar.

    Comparar chaves exige decifrar tudo a cada verificação. O hash permite
    consultar o banco por igualdade, e **não** permite recuperar o valor.

    A normalização (maiúsculas, sem separadores) faz `ABC-123` e `abc 123`
    serem reconhecidos como a mesma chave — que é o erro humano provável.
    """
    if valor in VAZIOS:
        return None
    normalizado = "".join(c for c in valor.upper() if c.isalnum())
    return hashlib.sha256(normalizado.encode()).hexdigest()


def mascarar(impressao_valor: str | None) -> str:
    """Como a chave aparece na tela e nas listagens."""
    if not impressao_valor:
        return "—"
    return f"••••-••••-••••-{impressao_valor}"


def recifrar(cifrado: bytes, versao_antiga: int) -> Segredo:
    """Re-cifra com a versão atual. Usado na rotação da chave mestra."""
    texto = decifrar(cifrado, versao_antiga)
    novo = cifrar(texto)
    if novo is None:  # pragma: no cover - decifrar já garantiu que há valor
        raise SegredoIlegivel("Valor vazio após decifrar.")
    return novo
