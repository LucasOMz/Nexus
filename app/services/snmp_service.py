"""SNMP de impressora: leitura de contador, suprimento e status.

O OCS enxerga bem computador e mal impressora. Este módulo conversa direto
com a impressora pelo protocolo que ela já fala — SNMP — e traz o que o
cadastro não tem: **contador real, nível de tonner e alarme ativo**.

Transforma o inventário de impressoras de cadastro em monitoramento.

## Por que a interpretação é separada da rede

Ler SNMP exige uma biblioteca externa e uma impressora acessível. As duas
coisas tornam o teste impossível sem infraestrutura. Por isso a **tradução**
(oid → campo) é uma função pura: dá para testar com respostas reais capturadas
de várias marcas, sem tocar na rede.

O transporte (`coletar`) é a única parte que precisa de rede — e falha com
mensagem clara quando a biblioteca não está instalada.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# OIDs padrão (RFC 3805 - Printer MIB), que a maioria das impressoras de rede
# responde. Muitas também expõem OIDs próprios da marca; estes são o mínimo
# comum.
# ---------------------------------------------------------------------------
OIDS = {
    # Identificação
    "modelo": "1.3.6.1.2.1.25.3.2.1.3.1",            # hrDeviceDescr
    "nome": "1.3.6.1.2.1.43.5.1.1.16.1",             # prtGeneralPrinterName
    "numero_serie": "1.3.6.1.2.1.43.5.1.1.17.1",     # prtGeneralSerialNumber
    # Estado
    "status": "1.3.6.1.2.1.25.3.2.1.5.1",            # hrDeviceStatus
    "status_prt": "1.3.6.1.2.1.43.5.1.1.1.1",        # prtGeneralPrinterStatus
    # Contador de páginas
    "contador": "1.3.6.1.2.1.43.10.2.1.4.1.1",       # prtMarkerLifeCount
    # Suprimentos — nível, capacidade e descrição do primeiro cartucho.
    # As impressoras expõem um índice por suprimento (.1.1, .1.2, ...).
    "suprimento_nivel": "1.3.6.1.2.1.43.11.1.1.9.1.1",
    "suprimento_max": "1.3.6.1.2.1.43.11.1.1.8.1.1",
    "suprimento_desc": "1.3.6.1.2.1.43.11.1.1.6.1.1",
}

# Prefixo para varrer TODOS os suprimentos (tonner, cilindro, manutenção).
PREFIXO_SUPRIMENTOS = "1.3.6.1.2.1.43.11.1.1"

# `hrDeviceStatus` (HR MIB).
STATUS_DEVICE = {
    1: "desconhecido", 2: "rodando", 3: "aviso", 4: "teste", 5: "parado",
}

# Nível de suprimento: a MIB usa -3 como "desconhecido" e -2 como "sem limite".
NIVEL_DESCONHECIDO = -3
NIVEL_SEM_LIMITE = -2
NIVEL_VAZIO = -1


def _inteiro(valor: Any) -> int | None:
    """SNMP devolve ora int, ora string, ora bytes — normaliza."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return int(valor)
    if isinstance(valor, int):
        return valor
    if isinstance(valor, bytes):
        valor = valor.decode("utf-8", "ignore")
    texto = str(valor).strip()
    if not texto:
        return None
    try:
        return int(texto)
    except ValueError:
        try:
            return int(float(texto))
        except ValueError:
            return None


def _texto(valor: Any) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, bytes):
        valor = valor.decode("utf-8", "ignore")
    texto = str(valor).strip().strip('"')
    return texto or None


def percentual_suprimento(nivel: int | None, capacidade: int | None) -> float | None:
    """Nível do tonner em porcentagem.

    A MIB é confusa de propósito: `-3` é desconhecido, `-2` é "sem limite" e
    `-1` é vazio. Tratar isso como número daria barrinha de -1%, então cada
    código especial tem seu significado.
    """
    if nivel is None:
        return None
    if nivel == NIVEL_VAZIO:
        return 0.0
    if nivel in (NIVEL_DESCONHECIDO, NIVEL_SEM_LIMITE):
        return None
    if capacidade is None or capacidade <= 0:
        return None
    return round(max(0.0, min(100.0, nivel / capacidade * 100)), 1)


def classificar_suprimento(pct: float | None) -> str:
    """Faixa do suprimento — o que dispara (ou não) o alerta."""
    if pct is None:
        return "desconhecido"
    if pct <= 0:
        return "vazio"
    if pct <= 10:
        return "critico"
    if pct <= 25:
        return "atencao"
    return "ok"


def mapear(respostas: dict[str, Any]) -> dict[str, Any]:
    """Traduz as respostas SNMP nos campos da impressora.

    Aceita as chaves `respostas` (nome do campo) OU os próprios OIDs — assim
    serve tanto para o teste com dados nomeados quanto para a resposta crua.
    """
    def pegar(campo: str) -> Any:
        if campo in respostas:
            return respostas[campo]
        oid = OIDS.get(campo)
        return respostas.get(oid) if oid else None

    nivel = _inteiro(pegar("suprimento_nivel"))
    capacidade = _inteiro(pegar("suprimento_max"))
    pct = percentual_suprimento(nivel, capacidade)

    status_num = _inteiro(pegar("status"))
    status = STATUS_DEVICE.get(status_num) if status_num is not None else None

    return {
        "modelo": _texto(pegar("modelo")),
        "nome": _texto(pegar("nome")),
        "numero_serie": _texto(pegar("numero_serie")),
        "contador": _inteiro(pegar("contador")),
        "status": status,
        "status_codigo": status_num,
        "suprimento": {
            "descricao": _texto(pegar("suprimento_desc")),
            "nivel": nivel,
            "capacidade": capacidade,
            "percentual": pct,
            "situacao": classificar_suprimento(pct),
        },
        # Se veio alguma resposta, a impressora falou SNMP.
        "respondeu": any(v is not None for v in respostas.values()),
    }


def extrair_suprimentos(pares: list[tuple[str, Any]]) -> list[dict]:
    """Separa TODOS os suprimentos de uma varredura.

    A MIB indexa por `...43.11.1.1.<campo>.<índice>.<sub>`. Uma impressora
    costuma ter vários: tonner preto, ciano, magenta, amarelo, cilindro, caixa
    de manutenção. Olhar só o primeiro perderia a cor que acabou.
    """
    por_indice: dict[str, dict[str, Any]] = {}
    campos = {"9": "nivel", "8": "capacidade", "6": "descricao"}

    for oid, valor in pares:
        if not oid.startswith(PREFIXO_SUPRIMENTOS):
            continue
        resto = oid[len(PREFIXO_SUPRIMENTOS) + 1:].split(".")
        if len(resto) < 2:
            continue
        campo = campos.get(resto[0])
        if campo is None:
            continue
        # A MIB termina com <indice_do_marcador>.<indice_do_suprimento>:
        # e o ULTIMO que identifica a cor. Usar o do meio juntava todos os
        # cartuchos num so.
        indice = resto[-1]
        por_indice.setdefault(indice, {})[campo] = valor

    saida = []
    for indice, dados in sorted(por_indice.items()):
        nivel = _inteiro(dados.get("nivel"))
        capacidade = _inteiro(dados.get("capacidade"))
        pct = percentual_suprimento(nivel, capacidade)
        saida.append({
            "indice": indice,
            "descricao": _texto(dados.get("descricao")),
            "nivel": nivel,
            "capacidade": capacidade,
            "percentual": pct,
            "situacao": classificar_suprimento(pct),
        })
    return saida


def alertas_de_suprimento(suprimentos: list[dict]) -> list[dict]:
    """Quais suprimentos merecem aviso — e com que urgência.

    Só alerta o que é acionável: 'vazio' e 'critico' pedem compra; 'atencao'
    pede atenção; 'desconhecido' não vira alarme falso.
    """
    ordem = {"vazio": 0, "critico": 1, "atencao": 2}
    alertas = []
    for s in suprimentos:
        if s["situacao"] not in ordem:
            continue
        alertas.append({
            "descricao": s.get("descricao") or f"Suprimento {s.get('indice')}",
            "percentual": s["percentual"],
            "situacao": s["situacao"],
            "gravidade": {"vazio": "alta", "critico": "alta", "atencao": "media"}[s["situacao"]],
            "mensagem": {
                "vazio": "Suprimento vazio — troca imediata.",
                "critico": f"Suprimento em {s['percentual']}% — providenciar troca.",
                "atencao": f"Suprimento em {s['percentual']}% — acompanhar.",
            }[s["situacao"]],
        })
    return sorted(alertas, key=lambda a: ordem[a["situacao"]])


def estimar_duracao(
    percentual: float | None,
    contador_atual: int | None,
    contador_anterior: int | None,
    dias_entre_leituras: int | None,
) -> dict[str, Any]:
    """Quanto tempo o suprimento ainda dura, pelo ritmo real de impressão.

    Isto é o que evita ficar sem tonner: a **porcentagem sozinha não diz
    quando acaba**. 20% numa impressora de 50 páginas/dia dura semanas; numa
    de 5.000 páginas/dia dura horas.
    """
    if percentual is None or percentual <= 0:
        return {"aplicavel": False, "motivo": "sem percentual utilizável"}
    # is None e nao truthiness: contador 0 e legitimo - impressora nova
    # comeca em zero, e descartar isso perderia justamente as novas.
    if contador_atual is None or contador_anterior is None or not dias_entre_leituras:
        return {"aplicavel": False, "motivo": "sem histórico de contador"}
    if contador_atual <= contador_anterior or dias_entre_leituras <= 0:
        return {"aplicavel": False, "motivo": "sem consumo no período"}

    paginas = contador_atual - contador_anterior
    por_dia = paginas / dias_entre_leituras
    if por_dia <= 0:
        return {"aplicavel": False, "motivo": "sem consumo no período"}

    # Quanto do suprimento aquele consumo gastou, e o que resta.
    dias_restantes = (percentual / 100) * dias_entre_leituras * (100 / max(0.01, 100 - percentual)) \
        if percentual < 100 else 0
    # Cálculo direto, mais legível: se consumiu X páginas para cair para P%,
    # então cada 1% dura (páginas / (100 - P)) dias por ponto.
    consumido_pct = max(0.01, 100 - percentual)
    paginas_por_ponto = paginas / consumido_pct
    paginas_restantes = paginas_por_ponto * percentual
    dias_restantes = paginas_restantes / por_dia

    return {
        "aplicavel": True,
        "paginas_por_dia": round(por_dia, 1),
        "paginas_restantes_estimadas": int(paginas_restantes),
        "dias_restantes": int(dias_restantes),
        "situacao": (
            "urgente" if dias_restantes <= 7
            else "atencao" if dias_restantes <= 30
            else "tranquilo"
        ),
    }


# ---------------------------------------------------------------------------
# Transporte — a única parte que precisa de rede.
# ---------------------------------------------------------------------------
class SNMPIndisponivel(RuntimeError):
    """A biblioteca de SNMP não está instalada."""


def disponivel() -> bool:
    try:
        import pysnmp  # noqa: F401
    except ImportError:
        return False
    return True


def coletar(host: str, comunidade: str = "public", timeout_s: int = 3) -> dict[str, Any]:
    """Consulta a impressora por SNMP.

    Sem a biblioteca instalada, falha com instrução — em vez de dizer apenas
    'erro'. A interpretação (`mapear`) funciona sem ela.
    """
    if not disponivel():
        raise SNMPIndisponivel(
            "O suporte a SNMP precisa da biblioteca pysnmp. "
            "Instale com: pip install pysnmp"
        )

    import asyncio

    from pysnmp.hlapi.v3arch.asyncio import (  # type: ignore
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        get_cmd,
    )

    async def _consultar() -> dict[str, Any]:
        engine = SnmpEngine()
        alvo = await UdpTransportTarget.create((host, 161), timeout=timeout_s, retries=1)

        respostas: dict[str, Any] = {}
        for nome, oid in OIDS.items():
            erro, _, _, var = await get_cmd(
                engine, CommunityData(comunidade, mpModel=1), alvo, ContextData(),
                ObjectType(ObjectIdentity(oid)),
            )
            if erro or not var:
                continue
            valor = var[0][1]
            texto = str(valor)
            # 'No Such Instance' é a impressora dizendo que não tem esse OID.
            if "No Such" in texto or "No more" in texto:
                continue
            respostas[nome] = valor
        return respostas

    return mapear(asyncio.run(_consultar()))


def carimbo() -> str:
    return datetime.now(timezone.utc).isoformat()


def varrer_suprimentos(endereco: str, comunidade: str = "public", timeout_s: int = 4) -> list[tuple[str, Any]]:
    """Percorre a tabela de suprimentos da impressora (SNMP walk).

    Um `get` só traria o primeiro cartucho — numa colorida, o ciano vazio
    ficaria invisível. A varredura traz todos.

    Devolve pares `(oid, valor)` — a tradução fica com `extrair_suprimentos`,
    que é pura e testável.
    """
    if not disponivel():
        raise SNMPIndisponivel(
            "O suporte a SNMP precisa da biblioteca pysnmp. "
            "Instale com: pip install pysnmp"
        )

    import asyncio

    from pysnmp.hlapi.v3arch.asyncio import (  # type: ignore
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        walk_cmd,
    )

    async def _varrer() -> list[tuple[str, Any]]:
        engine = SnmpEngine()
        alvo = await UdpTransportTarget.create((endereco, 161), timeout=timeout_s, retries=1)
        pares: list[tuple[str, Any]] = []

        iterator = walk_cmd(
            engine, CommunityData(comunidade, mpModel=1), alvo, ContextData(),
            ObjectType(ObjectIdentity(PREFIXO_SUPRIMENTOS)),
            lexicographicMode=False,
        )
        async for erro, _, _, var_binds in iterator:
            if erro:
                break
            for nome, valor in var_binds:
                pares.append((str(nome), valor))
        return pares

    return asyncio.run(_varrer())
