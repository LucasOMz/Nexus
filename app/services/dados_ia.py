"""Consultas de leitura específicas dos módulos que o chat pode usar."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from json import JSONDecodeError, loads
from typing import Literal
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from app.core.planta import aplicar_filtro
from app.models import Ativo, AtivoImpressora, AtivoTI, Contagem, Contrato, Emprestimo, LeituraContador, Manutencao, Movimentacao
from app.models import Planta, PlantaLocalidade, Produto, SoftwareInstalado, SuprimentoImpressora, Usuario
from app.models.emprestimo import SituacaoEmprestimo
from app.models.enums import Dominio, StatusManut, TipoMov
from app.services.conhecimento_ia import link_nexus
from app.services.inventario_ia import FUSO_INVENTARIO, Filtro, resolver_cadastro


class ConsultaFicha(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    identificador: str = Field(min_length=1, max_length=160, description="Patrimônio, número de série ou hostname exato.")
    planta: str | None = Field(default=None, max_length=120)
    assunto: Literal["completa", "cadastro", "hardware", "rede", "impressao", "contador", "suprimentos",
                     "comunicacao", "software", "manutencao", "aquisicao", "uso"] = "completa"


class ConsultaConsumiveis(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    termo: str | None = Field(default=None, max_length=160, description="SKU, nome ou trecho do nome.")
    operacao: Literal["listar", "contar", "estoque", "abaixo_minimo", "movimentacoes"] = "listar"
    dominio: Literal["ti", "impressora"] | None = None
    planta: str | None = Field(default=None, max_length=120)


class ConsultaIndicadores(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    indicador: Literal["manutencoes_abertas", "emprestimos_atrasados", "contratos_a_vencer",
                       "contagens", "garantias_a_vencer", "parque_financeiro"]
    planta: str | None = Field(default=None, max_length=120)
    dias: int = Field(default=30, ge=1, le=365)
    dominio: Literal["ti", "impressora"] | None = None


def _plantas_permitidas(db: Session, planta: str, planta_id: int | None) -> dict[int, str]:
    catalogo = db.query(Planta.id, Planta.nome, Planta.sigla, Planta.cidade, PlantaLocalidade.codigo).outerjoin(
        PlantaLocalidade, Planta.id == PlantaLocalidade.planta_id,
    ).filter(Planta.deleted_at.is_(None))
    if planta_id is not None:
        catalogo = catalogo.filter(Planta.id == planta_id)
    return resolver_cadastro(catalogo.all(), Filtro(campo="planta", operador="igual", valor=planta))


def informacoes(resumo: str, *, blocos=(), links=(), modulos=()) -> dict:
    return {"tipo": "informacoes", "resumo": resumo, "blocos": list(blocos),
            "links": list(links), "modulos_dados": sorted(modulos)}


def _linhas(consulta, limite: int, completo: bool):
    return consulta.all() if completo else consulta.limit(limite).all()


def _valor(valor):
    if isinstance(valor, datetime):
        instante = valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
        return instante.astimezone(ZoneInfo(FUSO_INVENTARIO)).strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, Enum):
        return valor.value.replace("_", " ")
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if isinstance(valor, Decimal):
        return str(valor).replace(".", ",")
    return valor


def _bloco(titulo: str, *dados: tuple) -> dict:
    return {"titulo": titulo, "linhas": [[rotulo, _valor(valor) if valor not in (None, "") else "Não cadastrado"]
                                        for rotulo, valor in dados]}


def _inventario(ficha: AtivoTI | None) -> dict:
    if ficha is None:
        return {}
    try:
        detalhes = loads(ficha.inventario_json or "{}")
    except (JSONDecodeError, TypeError):
        return {}
    return detalhes if isinstance(detalhes, dict) else {}


def _inventario_lista(detalhes: dict, chave: str, completo: bool) -> list[dict]:
    itens = detalhes.get(chave)
    return [item for item in (itens if completo else itens[:20]) if isinstance(item, dict)] if isinstance(itens, list) else []


def _juntar(*valores) -> str:
    return " · ".join(str(v) for v in valores if isinstance(v, (str, int, float)) and v != "")


def _hardware(ficha: AtivoTI | None, detalhes: dict, completo: bool) -> list[dict]:
    if ficha is None:
        return [_bloco("Hardware", ("Ficha", "Sem ficha técnica cadastrada"))]
    basico = _bloco("Hardware",
        ("Processador", ficha.cpu), ("RAM (GB)", ficha.ram_gb), ("Armazenamento (GB)", ficha.armazenamento_gb),
        ("Sistema operacional", ficha.so), ("GPU", _juntar(detalhes.get("gpu"))),
        ("BIOS", _juntar(detalhes.get("bios_versao"))),
        ("Placa-mãe", _juntar(detalhes.get("placa_mae_fabricante"), detalhes.get("placa_mae"))),
        ("Última coleta do agente", ficha.inventario_em))
    blocos = [basico]
    discos = _inventario_lista(detalhes, "discos", completo)
    if discos:
        blocos.append(_bloco("Discos", *[(_juntar(d.get("modelo"), d.get("tipo")) or "Disco",
                                         _juntar(f'{d["gb"]} GB' if isinstance(d.get("gb"), (int, float)) else None,
                                                 d.get("serial"))) for d in discos]))
    monitores = _inventario_lista(detalhes, "monitores", completo)
    if monitores:
        blocos.append(_bloco("Monitores", *[(_juntar(m.get("fabricante"), m.get("modelo")) or "Monitor",
                                            _juntar(m.get("serial"))) for m in monitores]))
    return blocos


def _impressao(db: Session, ativo: Ativo, assunto: str, completo: bool) -> list[dict]:
    blocos = []
    ficha = ativo.impressora
    if assunto in {"completa", "impressao", "contador"}:
        leitura = db.query(LeituraContador).filter(
            LeituraContador.ativo_id == ativo.id, LeituraContador.deleted_at.is_(None),
        ).order_by(LeituraContador.data_leitura.desc(), LeituraContador.id.desc()).first()
        blocos.append(_bloco("Impressão e contador",
            ("Tipo de impressão", ficha.tipo_impressao if ficha else None), ("Colorida", ficha.colorida if ficha else None),
            ("Conectividade", ficha.conectividade if ficha else None), ("Driver", ficha.driver if ficha else None),
            ("Contador cadastrado", ficha.contador_paginas if ficha else None),
            ("Última leitura de páginas", leitura.contador if leitura else None),
            ("Data da leitura", leitura.data_leitura if leitura else None)))
    if assunto in {"completa", "suprimentos"}:
        consulta = db.query(SuprimentoImpressora).filter(
            SuprimentoImpressora.ativo_id == ativo.id, SuprimentoImpressora.deleted_at.is_(None),
        ).order_by(SuprimentoImpressora.id)
        blocos.append(_bloco("Suprimentos cadastrados", *[
            (f"{_valor(item.tipo)} · {item.modelo or item.cor or 'sem modelo'}",
             f"Cor {item.cor or 'não cadastrada'} · estoque {item.estoque_atual} · mínimo {item.estoque_minimo}"
             + (f" · rendimento {item.rendimento_paginas} páginas" if item.rendimento_paginas else ""))
            for item in _linhas(consulta, 20, completo)
        ] or [("Cadastro", "Nenhum suprimento registrado")]))
    return blocos


def _bloco_monitor(db: Session, ativo: Ativo, user: Usuario, planta_id: int | None) -> dict:
    from app.routers.monitor_impressoras import situacao_da_impressora

    dados = situacao_da_impressora(ativo.id, db=db, user=user, planta_id=planta_id)
    estado = {
        "online": "Online via SNMP", "sem_resposta": "Sem resposta ao SNMP", "sem_endereco": "Sem endereço cadastrado",
        "indisponivel": "SNMP indisponível", "falha_na_consulta": "Falha na consulta SNMP",
    }.get(dados["comunicacao"], "Comunicação desconhecida")
    niveis = [(item.get("nome") or item.get("descricao") or "Suprimento",
               f'{item["percentual"]}%' if item.get("percentual") is not None else "Nível indisponível")
              for item in dados["suprimentos"]]
    return _bloco("Monitoramento da impressora", ("Comunicação", estado), ("Verificado em", dados["verificado_em"]), *niveis)


def consultar_ficha(db: Session, consulta: ConsultaFicha, planta_id: int | None, dominios: tuple[str, ...],
                    user: Usuario, modulos: frozenset[str], *, completo: bool = False) -> dict:
    termo = consulta.identificador.lower()
    consulta_ativo = db.query(Ativo).outerjoin(AtivoTI).outerjoin(AtivoImpressora).filter(
        Ativo.deleted_at.is_(None), Ativo.dominio.in_(dominios),
        or_(*(func.lower(campo) == termo for campo in
              (Ativo.patrimonio, Ativo.numero_serie, AtivoTI.hostname, AtivoImpressora.hostname))),
    )
    consulta_ativo = aplicar_filtro(consulta_ativo, Ativo, planta_id)
    if consulta.planta:
        consulta_ativo = consulta_ativo.filter(Ativo.planta_id.in_(_plantas_permitidas(db, consulta.planta, planta_id)))
    ativos = _linhas(consulta_ativo.options(selectinload(Ativo.ti), selectinload(Ativo.impressora)).order_by(Ativo.id), 6, completo)
    if not ativos:
        return informacoes("Não encontrei esse patrimônio, hostname ou número de série no escopo atual.", modulos={"ativos"})

    links = [link_nexus("ativos", rotulo=f"Abrir {a.patrimonio or a.hostname or a.numero_serie}",
                        consulta=f"?busca={quote(a.numero_serie, safe='')}&destaque={a.id}", dominio=a.dominio.value)
             for a in ativos[:5]]
    if len(ativos) > 1:
        blocos = [_bloco("Equipamentos encontrados", *[(a.numero_serie, a.planta.nome if a.planta else None)
                                                       for a in (ativos if completo else ativos[:5])])]
        return informacoes("Há mais de um equipamento com esse identificador. Informe o número de série ou a planta.",
                           blocos=blocos, links=links, modulos={"ativos"})

    ativo = ativos[0]
    identificacao = ativo.patrimonio or ativo.hostname or ativo.numero_serie
    assunto = consulta.assunto
    blocos = []
    requeridos = {"ativos"}
    resumo = f"Ficha do ativo {identificacao}."
    detalhes = _inventario(ativo.ti) if assunto in {"completa", "hardware", "rede"} else {}
    if assunto in {"completa", "cadastro", "aquisicao"}:
        departamento = ativo.departamento
        local = ativo.localizacao
        blocos.append(_bloco("Cadastro",
            ("Patrimônio", ativo.patrimonio), ("Número de série", ativo.numero_serie), ("Hostname", ativo.hostname),
            ("Marca", ativo.marca), ("Modelo", ativo.modelo), ("Status", ativo.status),
            ("Planta", ativo.planta.nome if ativo.planta else None),
            ("Departamento", departamento.nome if departamento and departamento.planta_id in (None, ativo.planta_id) else None),
            ("Localização", local.nome if local and local.planta_id in (None, ativo.planta_id) else None),
            ("Aquisição", ativo.data_aquisicao), ("Garantia", ativo.data_garantia), ("Forma de aquisição", ativo.forma_aquisicao)))
    if assunto == "aquisicao" and "financeiro" in modulos:
        requeridos.add("financeiro")
        blocos.append(_bloco("Financeiro", ("Valor de aquisição (R$)", ativo.valor)))
    if assunto == "uso":
        blocos.append(_bloco("Uso do equipamento", ("Último usuário visto pelo agente", ativo.ultimo_usuario),
                             ("Visto em", ativo.ultimo_usuario_em)))
    if assunto == "rede" or (assunto == "completa" and (ativo.ti or ativo.impressora)):
        ficha = ativo.ti or ativo.impressora
        blocos.append(_bloco("Rede", ("Hostname", ativo.hostname), ("IP", ficha.ip if ficha else None),
                             ("Endereço MAC", ativo.ti.mac_address if ativo.ti else None),
                             ("Domínio de rede", ativo.ti.dominio_ad if ativo.ti else None)))
        interfaces = _inventario_lista(detalhes, "rede", completo)
        if interfaces:
            blocos.append(_bloco("Interfaces de rede", *[
                (_juntar(r.get("adaptador")) or "Adaptador",
                 _juntar(r.get("mac"), *r["ips"]) if isinstance(r.get("ips"), list) else _juntar(r.get("mac")))
                for r in interfaces
            ]))
    if assunto in {"completa", "hardware"} and ativo.dominio == Dominio.TI:
        blocos.extend(_hardware(ativo.ti, detalhes, completo))
    if ativo.dominio == Dominio.IMPRESSORA:
        impressao = _impressao(db, ativo, assunto, completo)
        blocos.extend(impressao)
        if assunto == "contador":
            dados = dict(impressao[0]["linhas"])
            ultima, cadastro = dados["Última leitura de páginas"], dados["Contador cadastrado"]
            if isinstance(ultima, int):
                resumo = f"A última leitura de {identificacao} registrou {ultima} páginas."
            elif isinstance(cadastro, int):
                resumo = f"O contador cadastrado de {identificacao} indica {cadastro} páginas. Sem leituras registradas."
            else:
                resumo = f"{identificacao} está sem contador de páginas cadastrado."
        if "monitor" in modulos:
            links.append(link_nexus("monitor"))
            if assunto == "comunicacao":
                requeridos.add("monitor")
                try:
                    monitor = _bloco_monitor(db, ativo, user, planta_id)
                    blocos.append(monitor)
                    resumo = f"{identificacao} · {dict(monitor['linhas'])['Comunicação']}."
                except HTTPException as exc:
                    return informacoes(str(exc.detail), links=links, modulos=requeridos)
    if assunto == "software" and "software" in modulos:
        requeridos.add("software")
        instalados = db.query(SoftwareInstalado).filter(
            SoftwareInstalado.ativo_id == ativo.id, SoftwareInstalado.deleted_at.is_(None),
        ).order_by(SoftwareInstalado.nome, SoftwareInstalado.id)
        itens = _linhas(instalados, 21, completo)
        blocos.append(_bloco("Software instalado", *[(item.nome, item.versao or "Sem versão registrada")
                                                     for item in (itens if completo else itens[:20])]
                              or [("Coleta", "Nenhum software registrado")]))
        if not completo and len(itens) > 20:
            blocos[-1]["linhas"].append(["Exibição", "Primeiros 20 itens. Exporte o CSV para consultar o restante."])
        links.append(link_nexus("software"))
    if assunto == "manutencao" and "manutencoes" in modulos:
        requeridos.add("manutencoes")
        ordens = db.query(Manutencao).filter(
            Manutencao.ativo_id == ativo.id, Manutencao.deleted_at.is_(None),
        ).order_by(Manutencao.data_abertura.desc(), Manutencao.id.desc())
        blocos.append(_bloco("Manutenções", *[
            (f"Ordem {item.id} · {_valor(item.status)}", item.descricao or "Sem descrição")
            for item in _linhas(ordens, 10, completo)
        ] or [("Ordens", "Nenhuma manutenção registrada")]))
        links.append(link_nexus("manutencoes"))
    if not blocos:
        return informacoes("Essa informação não está disponível para o equipamento ou para as permissões da sua conta.",
                           links=links, modulos=requeridos)
    return informacoes(resumo, blocos=blocos, links=links, modulos=requeridos)


def consultar_consumiveis(db: Session, consulta: ConsultaConsumiveis, planta_id: int | None,
                          dominios: tuple[str, ...], modulos: frozenset[str], *, completo: bool = False) -> dict:
    mostrar_saldo = consulta.operacao in {"estoque", "abaixo_minimo"}
    mostrar_movimentos = consulta.operacao == "movimentacoes"
    requeridos = {"produtos"}
    links = [link_nexus("produtos", consulta=f"?busca={quote(consulta.termo, safe='')}" if consulta.termo else "",
                        dominio=consulta.dominio)]
    planta_pedida = (consulta.planta or "").casefold()
    consolidada = planta_pedida in {"", "todas", "todas as plantas", "consolidado", "geral"}
    if (mostrar_saldo or mostrar_movimentos) and (planta_id is not None or not consolidada or "movimentacoes" not in modulos):
        texto = ("As movimentações de consumíveis estão disponíveis na visão de todas as plantas, com acesso a Transferências."
                 if mostrar_movimentos else
                 "O saldo por planta não está disponível. O saldo consolidado exige a visão de todas as plantas e acesso a Transferências.")
        return informacoes(texto,
                           links=links, modulos=requeridos)
    base = db.query(Produto).filter(Produto.deleted_at.is_(None), Produto.dominio.in_(dominios))
    if consulta.dominio:
        base = base.filter(Produto.dominio == consulta.dominio)
    if consulta.termo:
        termo = consulta.termo.lower()
        base = base.filter(or_(func.lower(Produto.sku).contains(termo, autoescape=True),
                               func.lower(Produto.nome).contains(termo, autoescape=True)))
    if consulta.operacao == "contar" and not completo:
        return informacoes(f"Consumíveis encontrados no catálogo: {base.count()}.", links=links, modulos=requeridos)
    if mostrar_movimentos:
        requeridos.add("movimentacoes")
        movimentos = db.query(Movimentacao, Produto.nome, Produto.sku).join(Produto, Produto.id == Movimentacao.produto_id).filter(
            Movimentacao.deleted_at.is_(None), Movimentacao.tipo.in_((TipoMov.ENTRADA, TipoMov.SAIDA)),
            Produto.id.in_(base.with_entities(Produto.id).statement),
        ).order_by(Movimentacao.data_mov.desc(), Movimentacao.id.desc())
        itens = _linhas(movimentos, 20, completo)
        blocos = [_bloco("Últimas entradas e saídas", *[
            (f"{sku} · {_valor(mov.tipo)}", f"{nome} · quantidade {mov.quantidade} · {_valor(mov.data_mov)}")
            for mov, nome, sku in itens
        ])] if itens else []
        return informacoes("Veja as movimentações mais recentes." if itens else "Nenhuma movimentação encontrada.",
                           blocos=blocos, links=links, modulos=requeridos)
    blocos = []
    if mostrar_saldo:
        requeridos.add("movimentacoes")
        totais = db.query(Movimentacao.produto_id,
                          func.sum(Movimentacao.quantidade).filter(Movimentacao.tipo == TipoMov.ENTRADA).label("entradas"),
                          func.sum(Movimentacao.quantidade).filter(Movimentacao.tipo == TipoMov.SAIDA).label("saidas")
                         ).filter(Movimentacao.deleted_at.is_(None), Movimentacao.produto_id.isnot(None)
                                  ).group_by(Movimentacao.produto_id).subquery()
        saldo = func.coalesce(totais.c.entradas, 0) - func.coalesce(totais.c.saidas, 0)
        consulta_saldo = base.outerjoin(totais, Produto.id == totais.c.produto_id).add_columns(saldo)
        if consulta.operacao == "abaixo_minimo":
            consulta_saldo = consulta_saldo.filter(saldo < Produto.estoque_minimo)
        itens = _linhas(consulta_saldo.order_by(Produto.nome, Produto.id), 21, completo)
        blocos = [_bloco(f"{p.nome} · {p.sku}", ("Saldo consolidado", f"{total} {p.unidade}"),
                         ("Estoque mínimo", p.estoque_minimo)) for p, total in (itens if completo else itens[:20])]
    else:
        itens = _linhas(base.order_by(Produto.nome, Produto.id), 21, completo)
        blocos = [_bloco(f"{p.nome} · {p.sku}", ("Descrição", p.descricao), ("Unidade", p.unidade),
                         ("Estoque mínimo", p.estoque_minimo), ("Preço unitário (R$)", p.preco_unitario))
                  for p in (itens if completo else itens[:20])]
    resumo = ("Veja os consumíveis encontrados." if blocos else "Nenhum consumível encontrado com esses filtros.")
    if consulta.operacao == "contar":
        resumo = f"Consumíveis encontrados no catálogo: {len(itens)}."
    elif not completo and len(itens) > 20:
        resumo = "Mostrando os primeiros 20 consumíveis. Exporte o CSV para consultar os demais."
    if len(itens) == 1:
        produto = itens[0][0] if mostrar_saldo else itens[0]
        links = [link_nexus("produtos", consulta=f"?busca={quote(produto.sku, safe='')}", dominio=produto.dominio.value)]
        if mostrar_saldo:
            resumo = f"O saldo consolidado de {produto.sku} é de {itens[0][1]} {produto.unidade}."
    return informacoes(resumo, blocos=blocos, links=links, modulos=requeridos)


_MODULO_INDICADOR = {
    "manutencoes_abertas": "manutencoes", "emprestimos_atrasados": "emprestimos", "contratos_a_vencer": "contratos",
    "contagens": "contagens", "garantias_a_vencer": "financeiro", "parque_financeiro": "financeiro",
}


def consultar_indicador(db: Session, consulta: ConsultaIndicadores, planta_id: int | None,
                        dominios: tuple[str, ...], modulos: frozenset[str], *, completo: bool = False) -> dict:
    indicador = consulta.indicador
    modulo = _MODULO_INDICADOR[indicador]
    if modulo not in modulos:
        return informacoes(f"Sua conta não tem acesso ao módulo {link_nexus(modulo)['rotulo']}.")
    links = [link_nexus(modulo)]
    plantas = {planta_id} if planta_id is not None else None
    if consulta.planta:
        plantas = set(_plantas_permitidas(db, consulta.planta, planta_id))
        if not plantas:
            return informacoes("A planta pedida não foi encontrada no escopo atual.", links=links, modulos={modulo})

    def escopo(base, entidade, *, corporativo=False):
        if plantas is None:
            return base
        filtro = entidade.planta_id.in_(plantas)
        return base.filter(or_(filtro, entidade.planta_id.is_(None)) if corporativo else filtro)

    dominios = tuple(d for d in dominios if consulta.dominio is None or d == consulta.dominio)
    hoje = datetime.now(ZoneInfo(FUSO_INVENTARIO)).date()
    ate = hoje + timedelta(days=consulta.dias)
    blocos = []
    if indicador == "manutencoes_abertas":
        base = db.query(Manutencao).join(Ativo, Ativo.id == Manutencao.ativo_id).filter(
            Manutencao.deleted_at.is_(None), Ativo.deleted_at.is_(None), Ativo.dominio.in_(dominios),
            Manutencao.status.in_((StatusManut.ABERTA, StatusManut.EM_ANDAMENTO)),
        )
        base = escopo(base, Ativo)
        total = base.count()
        texto = f"Ordens de manutenção abertas ou em andamento: {total}."
        linhas = _linhas(base.with_entities(Manutencao.id, Manutencao.status, Ativo.patrimonio, Ativo.numero_serie)
                         .order_by(Manutencao.id), 20, completo)
        if linhas:
            blocos = [_bloco("Ordens de manutenção", *[(f"Ordem {id_} · {patrimonio or serie}", status)
                                                       for id_, status, patrimonio, serie in linhas])]
    elif indicador == "emprestimos_atrasados":
        base = db.query(Emprestimo).join(Ativo, Ativo.id == Emprestimo.ativo_id).filter(
            Emprestimo.deleted_at.is_(None), Ativo.deleted_at.is_(None), Ativo.dominio.in_(dominios),
            Emprestimo.situacao == SituacaoEmprestimo.RETIRADO,
            Emprestimo.devolucao_prevista < datetime.now(timezone.utc),
        )
        base = escopo(base, Emprestimo)
        total = base.count()
        texto = f"Empréstimos com devolução atrasada: {total}."
        linhas = _linhas(base.with_entities(Emprestimo.id, Emprestimo.devolucao_prevista, Ativo.patrimonio, Ativo.numero_serie)
                         .order_by(Emprestimo.devolucao_prevista, Emprestimo.id), 20, completo)
        if linhas:
            blocos = [_bloco("Empréstimos atrasados", *[(f"Empréstimo {id_} · {patrimonio or serie}", data)
                                                       for id_, data, patrimonio, serie in linhas])]
    elif indicador == "contratos_a_vencer":
        base = db.query(Contrato).filter(Contrato.deleted_at.is_(None), Contrato.fim.between(hoje, ate))
        base = escopo(base, Contrato, corporativo=True)
        total = base.count()
        linhas = _linhas(base.order_by(Contrato.fim, Contrato.id), 20, completo)
        blocos = [_bloco("Contratos a vencer", *[(item.numero, item.fim) for item in linhas])] if linhas else []
        texto = f"Contratos a vencer nos próximos {consulta.dias} dias: {total}."
    elif indicador == "contagens":
        base = db.query(Contagem.status, func.count(Contagem.id)).filter(
            Contagem.deleted_at.is_(None), or_(Contagem.dominio.is_(None), Contagem.dominio.in_(dominios)),
        )
        grupos = escopo(base, Contagem).group_by(Contagem.status).order_by(Contagem.status).all()
        blocos = [_bloco("Contagens por situação", *[(_valor(status), total) for status, total in grupos])] if grupos else []
        texto = f"Sessões de contagem encontradas: {sum(total for _, total in grupos)}."
    else:
        base = escopo(db.query(Ativo).filter(Ativo.deleted_at.is_(None), Ativo.dominio.in_(dominios)), Ativo)
        if indicador == "garantias_a_vencer":
            base = base.filter(Ativo.data_garantia.between(hoje, ate))
            total = base.count()
            texto = f"Garantias a vencer nos próximos {consulta.dias} dias: {total}."
            linhas = _linhas(base.with_entities(Ativo.patrimonio, Ativo.numero_serie, Ativo.data_garantia)
                             .order_by(Ativo.data_garantia, Ativo.id), 20, completo)
            if linhas:
                blocos = [_bloco("Garantias a vencer", *[(patrimonio or serie, data) for patrimonio, serie, data in linhas])]
        else:
            from app.routers.financeiro import _montar
            from app.services.financeiro import resumo_do_parque

            dados = resumo_do_parque(_montar(db, base.all()))
            compra, locacao = dados["comprado"], dados["locado"]
            blocos = [
                _bloco("Comprados", ("Quantidade", compra["ativos"]), ("Aquisição (R$)", compra["valor_aquisicao"]),
                       ("Valor atual (R$)", compra["valor_atual"]), ("Depreciação (R$)", compra["valor_depreciado"]),
                       ("Manutenção (R$)", compra["custo_manutencao"])),
                _bloco("Locados", ("Quantidade", locacao["ativos"]), ("Mensalidade (R$)", locacao["custo_mensal"]),
                       ("Acumulado (R$)", locacao["custo_acumulado"]), ("Manutenção (R$)", locacao["custo_manutencao"])),
            ]
            texto = "Resumo financeiro dos ativos no escopo consultado."
    return informacoes(texto, blocos=blocos, links=links, modulos={modulo})
