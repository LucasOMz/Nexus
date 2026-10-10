"""Enums de domínio como `StrEnum` (Python 3.11+).

Os valores são persistidos como STRING (portátil entre SQLite e PostgreSQL).
Em produção (schema.sql) existem os ENUMs nativos equivalentes.
"""
from __future__ import annotations

from enum import StrEnum


class Dominio(StrEnum):
    TI = "ti"
    IMPRESSORA = "impressora"


class TipoItem(StrEnum):
    ATIVO = "ativo"
    CONSUMIVEL = "consumivel"


class StatusAtivo(StrEnum):
    ESTOQUE = "estoque"
    RESERVADO = "reservado"
    EM_USO = "em_uso"
    MANUTENCAO = "manutencao"
    DESCARTADO = "descartado"
    EMPRESTADO = "emprestado"


class TipoMov(StrEnum):
    ENTRADA = "entrada"
    SAIDA = "saida"
    TRANSFERENCIA = "transferencia"
    ATRIBUICAO = "atribuicao"
    DEVOLUCAO = "devolucao"
    BAIXA = "baixa"


class PapelUsuario(StrEnum):
    ADMIN = "admin"
    TI = "ti"
    LEITOR = "leitor"
    AUDITOR = "auditor"


class StatusManut(StrEnum):
    ABERTA = "aberta"
    EM_ANDAMENTO = "em_andamento"
    CONCLUIDA = "concluida"
    CANCELADA = "cancelada"


class TipoImpressao(StrEnum):
    LASER = "laser"
    JATO = "jato"
    TERMICA = "termica"
    MATRICIAL = "matricial"
    PLOTTER = "plotter"


class Conectividade(StrEnum):
    USB = "usb"
    REDE = "rede"
    WIFI = "wifi"
    PARALELA = "paralela"
    SERIAL = "serial"


class TipoSuprimento(StrEnum):
    TONER = "toner"
    CARTUCHO = "cartucho"
    FITA = "fita"
    CILINDRO = "cilindro"
    PAPEL = "papel"
    OUTRO = "outro"


class FormaAquisicao(StrEnum):
    """Como o equipamento chegou ao parque.

    Muda o que faz sentido calcular: comprado deprecia e tem valor
    patrimonial; locado custa mensalidade e **não** é patrimônio da empresa
    (depreciá-lo mediria um bem que não é dela).

    O padrão é COMPRADO de propósito: todo ativo cadastrado antes deste campo
    existir foi tratado como comprado, e assim continua correto sem migração
    de dado.
    """

    COMPRADO = "comprado"
    LOCADO = "locado"


class TipoContrato(StrEnum):
    LOCACAO = "locacao"
    # Comodato: o equipamento é cedido sem mensalidade. Existe para o caso de
    # fornecedor que empresta em troca de exclusividade de suprimentos.
    COMODATO = "comodato"
    COMPRA = "compra"
