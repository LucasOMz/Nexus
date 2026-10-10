"""Descarte de equipamento — certificado e rastreabilidade.

Descartar eletrônico sem rastreabilidade é **passivo ambiental**. A Política
Nacional de Resíduos Sólidos (Lei 12.305/2010) responsabiliza o gerador pelo
destino do resíduo — inclusive depois de entregue a terceiros. O Decreto
10.240/2020 exige que a destinação seja comprovada.

O que isso significa na prática: **quem descarta precisa conseguir provar para
onde foi, quando e por quem**. Um sistema que emite esse documento protege a
empresa.

## Por que o motivo do descarte importa tanto

Cada motivo tem **exigência documental diferente** — e tratar todos igual é o
erro comum:

* sucata/reciclagem → destinador **licenciado**, com número de licença
* doação → beneficiário identificado e termo de doação
* venda → nota fiscal de saída
* perda/roubo → boletim de ocorrência
* devolução ao fornecedor → comprovante de RMA

Guardar isso no sistema evita que, três anos depois, ninguém saiba se aquele
notebook foi reciclado ou sumiu.
"""
from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from typing import Any

# Motivos e o que cada um exige para o certificado ser válido.
MOTIVOS: dict[str, dict[str, Any]] = {
    "sucata": {
        "rotulo": "Sucata / Reciclagem",
        "exige": ["destinador_nome", "destinador_cnpj", "destinador_licenca"],
        "fundamento": "PNRS Art. 33 — logística reversa",
    },
    "doacao": {
        "rotulo": "Doação",
        "exige": ["destinador_nome", "destinador_documento"],
        "fundamento": "Doação a terceiro — exige termo assinado",
    },
    "venda": {
        "rotulo": "Venda / Leilão",
        "exige": ["destinador_nome", "destinador_documento", "documento_fiscal"],
        "fundamento": "Saída com nota fiscal",
    },
    "perda": {
        "rotulo": "Perda / Roubo / Furto",
        "exige": ["numero_ocorrencia"],
        "fundamento": "Boletim de ocorrência",
    },
    "devolucao": {
        "rotulo": "Devolução ao fornecedor",
        "exige": ["destinador_nome", "documento_fiscal"],
        "fundamento": "RMA / garantia — o bem sai do patrimônio",
    },
    "transferencia": {
        "rotulo": "Transferência entre plantas",
        "exige": [],
        "fundamento": "Não é descarte — o bem continua no patrimônio",
    },
}

# Marca se o bem precisa de logística reversa (eletrônico).
CATEGORIAS_LOGISTICA_REVERSA = {
    "informatica", "eletronico", "eletrodomestico", "telefonia",
    "bateria", "pilha", "lampada",
}


def precisa_logistica_reversa(categoria: str | None) -> bool:
    """Eletrônico tem destinação obrigatória; móvel, não.

    A PNRS trata eletroeletrônico como resíduo de logística reversa
    obrigatória — uma cadeira descartada não tem essa exigência.
    """
    if not categoria:
        return False
    # Sem acento: Eletrônico e eletronico precisam casar - quem digita o
    # cadastro nao segue um padrao unico.
    limpa = unicodedata.normalize("NFKD", categoria.strip().lower())
    limpa = "".join(ch for ch in limpa if not unicodedata.combining(ch))
    return limpa in CATEGORIAS_LOGISTICA_REVERSA


def validar(dados: dict[str, Any]) -> dict[str, Any]:
    """O que falta para o certificado ser defensável.

    Devolve a lista de pendências **com o motivo de cada uma** — não só
    'campo obrigatório'. Quem descarta precisa entender por que importa.
    """
    motivo = (dados.get("motivo") or "").strip().lower()
    if motivo not in MOTIVOS:
        return {
            "ok": False,
            "pendencias": [f"Motivo inválido. Use um destes: {', '.join(MOTIVOS)}."],
            "exigidos": [],
        }

    regra = MOTIVOS[motivo]
    pendencias = []
    for campo in regra["exige"]:
        if not (dados.get(campo) or "").strip() if isinstance(dados.get(campo), str) else not dados.get(campo):
            pendencias.append(campo)

    if not (dados.get("patrimonio") or "").strip():
        pendencias.append("patrimonio")
    if not dados.get("quantidade") or int(dados.get("quantidade") or 0) < 1:
        pendencias.append("quantidade")
    if not (dados.get("responsavel") or "").strip():
        pendencias.append("responsavel")

    rotulos = {
        "destinador_nome": "Nome de quem recebe o material",
        "destinador_cnpj": "CNPJ do destinador",
        "destinador_documento": "Documento do destinatário",
        "destinador_licenca": "Número da licença ambiental do destinador (exigida na logística reversa)",
        "documento_fiscal": "Documento fiscal de saída",
        "numero_ocorrencia": "Número do boletim de ocorrência",
        "patrimonio": "Patrimônio do equipamento",
        "quantidade": "Quantidade descartada",
        "responsavel": "Responsável pelo descarte",
    }
    return {
        "ok": not pendencias,
        "pendencias": pendencias,
        "mensagens": [rotulos.get(p, p) for p in pendencias],
        "exigidos": regra["exige"],
        "rotulo_motivo": regra["rotulo"],
        "fundamento": regra["fundamento"],
    }


def montar(dados: dict[str, Any], agora: datetime | None = None) -> dict[str, Any]:
    """Monta o conteúdo do certificado.

    Recusa certificado incompleto: um documento com campo em branco não
    protege ninguém numa fiscalização — e dá falsa sensação de cobertura.
    """
    checagem = validar(dados)
    if not checagem["ok"]:
        raise ValueError(
            "Certificado incompleto: " + "; ".join(checagem.get("mensagens", checagem["pendencias"]))
        )

    momento = agora or datetime.now(timezone.utc)
    motivo = dados["motivo"].strip().lower()
    regra = MOTIVOS[motivo]

    conteudo = {
        "emitido_em": momento.isoformat(),
        "motivo": motivo,
        "motivo_rotulo": regra["rotulo"],
        "fundamento_legal": regra["fundamento"],
        "logistica_reversa": precisa_logistica_reversa(dados.get("categoria")),

        "empresa": {
            "nome": dados.get("empresa_nome"),
            "cnpj": dados.get("empresa_cnpj"),
            "planta": dados.get("planta_nome"),
        },
        "equipamento": {
            "patrimonio": dados.get("patrimonio"),
            "descricao": dados.get("descricao"),
            "marca": dados.get("marca"),
            "modelo": dados.get("modelo"),
            "numero_serie": dados.get("numero_serie"),
            "categoria": dados.get("categoria"),
            "valor_contabil": dados.get("valor"),
        },
        "destinacao": {
            "quantidade": int(dados.get("quantidade") or 1),
            "destinador_nome": dados.get("destinador_nome"),
            "destinador_cnpj": dados.get("destinador_cnpj"),
            "destinador_documento": dados.get("destinador_documento"),
            "destinador_licenca": dados.get("destinador_licenca"),
            "documento_fiscal": dados.get("documento_fiscal"),
            "numero_ocorrencia": dados.get("numero_ocorrencia"),
        },
        "responsavel": dados.get("responsavel"),
        "observacoes": dados.get("observacoes"),
    }
    conteudo["hash"] = _hash(conteudo)
    conteudo["numero"] = _numero_certificado(momento, conteudo["hash"])
    return conteudo


def _hash(conteudo: dict[str, Any]) -> str:
    """Impressão digital do certificado.

    Ficam de fora os campos DERIVADOS do próprio hash: `hash` e `numero`. Se
    entrassem, o cálculo nunca fecharia — o número nasce do hash, que mudaria
    ao incluir o número.
    """
    base = {k: v for k, v in conteudo.items() if k not in ("hash", "numero")}
    texto = json.dumps(base, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _numero_certificado(momento: datetime, hash_conteudo: str) -> str:
    """Número legível e rastreável: CAD-AAAA-MM-XXXXXX."""
    return f"CAD-{momento:%Y-%m}-{hash_conteudo[:6].upper()}"


def conferir(conteudo: dict[str, Any]) -> bool:
    """O certificado foi alterado depois de emitido?

    Recalcula o hash e compara. É o que transforma o documento em prova: sem
    isso, qualquer um edita o arquivo e o certificado continua "válido".
    """
    if not conteudo.get("hash"):
        return False
    return _hash(conteudo) == conteudo["hash"]


def texto(conteudo: dict[str, Any]) -> str:
    """Versão em texto do certificado — assinável e arquivável.

    Em texto puro de propósito: abre em qualquer lugar, daqui a dez anos,
    sem depender de nenhum programa.
    """
    e = conteudo.get("equipamento", {})
    d = conteudo.get("destinacao", {})
    emp = conteudo.get("empresa", {})

    linhas = [
        "=" * 68,
        "CERTIFICADO DE DESCARTE DE EQUIPAMENTO",
        f"Nº {conteudo.get('numero', '—')}",
        "=" * 68,
        "",
        f"EMITIDO EM: {conteudo.get('emitido_em', '').replace('T', ' ')[:19]}",
        "",
        "GERADOR",
        f"  Empresa ....: {emp.get('nome') or '—'}",
        f"  CNPJ .......: {emp.get('cnpj') or '—'}",
        f"  Planta .....: {emp.get('planta') or '—'}",
        "",
        "EQUIPAMENTO",
        f"  Patrimônio .: {e.get('patrimonio') or '—'}",
        f"  Descrição ..: {e.get('descricao') or '—'}",
        f"  Marca/Modelo: {' '.join(filter(None, [e.get('marca'), e.get('modelo')])) or '—'}",
        f"  Nº de série : {e.get('numero_serie') or '—'}",
        f"  Categoria ..: {e.get('categoria') or '—'}",
        f"  Quantidade .: {d.get('quantidade', 1)}",
        "",
        "DESTINAÇÃO",
        f"  Motivo .....: {conteudo.get('motivo_rotulo') or '—'}",
        f"  Fundamento .: {conteudo.get('fundamento_legal') or '—'}",
        f"  Destinador .: {d.get('destinador_nome') or '—'}",
        f"  CNPJ/Doc ...: {d.get('destinador_cnpj') or d.get('destinador_documento') or '—'}",
        f"  Licença amb.: {d.get('destinador_licenca') or '—'}",
        f"  Doc. fiscal : {d.get('documento_fiscal') or '—'}",
        f"  Ocorrência .: {d.get('numero_ocorrencia') or '—'}",
    ]

    if conteudo.get("logistica_reversa"):
        linhas += [
            "",
            "LOGÍSTICA REVERSA",
            "  Resíduo eletroeletrônico sujeito a destinação obrigatória",
            "  (PNRS, Lei 12.305/2010, Art. 33).",
        ]

    linhas += [
        "",
        "RESPONSÁVEL",
        f"  {conteudo.get('responsavel') or '—'}",
        "",
    ]
    if conteudo.get("observacoes"):
        linhas += ["OBSERVAÇÕES", f"  {conteudo['observacoes']}", ""]

    linhas += [
        "-" * 68,
        f"Autenticidade: {conteudo.get('hash', '')}",
        "Confira este código no sistema para verificar se o documento não foi alterado.",
        "=" * 68,
    ]
    return "\n".join(linhas)


def resumo(conteudo: dict[str, Any]) -> dict[str, Any]:
    return {
        "numero": conteudo.get("numero"),
        "patrimonio": conteudo.get("equipamento", {}).get("patrimonio"),
        "motivo": conteudo.get("motivo_rotulo"),
        "quantidade": conteudo.get("destinacao", {}).get("quantidade"),
        "destinador": conteudo.get("destinacao", {}).get("destinador_nome"),
        "emitido_em": conteudo.get("emitido_em"),
        "logistica_reversa": conteudo.get("logistica_reversa"),
        "integro": conferir(conteudo),
    }
