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


class TipoLicenca(StrEnum):
    """A natureza do direito de uso.

    Muda o que faz sentido calcular, como `FormaAquisicao` faz para o
    equipamento:

    - **Perpétua** tem valor e vira ativo intangível. Não vence.
    - **Assinatura** é serviço: o custo é mensal e o direito acaba quando o
      pagamento para. Nunca vira patrimônio.
    - **OEM** vem colada na máquina e **não pode ser transferida** — por isso
      a atribuição dela precisa apontar para um ativo.
    - **Volume** é um contrato de N atos: um número de série cobre vários seats.
    - **Open source** não tem chave nem custo, mas é cadastrada para o
      relatório de conformidade saber que o uso é legítimo.
    """

    PERPETUA = "perpetua"
    ASSINATURA = "assinatura"
    OEM = "oem"
    VOLUME = "volume"
    OPEN_SOURCE = "open_source"
    TRIAL = "trial"


class SituacaoLicenca(StrEnum):
    """Onde a licença está na vida útil dela.

    Diferente de "vencida": uma licença pode estar **suspensa** por decisão
    (contrato em disputa, fim de projeto) antes de a data chegar — e o
    relatório precisa distinguir as duas, porque a ação é diferente.
    """

    ATIVA = "ativa"
    SUSPENSA = "suspensa"
    EXPIRADA = "expirada"
    CANCELADA = "cancelada"


class PlataformaSoftware(StrEnum):
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    ANDROID = "android"
    IOS = "ios"
    WEB = "web"
    # Para o que roda em qualquer lugar (navegador, Java, agente).
    MULTIPLATAFORMA = "multiplataforma"


class SituacaoConformidade(StrEnum):
    """O resultado do cruzamento instalado × licenciado.

    ## Por que "ocioso" existe

    Comprar 50 seats e usar 31 é dinheiro parado. Um relatório que só acusa
    excesso esconde a metade que ninguém procura — porque não há risco legal
    nela, só financeiro.
    """

    CONFORME = "conforme"
    EXCEDENTE = "excedente"      # instalado > licenciado — risco em auditoria
    OCIOSO = "ocioso"            # instalado < licenciado — dinheiro parado
    SEM_LICENCA = "sem_licenca"  # instalado e nenhuma licença cadastrada
    NAO_INSTALADO = "nao_instalado"


class MetricaLicenca(StrEnum):
    """Como a licença é CONTADA — e por que isso muda o número.

    ## O problema que este campo resolve

    O OCS conta **máquinas**. A licença conta **seats**. Para o Office LTSC,
    os dois são a mesma coisa: o direito acompanha o computador.

    Para Microsoft 365 e Adobe CC, **não são**: o seat é por PESSOA, e uma
    pessoa pode usar dois computadores.

        Você tem 10 licenças. 10 pessoas usam.
        Maria tem notebook e desktop → 11 máquinas com o programa instalado.
        → o sistema compara 11 instalações com 10 seats e acusa EXCEDENTE.

    Está errado, e o erro **custa dinheiro**: alguém compra uma licença que
    não falta. E piora a cada máquina nova, mesmo sem entrar gente nova.

    ## Por que o campo não tem padrão silencioso

    A escolha é **perguntada**, não assumida. Um valor padrão faria o
    operador passar reto e o cálculo seguir errado sem ninguém perceber —
    que é exatamente o problema que este campo existe para resolver.
    """

    DISPOSITIVO = "dispositivo"
    USUARIO = "usuario"
