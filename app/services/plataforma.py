"""Limite de requisições, retenção (LGPD) e MFA — utilitários de plataforma.

Três peças pequenas, todas de **lógica pura**:

* **limite de requisições** — janela deslizante em memória
* **retenção e expurgo** — quando cada tipo de dado deixa de ser necessário
* **MFA (TOTP)** — segunda etapa para administradores, em biblioteca padrão

Nenhuma depende de serviço externo, e é isso que as torna verificáveis.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import unicodedata
from collections import deque
from datetime import date, datetime, timedelta, timezone
from typing import Any


# ===========================================================================
# 1. LIMITE DE REQUISIÇÕES
# ===========================================================================
class Limitador:
    """Janela deslizante por chave (IP, usuário, rota).

    Em memória de propósito: o objetivo é conter abuso acidental — um script
    em laço, um celular reenviando —, não defender contra ataque distribuído.
    Para isso existiria limite no proxy.

    Em memória também significa que **cada processo tem o seu**. Com vários
    workers, o limite efetivo é a soma — está documentado para não virar
    surpresa.
    """

    def __init__(self, limite: int = 60, janela_s: int = 60, max_chaves: int = 5000):
        self.limite = limite
        self.janela_s = janela_s
        # Teto de chaves: sem isso, um ataque com milhões de IPs falsos encheria
        # a memória do servidor — o remédio viraria a doença.
        self.max_chaves = max_chaves
        self._marcas: dict[str, deque[float]] = {}

    def permitir(self, chave: str, agora: float) -> dict[str, Any]:
        """Consome uma unidade e diz se passou."""
        marcas = self._marcas.get(chave)
        if marcas is None:
            if len(self._marcas) >= self.max_chaves:
                self._limpar_antigas(agora)
            marcas = self._marcas.setdefault(chave, deque())

        corte = agora - self.janela_s
        while marcas and marcas[0] <= corte:
            marcas.popleft()

        if len(marcas) >= self.limite:
            espera = max(1, int(marcas[0] + self.janela_s - agora) + 1)
            return {
                "permitido": False,
                "restantes": 0,
                "recomeca_em_s": espera,
                "limite": self.limite,
                "janela_s": self.janela_s,
            }

        marcas.append(agora)
        return {
            "permitido": True,
            "restantes": self.limite - len(marcas),
            "recomeca_em_s": 0,
            "limite": self.limite,
            "janela_s": self.janela_s,
        }

    def esquecer(self, chave: str) -> None:
        """Zera o contador — usado depois de um login bem-sucedido."""
        self._marcas.pop(chave, None)

    def _limpar_antigas(self, agora: float) -> None:
        corte = agora - self.janela_s
        for k in [k for k, v in self._marcas.items() if not v or v[-1] <= corte]:
            self._marcas.pop(k, None)

    def limpar(self) -> None:
        self._marcas.clear()


# ===========================================================================
# 2. RETENÇÃO E EXPURGO (LGPD)
# ===========================================================================
# Por quanto tempo cada dado é necessário, e o que fazer depois.
#
# O princípio da LGPD é **finalidade**: dado guardado sem motivo vira passivo.
# Mas apagar de mais também é problema — auditoria e garantia exigem histórico.
# Cada prazo aqui tem uma justificativa, e não um número escolhido ao acaso.
RETENCAO = {
    "auditoria": {
        "dias": 365 * 5,
        "motivo": "Prazo prescricional fiscal e trabalhista; sustentação de auditoria.",
        "acao": "anonimizar",   # a trilha fica; o IP e o nome do operador não
    },
    "movimentacoes": {
        "dias": 365 * 10,
        "motivo": "Histórico patrimonial — vida útil do bem e sua baixa.",
        "acao": "manter",
    },
    "manutencoes": {
        "dias": 365 * 5,
        "motivo": "Garantia e responsabilidade sobre o serviço prestado.",
        "acao": "manter",
    },
    "reportes": {
        "dias": 365 * 2,
        "motivo": "Retorno da implantação; depois perde utilidade.",
        "acao": "apagar",
    },
    "logs_acesso": {
        "dias": 180,
        "motivo": "Segurança — identificar acesso indevido recente.",
        "acao": "apagar",
    },
    "notificacoes": {
        "dias": 90,
        "motivo": "Aviso operacional: lido ou vencido, não serve mais.",
        "acao": "apagar",
    },
    "fotos": {
        "dias": None,
        "motivo": "Enquanto o ativo existir: é a prova do estado dele.",
        "acao": "vincular_ao_ativo",
    },
}


def prazo_de(tipo: str, agora: datetime | None = None) -> date | None:
    """Data-limite a partir da qual o dado pode ser expurgado."""
    regra = RETENCAO.get(tipo)
    if regra is None or regra["dias"] is None:
        return None
    hoje = (agora or datetime.now(timezone.utc)).date()
    return hoje - timedelta(days=regra["dias"])


def decidir(tipo: str, criado_em: Any, agora: datetime | None = None) -> dict[str, Any]:
    """O que fazer com ESTE registro.

    Devolve a ação e o porquê — quem for executar o expurgo precisa entender a
    decisão, não só obedecer.
    """
    regra = RETENCAO.get(tipo)
    if regra is None:
        return {"acao": "manter", "motivo": "Tipo sem política definida — mantido por segurança."}

    quando = _data(criado_em)
    if quando is None:
        return {"acao": "manter", "motivo": "Sem data de criação — não se expurga o que não se pode datar."}

    limite = prazo_de(tipo, agora=agora)
    if limite is None:
        return {"acao": regra["acao"], "motivo": regra["motivo"], "definitivo": False}

    if quando > limite:
        restantes = (quando - limite).days
        return {
            "acao": "manter",
            "faltam_dias": restantes,
            "motivo": regra["motivo"],
        }

    return {
        "acao": regra["acao"],
        "vencido_em": limite.isoformat(),
        "motivo": regra["motivo"],
    }


def plano_de_expurgo(registros: list[dict], agora: datetime | None = None) -> dict[str, Any]:
    """Resumo do que seria expurgado, SEM expurgar.

    Rodar isto antes é o que evita apagar demais: a pessoa vê o número e
    confirma, em vez de descobrir depois que o histórico sumiu.
    """
    contagem: dict[str, dict[str, int]] = {}
    for r in registros:
        tipo = r.get("tipo")
        decisao = decidir(tipo, r.get("criado_em"), agora=agora)
        linha = contagem.setdefault(tipo, {"manter": 0, "apagar": 0, "anonimizar": 0, "expurgar": 0})
        acao = decisao["acao"]
        linha[acao if acao in linha else "manter"] += 1
        if acao != "manter" and decisao.get("vencido_em"):
            linha["expurgar"] += 1
    return {"por_tipo": contagem, "total": len(registros)}


def anonimizar(registro: dict[str, Any]) -> dict[str, Any]:
    """Tira o que identifica a pessoa, preservando o fato.

    É o que concilia LGPD com auditoria: a trilha "alguém alterou o ativo X no
    dia Y" continua íntegra; **quem** era a pessoa, não. Sem isso, a escolha
    seria entre apagar a prova ou violar a lei.
    """
    sensiveis = ("ip", "usuario_nome", "usuario_email", "login_ad", "user_agent", "nome")
    saida = dict(registro)
    for campo in sensiveis:
        if saida.get(campo):
            saida[campo] = "[anonimizado]"
    if saida.get("usuario_id") is not None:
        saida["usuario_id_original"] = None   # a ligação com a pessoa sai
    saida["anonimizado"] = True
    return saida


def _data(valor: Any) -> date | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except (ValueError, TypeError):
        return None


# ===========================================================================
# 3. MFA (TOTP)
# ===========================================================================
# Implementado em biblioteca padrão: TOTP (RFC 6238) é HMAC-SHA1 sobre o
# contador de intervalos de 30s. Depender de pacote externo para ~40 linhas
# não se justifica — e uma dependência a menos é uma falha de instalação a
# menos.
TOTP_DIGITOS = 6
TOTP_INTERVALO_S = 30
# Aceita o código do intervalo anterior e do seguinte: relógios diferentes e
# digitação no limite do intervalo causariam recusa indevida.
TOTP_JANELA = 1


def gerar_segredo(bytes_: int = 20) -> str:
    """Segredo em base32 — o formato que os aplicativos autenticadores leem."""
    return base64.b32encode(secrets.token_bytes(bytes_)).decode("ascii").rstrip("=")


def _decodificar_segredo(segredo: str) -> bytes:
    limpo = (segredo or "").strip().replace(" ", "").upper()
    # Base32 sem padding é o padrão nos apps; o Python exige o padding.
    limpo += "=" * (-len(limpo) % 8)
    return base64.b32decode(limpo, casefold=True)


def gerar_codigo(segredo: str, momento: datetime | None = None) -> str:
    """Código de 6 dígitos do momento atual."""
    quando = momento or datetime.now(timezone.utc)
    contador = int(quando.timestamp()) // TOTP_INTERVALO_S
    chave = _decodificar_segredo(segredo)
    digest = hmac.new(chave, struct.pack(">Q", contador), hashlib.sha1).digest()
    # Truncamento dinâmico (RFC 4226): o último nibble diz de onde ler 4 bytes.
    deslocamento = digest[-1] & 0x0F
    codigo = struct.unpack(">I", digest[deslocamento:deslocamento + 4])[0] & 0x7FFFFFFF
    return str(codigo % (10 ** TOTP_DIGITOS)).zfill(TOTP_DIGITOS)


def conferir_codigo(segredo: str, codigo: str, momento: datetime | None = None) -> bool:
    """O código confere, aceitando a janela de tolerância.

    Compara em tempo constante — comparar com `==` vazaria informação pelo
    tempo de resposta, e código de 6 dígitos é força bruta viável.
    """
    if not segredo or not codigo:
        return False
    limpo = str(codigo).strip().replace(" ", "")
    if not limpo.isdigit() or len(limpo) != TOTP_DIGITOS:
        return False

    quando = momento or datetime.now(timezone.utc)
    for deslocamento in range(-TOTP_JANELA, TOTP_JANELA + 1):
        alvo = quando + timedelta(seconds=deslocamento * TOTP_INTERVALO_S)
        if hmac.compare_digest(gerar_codigo(segredo, alvo), limpo):
            return True
    return False


def uri_otpauth(segredo: str, conta: str, emissor: str = "Gestao Patrimonial") -> str:
    """Endereço que o aplicativo lê do QR Code.

    É o que faz o cadastro ser "aponte a câmera" em vez de "digite 32 letras".
    """
    from urllib.parse import quote, urlencode

    parametros = urlencode({
        "secret": segredo,
        "issuer": emissor,
        "algorithm": "SHA1",
        "digits": TOTP_DIGITOS,
        "period": TOTP_INTERVALO_S,
    })
    return f"otpauth://totp/{quote(emissor)}:{quote(conta)}?{parametros}"


def gerar_codigos_de_recuperacao(quantidade: int = 8) -> list[str]:
    """Códigos de uso único para quando o celular é perdido.

    Sem isso, quem perde o telefone perde o acesso — e a saída vira desativar
    o MFA, que é pior que não ter.
    """
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}".upper() for _ in range(quantidade)]


def normalizar_codigo_recuperacao(texto: str) -> str:
    return unicodedata.normalize("NFKC", (texto or "").strip()).upper()
