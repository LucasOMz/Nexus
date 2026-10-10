"""NF-e (XML) — entrada de ativo pela nota fiscal.

O que hoje se faz digitando à mão: descrição, valor, fornecedor, data e série
do equipamento **já estão no XML** que a empresa recebe. Ler a nota economiza
a digitação e encaixa o cadastro no fiscal brasileiro.

## O que este módulo faz

Lê o XML, valida a **chave de acesso** (44 dígitos, com dígito verificador) e
monta uma **sugestão** de cadastro. Não grava nada por conta própria.

## Por que não grava sozinho

Uma NF-e pode ter 200 itens, e nem todos são patrimônio: cabos, suprimentos e
material de escritório vêm na mesma nota. Criar tudo automaticamente encheria
o inventário de coisas que ninguém vai etiquetar. O sistema **sugere**, e a
pessoa escolhe o que vira ativo.

Só usa a biblioteca padrão (`xml.etree`) — sem dependência nova.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405 - XML de origem conhecida, ver `_seguro`
from datetime import datetime, timezone
from typing import Any

NS = "{http://www.portalfiscal.inf.br/nfe}"

# Pesos do dígito verificador da chave de acesso (módulo 11).
_PESOS = [2, 3, 4, 5, 6, 7, 8, 9]


def _tag(nome: str) -> str:
    return f"{NS}{nome}"


def _texto(no, caminho: str) -> str | None:
    achado = no.find(caminho) if no is not None else None
    if achado is None or achado.text is None:
        return None
    valor = achado.text.strip()
    return valor or None


def _decimal(valor: Any) -> float | None:
    if valor is None:
        return None
    texto = str(valor).strip().replace(".", "").replace(",", ".") if "," in str(valor) else str(valor).strip()
    try:
        return round(float(texto), 2)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
def chave_valida(chave: str | None) -> bool:
    """Confere a chave de acesso da NF-e (44 dígitos, módulo 11).

    Vale a pena validar: a chave é a identidade fiscal do documento. Aceitar
    uma chave errada significa vincular o ativo a uma nota que não existe — e
    descobrir isso só na auditoria.
    """
    if not chave:
        return False
    digitos = re.sub(r"\D", "", str(chave))
    if len(digitos) != 44:
        return False
    if len(set(digitos)) == 1:      # 0000... e 1111... passariam no cálculo
        return False

    corpo = digitos[:43]
    soma = 0
    peso = 0
    for d in reversed(corpo):
        soma += int(d) * _PESOS[peso % len(_PESOS)]
        peso += 1
    resto = soma % 11
    dv = 0 if resto < 2 else 11 - resto
    return dv == int(digitos[43])


def _seguro(xml: str | bytes) -> None:
    """Recusa XML com DTD/entidade externa (XXE).

    O arquivo vem de fora — do e-mail do fornecedor, de um portal. Um XML com
    `<!DOCTYPE` pode tentar ler arquivos do servidor.
    """
    texto = xml.decode("utf-8", "ignore") if isinstance(xml, bytes) else xml
    cabeca = texto[:2000].upper()
    if "<!DOCTYPE" in cabeca or "<!ENTITY" in cabeca:
        raise ValueError("XML com DTD/entidade não é aceito por segurança.")


def parse_nfe(xml: str | bytes) -> dict[str, Any]:
    """Lê a NF-e e devolve o que interessa para o cadastro.

    Aceita tanto o XML completo (`<nfeProc>`, com protocolo) quanto só a
    `<NFe>` — os dois formatos aparecem na prática.
    """
    _seguro(xml)
    try:
        raiz = ET.fromstring(xml)  # noqa: S314 - validado acima
    except ET.ParseError as e:
        raise ValueError(f"XML inválido: {e}") from e

    inf = raiz.find(f".//{_tag('infNFe')}")
    if inf is None:
        raise ValueError("Este XML não parece uma NF-e (falta o bloco infNFe).")

    chave = _texto(inf, "infNFe")  # não usado; a chave vem do atributo
    chave = (inf.get("Id") or "").replace("NFe", "").strip() or None

    emit = inf.find(_tag("emit"))
    dest = inf.find(_tag("dest"))
    ide = inf.find(_tag("ide"))
    total = inf.find(f"{_tag('total')}/{_tag('ICMSTot')}")

    itens = []
    for det in inf.findall(_tag("det")):
        prod = det.find(_tag("prod"))
        if prod is None:
            continue
        item = {
            "numero": det.get("nItem"),
            "codigo": _texto(prod, _tag("cProd")),
            "descricao": _texto(prod, _tag("xProd")),
            "ncm": _texto(prod, _tag("NCM")),
            "cfop": _texto(prod, _tag("CFOP")),
            "unidade": _texto(prod, _tag("uCom")),
            "quantidade": _decimal(_texto(prod, _tag("qCom"))),
            "valor_unitario": _decimal(_texto(prod, _tag("vUnCom"))),
            "valor_total": _decimal(_texto(prod, _tag("vProd"))),
            "informacoes": _texto(det, f"{_tag('infAdProd')}"),
        }
        # Série e número de patrimônio do fornecedor costumam vir aqui — e são
        # justamente o que se digitaria à mão.
        item["series"] = extrair_series(item["informacoes"] or "")
        itens.append(item)

    return {
        "chave": chave,
        "chave_valida": chave_valida(chave),
        "numero": _texto(ide, _tag("nNF")),
        "serie": _texto(ide, _tag("serie")),
        "emitida_em": _texto(ide, _tag("dhEmi")) or _texto(ide, _tag("dEmi")),
        "natureza": _texto(ide, _tag("natOp")),
        "emitente": {
            "cnpj": _texto(emit, _tag("CNPJ")) or _texto(emit, _tag("CPF")),
            "nome": _texto(emit, _tag("xNome")),
            "fantasia": _texto(emit, _tag("xFant")),
            "ie": _texto(emit, _tag("IE")),
            "municipio": _texto(emit, f"{_tag('enderEmit')}/{_tag('xMun')}"),
            "uf": _texto(emit, f"{_tag('enderEmit')}/{_tag('UF')}"),
        },
        "destinatario": {
            "cnpj": _texto(dest, _tag("CNPJ")) or _texto(dest, _tag("CPF")),
            "nome": _texto(dest, _tag("xNome")),
        },
        "valor_total": _decimal(_texto(total, _tag("vNF"))),
        "valor_produtos": _decimal(_texto(total, _tag("vProd"))),
        "itens": itens,
    }


def extrair_series(texto: str) -> list[str]:
    """Procura números de série no texto livre da nota.

    Cada fornecedor escreve de um jeito: "S/N: ABC123", "SERIE ABC123",
    "NS ABC123, DEF456". Não dá para exigir um formato — dá para reconhecer os
    mais comuns e deixar a pessoa conferir.
    """
    if not texto:
        return []
    achados: list[str] = []
    padrao = re.compile(
        r"(?:s/?n|serial|s[eé]rie|ns)\s*[:\-]?\s*([A-Za-z0-9][A-Za-z0-9\-\./]{3,30})",
        re.IGNORECASE,
    )
    for m in padrao.finditer(texto):
        bruto = m.group(1).strip(" .,;")
        # Separa listas: "ABC123, DEF456" vira dois.
        for parte in re.split(r"[,\s]+", bruto):
            parte = parte.strip(" .,;")
            if len(parte) >= 4 and parte not in achados:
                achados.append(parte)
    return achados


def sugerir_ativo(item: dict, nfe: dict) -> dict[str, Any]:
    """Pré-preenche o cadastro do ativo a partir de um item da nota.

    Sugere, não define: `dominio`, `categoria` e `tipo_item` dependem da
    organização de cada empresa, e chutar isso criaria dado errado.
    """
    # Uma NF-e não traz a garantia. O que dá para estimar é a referência:
    # 12 meses é o prazo legal para bens duráveis (CDC), e serve de ponto de
    # partida — a pessoa ajusta se o fornecedor der mais.
    emitida = _data_nfe(nfe.get("emitida_em"))
    garantia = None
    if emitida is not None:
        garantia = emitida.replace(year=emitida.year + 1).date().isoformat()

    return {
        "descricao_original": item.get("descricao"),
        "modelo": item.get("descricao"),
        "numero_serie": (item.get("series") or [None])[0],
        "series_encontradas": item.get("series") or [],
        "valor": item.get("valor_unitario") or item.get("valor_total"),
        "data_aquisicao": emitida.date().isoformat() if emitida else None,
        "data_garantia": garantia,
        "fornecedor": nfe.get("emitente", {}).get("nome"),
        "fornecedor_cnpj": nfe.get("emitente", {}).get("cnpj"),
        "nota_fiscal": nfe.get("numero"),
        "nota_chave": nfe.get("chave"),
        "ncm": item.get("ncm"),
        # O que a pessoa ainda precisa decidir.
        "a_definir": ["patrimônio", "domínio", "categoria", "localização"],
    }


def _data_nfe(valor: Any) -> datetime | None:
    if not valor:
        return None
    texto = str(valor).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(texto)
    except (ValueError, TypeError):
        try:
            d = datetime.strptime(str(valor)[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def resumo(nfe: dict) -> dict[str, Any]:
    """O que a tela mostra antes de a pessoa escolher os itens."""
    itens = nfe.get("itens") or []
    com_serie = [i for i in itens if i.get("series")]
    return {
        "chave": nfe.get("chave"),
        "chave_valida": nfe.get("chave_valida"),
        "fornecedor": nfe.get("emitente", {}).get("nome"),
        "emitida_em": nfe.get("emitida_em"),
        "itens": len(itens),
        "itens_com_serie": len(com_serie),
        "valor_total": nfe.get("valor_total"),
        "aviso": (
            None if nfe.get("chave_valida")
            else "A chave de acesso desta nota não confere — confira o arquivo antes de usar."
        ),
    }
