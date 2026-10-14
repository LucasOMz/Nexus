"""Cliente e sincronização com o OCS Inventory.

O OCS expõe uma API REST (a partir da versão 2.8) em `/ocsapi/v1`. A autenticação
é por **token fixo** no cabeçalho, configurado no servidor do OCS.

Duas decisões importantes:

1. **O OCS nunca sobrescreve dados patrimoniais.** Planta, responsável, garantia,
   valor e patrimônio são do sistema — a sincronização mexe apenas nos campos
   técnicos (SO, memória, rede, série).
2. **O casamento é por número de série**, com o patrimônio como reserva. Isso
   permite que máquinas já cadastradas antes da integração sejam reconhecidas em
   vez de duplicadas.
"""
from __future__ import annotations

import re
import time
from typing import Any

import httpx

from app.core.cripto import decifrar

# Blocos consultados por máquina. Cada um é uma chamada à API.
BLOCOS = ("bios", "hardware", "os", "networks", "disk")

# Quanto tempo esperar entre chamadas (evita derrubar o OCS com centenas de
# requisições seguidas).
PAUSA_ENTRE_CHAMADAS = 0.02


def _primeiro(dados: Any, *chaves: str) -> Any:
    """Devolve o primeiro valor não vazio entre os nomes dados.

    Os nomes dos campos variam um pouco entre versões do OCS — procurar por
    vários nomes evita que a integração quebre ao atualizar o servidor.
    """
    if isinstance(dados, list):
        dados = dados[0] if dados else {}
    if not isinstance(dados, dict):
        return None
    for chave in chaves:
        valor = dados.get(chave)
        if valor not in (None, "", [], {}):
            return valor
    return None


def _para_gb(valor: Any) -> int | None:
    """O OCS manda bytes; o sistema guarda GB."""
    try:
        numero = int(str(valor).strip())
    except (TypeError, ValueError):
        return None
    if numero <= 0:
        return None
    gb = round(numero / (1024 ** 3))
    return gb if gb > 0 else None


def _texto(valor: Any, limite: int = 200) -> str | None:
    if valor in (None, ""):
        return None
    return str(valor).strip()[:limite] or None


# ---------------------------------------------------------------------------
# Cliente HTTP
# ---------------------------------------------------------------------------
def token_de(cfg) -> str | None:
    """O token fica cifrado no banco; devolve em claro para uso interno."""
    if not cfg.token:
        return None
    return decifrar(cfg.token) if cfg.token else None


def _cliente(cfg) -> httpx.Client:
    token = token_de(cfg)
    if not token:
        raise ValueError("Token da API do OCS não configurado.")
    return httpx.Client(
        base_url=(cfg.servidor or "").rstrip("/"),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=float(cfg.timeout_s or 30),
        verify=bool(cfg.verificar_ssl),
    )


def listar_maquinas(cfg) -> list[dict]:
    """Lista as máquinas inventariadas."""
    with _cliente(cfg) as cli:
        r = cli.get("/ocsapi/v1/computer")
        r.raise_for_status()
        dados = r.json()
    if isinstance(dados, dict):  # algumas versões embrulham em {"computers": [...]}
        for chave in ("computers", "data", "items", "results"):
            if isinstance(dados.get(chave), list):
                return dados[chave]
        return []
    return dados if isinstance(dados, list) else []


def detalhes(cfg, maquina_id: Any) -> dict:
    """Junta os blocos de uma máquina (BIOS, hardware, SO, rede, disco)."""
    saida: dict[str, Any] = {}
    with _cliente(cfg) as cli:
        for bloco in BLOCOS:
            try:
                r = cli.get(f"/ocsapi/v1/computer/{maquina_id}/{bloco}")
                saida[bloco] = r.json() if r.status_code == 200 else None
            except httpx.HTTPError:
                saida[bloco] = None
            time.sleep(PAUSA_ENTRE_CHAMADAS)
    return saida


def testar_conexao(cfg) -> tuple[bool, str]:
    """Valida o endereço e o token, informando quantas máquinas existem."""
    if not cfg.servidor:
        return False, "Informe o endereço do servidor OCS."
    if not token_de(cfg):
        return False, "Informe o token da API do OCS."
    try:
        maquinas = listar_maquinas(cfg)
    except httpx.HTTPStatusError as e:
        codigo = e.response.status_code
        if codigo in (401, 403):
            return False, f"O servidor respondeu {codigo}: token inválido ou sem permissão."
        return False, f"O servidor respondeu {codigo}."
    except httpx.ConnectError:
        return False, "Não foi possível conectar. Confira o endereço e a rede."
    except httpx.TimeoutException:
        return False, "O servidor demorou demais para responder."
    except (httpx.HTTPError, ValueError) as e:
        return False, f"Falha na conexão: {e}"
    return True, f"Conectado. {len(maquinas)} máquina(s) encontrada(s) no OCS."


# ---------------------------------------------------------------------------
# Mapeamento
# ---------------------------------------------------------------------------
def _serial_provisorio(maquina: dict) -> str:
    """Um número de série para quando o fabricante não informa nenhum.

    ## Por que existe

    O número de série **é o identificador do ativo** — o banco exige, e dois
    ativos não podem repetir. Algumas máquinas, porém, reportam `SSN` vazio,
    ou o texto de fábrica `"To be filled by O.E.M."` que a placa-mãe traz
    quando o montador não gravou nada.

    Sem isto, essas máquinas **nunca entrariam** no inventário: o cadastro
    seria recusado pelo banco, e a coleta inteira falharia por causa delas.

    ## Por que derivar do DEVICEID

    É o identificador que o próprio OCS usa — estável entre coletas, e único
    por máquina. O hostname seria menos confiável: nome de máquina muda com
    frequência, e duas podem compartilhar.

    ## O prefixo `OCS-`

    Deixa explícito que aquele serial **não veio do fabricante**. Quem olhar
    o cadastro sabe que é provisório, e pode trocar quando o real aparecer —
    em vez de achar que aquele código estranho é o serial de verdade.
    """
    bruto = _primeiro(maquina, "DEVICEID", "deviceid", "ID", "id", "NAME", "name")
    limpo = _texto(bruto, 100)
    if not limpo:
        return "OCS-SEM-IDENTIFICADOR"
    # Só o que cabe num serial; o resto vira ruído visual na etiqueta.
    seguro = "".join(c for c in str(limpo) if c.isalnum() or c in "-_")
    return f"OCS-{seguro[:100]}" or "OCS-SEM-IDENTIFICADOR"



def mapear(maquina: dict, det: dict) -> dict[str, Any]:
    """Traduz a resposta do OCS para os campos usados pelo sistema."""
    bio = det.get("bios")
    hw = det.get("hardware")
    so = det.get("os")
    rede = det.get("networks")
    disco = det.get("disk")

    # O bloco de hardware pode vir como lista de blocos; junta tudo.
    def do_hardware(*chaves):
        return _primeiro(hw, *chaves)

    return {
        # --- Identificação ---
        "hostname": _texto(_primeiro(maquina, "NAME", "name", "DEVICEID"), 120),
        # O número de série é o IDENTIFICADOR do ativo — o banco exige, e dois
        # ativos não podem repetir.
        #
        # ## O que fazer quando o OCS não informa
        #
        # Algumas máquinas reportam `SSN` vazio, ou o texto de fábrica
        # `"To be filled by O.E.M."`. Antes isso virava um ativo sem serial.
        # Agora não pode: sem serial o cadastro é recusado pelo banco, e a
        # máquina **nunca entraria** no inventário.
        #
        # A escolha é derivar do `DEVICEID` do OCS — estável entre coletas, e
        # único por máquina. O hostname seria menos confiável: nome de máquina
        # muda, e duas podem compartilhar.
        #
        # O prefixo `OCS-` deixa explícito que aquele serial **não veio do
        # fabricante**: quem olhar o cadastro sabe que é provisório, e pode
        # trocar quando o real aparecer.
        "numero_serie": (
            _texto(_primeiro(bio, "SSN", "ssn", "SERIALNUMBER", "serialnumber"), 120)
            or _serial_provisorio(maquina)
        ),
        "marca": _texto(_primeiro(bio, "SMANUFACTURER", "manufacturer", "MANUFACTURER"), 80),
        "modelo": _texto(_primeiro(bio, "SMODEL", "model", "MODEL", "SMODELNAME"), 120),
        # --- Técnico ---
        "so": _texto(_primeiro(so, "OSNAME", "osname", "NAME", "VERSION"), 120),
        "cpu": _texto(do_hardware("PROCESSORT", "processort", "PROCESSORS", "CPU"), 120),
        "ram_gb": _para_gb(do_hardware("MEMORY", "memory")),
        "armazenamento_gb": _para_gb(do_hardware("DISKSIZE", "disksize", "HDD")),
        "mac_address": _texto(_primeiro(rede, "MACADDR", "macaddr", "MAC"), 60),
        "ip": _texto(_primeiro(rede, "IPADDRESS", "ipaddress", "IP"), 60),
        # --- Apoio ---
        "usuario_ad": _texto(_primeiro(maquina, "USERID", "userid", "USER"), 120),
        "ultimo_contato": _texto(_primeiro(maquina, "LASTDATE", "lastdate", "LASTCOME", "lastcome"), 40),
        "ocs_id": _primeiro(maquina, "ID", "id"),
        "_disco": disco,
    }


def regra_que_casa(regras: list[dict], hostname: str | None) -> dict | None:
    """Devolve a PRIMEIRA regra que casa com o hostname (ou None).

    `planta_por_hostname` e a pré-visualização usam esta mesma função — assim
    não há risco de a contagem na tela discordar do que a sincronização faz.
    """
    if not hostname:
        return None
    alvo = hostname.strip().upper()

    for regra in regras or []:
        padrao = (regra.get("prefixo") or regra.get("padrao") or "").strip()
        if not padrao:
            continue

        tipo = (regra.get("tipo") or "comeca_com").lower()
        if tipo == "contem":
            casa = padrao.upper() in alvo
        elif tipo == "regex":
            try:
                casa = re.search(padrao, hostname, re.I) is not None
            except re.error:
                casa = False  # expressão inválida não derruba a sincronização
        else:
            casa = alvo.startswith(padrao.upper())

        if casa:
            return regra
    return None


def planta_por_hostname(regras: list[dict], hostname: str | None) -> int | None:
    """Descobre a planta pelo hostname, conforme o tipo de comparação da regra.

    Tipos aceitos em `tipo` (ausente = `comeca_com`, para não quebrar as regras
    que já existiam):

    * `comeca_com` — o hostname inicia com o padrão (`PC-BNT-001`)
    * `contem`     — o padrão aparece em qualquer posição (`DTAT0001` contém `TAT`)
    * `regex`      — expressão regular completa (`^[DNR]TAT\\d+$`)

    A **primeira regra que casar** decide — por isso a ordem importa.
    Devolve `None` quando nenhuma casa; o chamador decide o que fazer.
    """
    regra = regra_que_casa(regras, hostname)
    return regra.get("planta_id") if regra else None


def compilar_filtro(padrao: str | None) -> re.Pattern | None:
    """Compila o filtro de hostname, tolerando uma expressão inválida."""
    if not padrao:
        return None
    try:
        return re.compile(padrao, re.I)
    except re.error:
        return None
