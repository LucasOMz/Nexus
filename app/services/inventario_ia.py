"""Consultas de inventário aceitas pelo chat, executadas pelo Nexus."""
from __future__ import annotations

import re
from math import isfinite
from datetime import date, datetime, time, timezone
from typing import Literal
from unicodedata import combining, normalize
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import String, and_, case, cast, func, or_, select, true
from sqlalchemy.orm import Session

from app.core.planta import aplicar_filtro
from app.models.core import Ativo, Categoria, Departamento, Localizacao, Planta, PlantaLocalidade
from app.models.enums import Dominio
from app.models.impressora import AtivoImpressora
from app.models.software import Software, SoftwareInstalado
from app.models.ti import AtivoTI

Campo = Literal[
    "planta", "departamento", "localizacao", "categoria", "tipo_equipamento", "dominio", "status",
    "patrimonio", "numero_serie", "hostname", "marca", "modelo", "inventario_em", "data_aquisicao", "data_garantia",
    "ram_gb", "armazenamento_gb", "so", "cpu",
]
Grupo = Literal["planta", "departamento", "localizacao", "categoria", "tipo_equipamento", "dominio", "status", "marca", "modelo"]
Atributo = Literal["ram_gb", "armazenamento_gb", "cpu", "so"]
ATRIBUTOS_TI = {
    "ram_gb": (AtivoTI.ram_gb, "Memória RAM", " GB"),
    "armazenamento_gb": (AtivoTI.armazenamento_gb, "Armazenamento", " GB"),
    "cpu": (AtivoTI.cpu, "Processador", ""),
    "so": (AtivoTI.so, "Sistema operacional", ""),
}
DATAS = {"inventario_em", "data_aquisicao", "data_garantia"}
OPERADORES_DATA = {"desde", "antes_de"}
NUMERICOS = {"ram_gb", "armazenamento_gb"}
FUSO_INVENTARIO = "America/Sao_Paulo"
_PREFIXO_CADASTRO = re.compile(r"^(?:(?:departamento|setor|planta|unidade)\s+)?(?:d(?:e|a|o|as|os)\s+)?")


class Filtro(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    campo: Campo
    operador: Literal["igual", "contém", "começa_com", "vazio", "preenchido", "desde", "antes_de", "no_minimo", "no_maximo"]
    valor: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validar_valor(self) -> Filtro:
        if self.operador in {"vazio", "preenchido"}:
            return self
        if not self.valor:
            raise ValueError("Informe um valor para o filtro.")
        if (self.operador in OPERADORES_DATA) != (self.campo in DATAS):
            raise ValueError("Para datas, use desde, antes_de, vazio ou preenchido.")
        if self.campo in DATAS:
            date.fromisoformat(self.valor)
        if self.campo in NUMERICOS:
            if self.operador not in {"igual", "no_minimo", "no_maximo"} or not isfinite(float(self.valor)) or float(self.valor) < 0:
                raise ValueError("Informe uma quantidade em GB com igual, no_minimo ou no_maximo.")
        elif self.operador in {"no_minimo", "no_maximo"}:
            raise ValueError("Limites numéricos se aplicam a RAM ou armazenamento.")
        return self


class FiltroSoftware(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    nome: str = Field(min_length=2, max_length=180)
    comparacao_nome: Literal["igual", "contém"] = "contém"
    versao: str | None = Field(default=None, min_length=1, max_length=80)
    comparacao_versao: Literal["igual", "prefixo"] = "igual"
    situacao: Literal["instalado", "ausente"] = "instalado"


class ConsultaInventario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operacao: Literal["contar", "listar", "percentual"]
    filtros: list[Filtro] = Field(default_factory=list, max_length=10)
    filtros_numerador: list[Filtro] = Field(default_factory=list, max_length=10)
    softwares: list[FiltroSoftware] = Field(default_factory=list, max_length=4)
    softwares_numerador: list[FiltroSoftware] = Field(default_factory=list, max_length=4)
    agrupar_por: list[Grupo] = Field(default_factory=list, max_length=2)
    atributos: list[Atributo] = Field(default_factory=list, max_length=4)
    ordem: Literal["maior", "menor"] = "maior"
    limite: int = Field(default=15, ge=1, le=30)

    @model_validator(mode="after")
    def validar_operacao(self) -> ConsultaInventario:
        if len(set(self.agrupar_por)) != len(self.agrupar_por) or (self.operacao == "listar" and self.agrupar_por):
            raise ValueError("Use agrupamentos distintos apenas em contagens ou percentuais.")
        if bool(self.filtros_numerador or self.softwares_numerador) != (self.operacao == "percentual"):
            raise ValueError("Informe os critérios do numerador apenas ao calcular um percentual.")
        if self.atributos and (self.operacao != "listar" or len(self.atributos) != len(set(self.atributos))):
            raise ValueError("Use atributos distintos apenas em listagens.")
        return self


def _lookup_no_escopo(modelo, chave):
    return and_(modelo.id == chave, modelo.deleted_at.is_(None),
                or_(modelo.planta_id.is_(None), modelo.planta_id == Ativo.planta_id))


def _normalizar_texto(valor: str | None) -> str:
    decomposto = normalize("NFD", (valor or "").casefold())
    return " ".join("".join(c for c in decomposto if not combining(c)).split())


def resolver_cadastro(cadastros, filtro: Filtro) -> dict[int, str]:
    termo = _normalizar_texto(filtro.valor)
    if not termo:
        return {}
    nomes = [(id_, nome, tuple(filter(None, map(_normalizar_texto, (nome, *aliases)))))
             for id_, nome, *aliases in cadastros]
    if filtro.operador == "igual":
        limpo = _PREFIXO_CADASTRO.sub("", termo)
        for candidato in dict.fromkeys(filter(None, (termo, limpo))):
            exatos = {id_: nome for id_, nome, aliases in nomes if candidato in aliases}
            if exatos:
                return exatos
        # Um nome curto pode se referir ao cadastro “Unidade Tatuí” ou “Engenharia Industrial”.
        if not limpo:
            return {}
        return {id_: nome for id_, nome, aliases in nomes
                if aliases and re.search(rf"(?<!\w){re.escape(limpo)}(?!\w)", aliases[0])}
    if filtro.operador == "começa_com":
        return {id_: nome for id_, nome, aliases in nomes if any(s.startswith(termo) for s in aliases)}
    return {id_: nome for id_, nome, aliases in nomes if any(termo in s for s in aliases)}


def _condicao_software(filtro: FiltroSoftware):
    nome = filtro.nome.lower()
    informado = func.lower(func.trim(SoftwareInstalado.nome))
    catalogado = func.lower(func.trim(Software.nome))
    if filtro.comparacao_nome == "igual":
        condicao_nome = or_(informado == nome, catalogado == nome)
    else:
        condicao_nome = or_(informado.contains(nome, autoescape=True), catalogado.contains(nome, autoescape=True))
    condicao = and_(SoftwareInstalado.deleted_at.is_(None), condicao_nome)
    if filtro.versao is None:
        return condicao
    versao = func.lower(func.trim(SoftwareInstalado.versao))
    pedida = filtro.versao.lower()
    comparacao = versao == pedida
    if filtro.comparacao_versao == "prefixo":
        comparacao = or_(comparacao, versao.startswith(pedida + ".", autoescape=True))
    return and_(condicao, comparacao)


def _consulta_software(consulta):
    return consulta.outerjoin(Software, _lookup_no_escopo(Software, SoftwareInstalado.software_id))


def _instalacoes_do_ativo(filtro: FiltroSoftware):
    return _consulta_software(select(SoftwareInstalado.id).select_from(SoftwareInstalado)).where(
        SoftwareInstalado.ativo_id == Ativo.id, _condicao_software(filtro),
    ).correlate(Ativo)


def _existe_software(filtro: FiltroSoftware):
    instalacoes = _instalacoes_do_ativo(filtro).exists()
    if filtro.situacao == "instalado":
        return instalacoes
    # Sem qualquer software coletado, não há evidência suficiente para afirmar ausência.
    inventariado = select(SoftwareInstalado.id).where(
        SoftwareInstalado.ativo_id == Ativo.id, SoftwareInstalado.deleted_at.is_(None),
    ).correlate(Ativo).exists()
    if filtro.versao is None:
        return and_(inventariado, ~instalacoes)
    sem_versao = _instalacoes_do_ativo(filtro.model_copy(update={"versao": None})).where(
        or_(SoftwareInstalado.versao.is_(None), func.trim(SoftwareInstalado.versao) == ""),
    ).exists()
    return and_(inventariado, ~instalacoes, ~sem_versao)


def detalhar_consulta(consulta: ConsultaInventario) -> ConsultaInventario:
    filtros = consulta.filtros + consulta.filtros_numerador
    atributos = list(dict.fromkeys([*consulta.atributos, *(f.campo for f in filtros if f.campo in ATRIBUTOS_TI)]))
    return consulta.model_copy(update={
        "operacao": "listar", "agrupar_por": [], "filtros": filtros, "atributos": atributos,
        "softwares": consulta.softwares + consulta.softwares_numerador, "filtros_numerador": [], "softwares_numerador": [],
    })


def executar_consulta(db: Session, consulta: ConsultaInventario, planta_id: int | None, dominios: tuple[str, ...],
                      *, inicio: int = 0, tamanho: int | None = None, completo: bool = False) -> dict:
    resultado: dict = {"operacao": consulta.operacao, "agrupar_por": consulta.agrupar_por}
    filtros_nomeados = [f for f in consulta.filtros + consulta.filtros_numerador
                        if f.campo in {"planta", "departamento"} and f.operador not in {"vazio", "preenchido"}]
    filtros_planta = [f for f in filtros_nomeados if f.campo == "planta"]
    filtros_departamento = [f for f in filtros_nomeados if f.campo == "departamento"]
    cadastros = {}
    plantas_consultadas = None if planta_id is None else {planta_id}
    if filtros_planta:
        catalogo = db.query(Planta.id, Planta.nome, Planta.sigla, Planta.cidade, PlantaLocalidade.codigo).outerjoin(
            PlantaLocalidade, PlantaLocalidade.planta_id == Planta.id
        ).filter(Planta.deleted_at.is_(None))
        if planta_id is not None:
            catalogo = catalogo.filter(Planta.id == planta_id)
        plantas = catalogo.all()
        for filtro in filtros_planta:
            ids = resolver_cadastro(plantas, filtro)
            if not ids:
                aviso = (f'A planta “{filtro.valor}” não corresponde ao escopo atual. Confira a planta selecionada no topo.'
                         if planta_id is not None else
                         f'Não encontrei a planta “{filtro.valor}”. Confira o nome, a cidade ou a sigla.')
                return {**resultado, "aviso": aviso}
            cadastros[(filtro.campo, filtro.operador, filtro.valor)] = ids
            if filtro in consulta.filtros:
                plantas_consultadas = plantas_consultadas & ids.keys() if plantas_consultadas is not None else set(ids)
    if filtros_departamento:
        catalogo = db.query(Departamento.id, Departamento.nome, Departamento.sigla).filter(Departamento.deleted_at.is_(None))
        if plantas_consultadas is not None:
            catalogo = catalogo.filter(or_(Departamento.planta_id.is_(None), Departamento.planta_id.in_(plantas_consultadas)))
        departamentos = catalogo.all()
        for filtro in filtros_departamento:
            ids = resolver_cadastro(departamentos, filtro)
            if not ids:
                return {**resultado, "aviso": f'Não encontrei o departamento “{filtro.valor}” nas plantas consultadas. Confira o nome ou a sigla.'}
            cadastros[(filtro.campo, filtro.operador, filtro.valor)] = ids

    if cadastros:
        resultado["cadastros_consultados"] = {campo: sorted({
            nome for (tipo, _, _), ids in cadastros.items() if tipo == campo for nome in ids.values()
        }) for campo in ("planta", "departamento")}

    hostname = func.coalesce(func.nullif(func.trim(AtivoTI.hostname), ""), AtivoImpressora.hostname)
    cat = func.lower(Categoria.nome)
    so = func.lower(func.trim(AtivoTI.so))
    classe = case(
        (Ativo.dominio == Dominio.IMPRESSORA, "impressora"),
        (or_(func.upper(hostname).regexp_match(r"^N[A-Z]{3}[0-9]{4}([.]|$)"), cat.contains("notebook"), cat.contains("laptop")), "notebook"),
        (or_(func.upper(hostname).regexp_match(r"^D[A-Z]{3}[0-9]{4}([.]|$)"), cat.contains("desktop")), "desktop"),
        (or_(func.upper(hostname).regexp_match(r"^R[A-Z]{3}[0-9]{4}([.]|$)"), cat.contains("raspberry")), "raspberry"),
        (or_(cat.contains("computador"), cat.in_(("pc", "pcs"))), "computador"),
        (and_(Ativo.dominio == Dominio.TI,
              or_(so.startswith("windows"), so.startswith("linux"), so.startswith("macos"),
                  so.startswith("ubuntu"), so.startswith("debian"), so.startswith("raspbian"))), "computador"),
        else_="outro",
    )
    campos = {
        "planta": Planta.nome, "departamento": Departamento.nome, "localizacao": Localizacao.nome,
        "categoria": Categoria.nome, "tipo_equipamento": classe, "dominio": cast(Ativo.dominio, String),
        "status": cast(Ativo.status, String), "patrimonio": Ativo.patrimonio, "numero_serie": Ativo.numero_serie,
        "hostname": hostname, "marca": Ativo.marca, "modelo": Ativo.modelo, "inventario_em": AtivoTI.inventario_em,
        "data_aquisicao": Ativo.data_aquisicao, "data_garantia": Ativo.data_garantia,
        **{campo: config[0] for campo, config in ATRIBUTOS_TI.items()},
    }

    def expressao(filtro: Filtro):
        coluna = campos[filtro.campo]
        operador, valor = filtro.operador, filtro.valor
        if operador in {"vazio", "preenchido"}:
            vazio = coluna.is_(None) if filtro.campo in DATAS | NUMERICOS else or_(coluna.is_(None), func.trim(coluna) == "")
            return vazio if operador == "vazio" else ~vazio
        if filtro.campo in NUMERICOS:
            n = float(valor)
            if operador == "no_minimo":
                return coluna >= n
            if operador == "no_maximo":
                return coluna <= n
            return coluna == n
        if filtro.campo in DATAS:
            dia = date.fromisoformat(valor)
            limite = dia
            if filtro.campo == "inventario_em":
                limite = datetime.combine(dia, time.min, ZoneInfo(FUSO_INVENTARIO)).astimezone(timezone.utc)
            return coluna >= limite if operador == "desde" else coluna < limite
        if filtro.campo == "tipo_equipamento" and operador == "igual":
            tipo = _normalizar_texto(valor)
            if tipo in {"computador", "computadores", "pc", "pcs"}:
                return coluna.in_(("computador", "desktop", "notebook", "raspberry"))
            if tipo in {"ativo", "ativos", "equipamento", "equipamentos", "todos", "todos os ativos"}:
                return true()
        if filtro.campo in {"planta", "departamento"}:
            chave = Planta.id if filtro.campo == "planta" else Departamento.id
            return chave.in_(cadastros[(filtro.campo, operador, valor)].keys())
        if operador == "igual":
            return func.lower(coluna) == valor.lower()
        if operador == "começa_com":
            return func.lower(coluna).startswith(valor.lower(), autoescape=True)
        return func.lower(coluna).contains(valor.lower(), autoescape=True)

    base = (
        db.query(Ativo.id).select_from(Ativo)
        .outerjoin(Planta, and_(Planta.id == Ativo.planta_id, Planta.deleted_at.is_(None)))
        .outerjoin(Departamento, _lookup_no_escopo(Departamento, Ativo.departamento_id))
        .outerjoin(Categoria, _lookup_no_escopo(Categoria, Ativo.categoria_id))
        .outerjoin(Localizacao, _lookup_no_escopo(Localizacao, Ativo.localizacao_id))
        .outerjoin(AtivoTI, AtivoTI.ativo_id == Ativo.id)
        .outerjoin(AtivoImpressora, AtivoImpressora.ativo_id == Ativo.id)
        .filter(Ativo.deleted_at.is_(None), Ativo.dominio.in_(dominios))
        .filter(*(expressao(filtro) for filtro in consulta.filtros))
        .filter(*(_existe_software(filtro) for filtro in consulta.softwares))
    )
    base = aplicar_filtro(base, Ativo, planta_id)
    total = func.count(Ativo.id)
    if consulta.operacao == "listar":
        colunas = ("patrimonio", "hostname", "modelo", "planta", "departamento", "status",
                   "numero_serie", "marca", "categoria", "localizacao", "tipo_equipamento", "dominio")
        selecao = [campos[c].label(c) for c in colunas]
        selecao.extend(ATRIBUTOS_TI[c][0].label(c) for c in consulta.atributos)
        pagina = base.order_by(Ativo.id).offset(inicio)
        if not completo:
            pagina = pagina.limit(tamanho or consulta.limite)
        linhas = [dict(linha._mapping) for linha in pagina.with_entities(Ativo.id, *selecao)]
        instalados = [f for f in consulta.softwares if f.situacao == "instalado"]
        if linhas and instalados:
            evidencias = _consulta_software(db.query(
                SoftwareInstalado.ativo_id, SoftwareInstalado.nome, SoftwareInstalado.versao,
            ).join(Ativo, Ativo.id == SoftwareInstalado.ativo_id)).filter(
                SoftwareInstalado.ativo_id.in_(pagina.with_entities(Ativo.id).statement.correlate(None)),
                or_(*(_condicao_software(f) for f in instalados)),
            ).distinct().order_by(SoftwareInstalado.ativo_id, SoftwareInstalado.nome, SoftwareInstalado.versao)
            por_ativo = {}
            for id_, nome, versao in evidencias:
                por_ativo.setdefault(id_, []).append({"nome": nome, "versao": versao})
            for linha in linhas:
                linha["softwares"] = por_ativo.get(linha["id"], [])
        if consulta.atributos:
            resultado["atributos"] = consulta.atributos
        quantidade = base.with_entities(total).scalar()
        proximo = inicio + len(linhas)
        return {**resultado, "total": quantidade, "equipamentos": linhas,
                "inicio": inicio, "proximo": proximo if linhas and proximo < quantidade else None}

    condicoes = [expressao(f) for f in consulta.filtros_numerador]
    condicoes.extend(_existe_software(f) for f in consulta.softwares_numerador)
    numerador = func.count(case((and_(*condicoes), 1))) if condicoes else None
    medidas = (total, numerador) if numerador is not None else (total,)

    def metricas(valores) -> dict:
        n = valores[0]
        if numerador is None:
            return {"total": n}
        return {"total": n, "correspondentes": valores[1], "percentual": round(100 * valores[1] / n, 2) if n else None}

    resultado.update(metricas(base.with_entities(*medidas).one()))
    if consulta.agrupar_por:
        grupos = [campos[c] for c in consulta.agrupar_por]
        ranking = numerador * 1.0 / total if numerador is not None else total
        agrupada = base.with_entities(*grupos, *medidas).group_by(*grupos)
        ordenada = agrupada.order_by(ranking.asc() if consulta.ordem == "menor" else ranking.desc(), *grupos)
        linhas = ordenada.all() if completo else ordenada.limit(consulta.limite + 1).all()
        k = len(grupos)
        resultado["grupos"] = [{"valores": list(linha[:k]), **metricas(linha[k:])}
                               for linha in (linhas if completo else linhas[:consulta.limite])]
        resultado["truncado"] = not completo and len(linhas) > consulta.limite
    return resultado


def resposta_ficha(dados: dict) -> str:
    if not dados["equipamentos"]:
        return "Nenhum equipamento encontrado com esses filtros no escopo atual."
    if dados["total"] > 1 or len(dados["equipamentos"]) > 1:
        return f"Encontrei {dados['total']} equipamentos. Veja as informações disponíveis na lista."
    ativo = dados["equipamentos"][0]
    identificacao = ativo["patrimonio"] or ativo["hostname"] or f"#{ativo['id']}"
    if dados["atributos"] == ["ram_gb"] and ativo["ram_gb"] is not None:
        return f"O ativo {identificacao} tem {ativo['ram_gb']} GB de RAM cadastrados."
    ficha = []
    for campo in dados["atributos"]:
        _, rotulo, unidade = ATRIBUTOS_TI[campo]
        valor = ativo[campo]
        ficha.append(f"{rotulo} · {valor}{unidade}" if valor is not None and valor != "" else f"{rotulo} · sem informação cadastrada")
    return f"Ativo {identificacao}. " + ". ".join(ficha) + "."
