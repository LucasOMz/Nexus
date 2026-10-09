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
