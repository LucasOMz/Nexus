"""Consultas de inventário aceitas pelo chat, executadas pelo Nexus."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from typing import Literal
from unicodedata import combining, normalize
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import String, and_, case, cast, func, or_, true
from sqlalchemy.orm import Session

from app.core.planta import aplicar_filtro
from app.models.core import Ativo, Categoria, Departamento, Localizacao, Planta, PlantaLocalidade
from app.models.enums import Dominio
from app.models.impressora import AtivoImpressora
from app.models.ti import AtivoTI

Campo = Literal[
    "planta", "departamento", "localizacao", "categoria", "tipo_equipamento", "dominio", "status",
    "patrimonio", "numero_serie", "hostname", "marca", "modelo", "inventario_em", "data_aquisicao", "data_garantia",
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
FUSO_INVENTARIO = "America/Sao_Paulo"
_PREFIXO_CADASTRO = re.compile(r"^(?:(?:departamento|setor|planta|unidade)\s+)?(?:d(?:e|a|o|as|os)\s+)?")


class Filtro(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    campo: Campo
    operador: Literal["igual", "contém", "começa_com", "vazio", "preenchido", "desde", "antes_de"]
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
        return self


class ConsultaInventario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operacao: Literal["contar", "listar", "percentual"]
    filtros: list[Filtro] = Field(default_factory=list, max_length=10)
    filtros_numerador: list[Filtro] = Field(default_factory=list, max_length=10)
    agrupar_por: list[Grupo] = Field(default_factory=list, max_length=2)
    atributos: list[Atributo] = Field(default_factory=list, max_length=4)
    ordem: Literal["maior", "menor"] = "maior"
    limite: int = Field(default=15, ge=1, le=30)

    @model_validator(mode="after")
    def validar_operacao(self) -> ConsultaInventario:
        if len(set(self.agrupar_por)) != len(self.agrupar_por) or (self.operacao == "listar" and self.agrupar_por):
            raise ValueError("Use agrupamentos distintos apenas em contagens ou percentuais.")
        if bool(self.filtros_numerador) != (self.operacao == "percentual"):
            raise ValueError("Informe filtros_numerador apenas ao calcular um percentual.")
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


def executar_consulta(db: Session, consulta: ConsultaInventario, planta_id: int | None, dominios: tuple[str, ...]) -> dict:
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
    }

    def expressao(filtro: Filtro):
        coluna = campos[filtro.campo]
        operador, valor = filtro.operador, filtro.valor
        if operador in {"vazio", "preenchido"}:
            vazio = coluna.is_(None) if filtro.campo in DATAS else or_(coluna.is_(None), func.trim(coluna) == "")
            return vazio if operador == "vazio" else ~vazio
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
    )
    base = aplicar_filtro(base, Ativo, planta_id)
    total = func.count(Ativo.id)
    if consulta.operacao == "listar":
        colunas = ("patrimonio", "hostname", "modelo", "planta", "departamento", "status")
        selecao = [campos[c].label(c) for c in colunas]
        selecao.extend(ATRIBUTOS_TI[c][0].label(c) for c in consulta.atributos)
        linhas = base.with_entities(Ativo.id, *selecao).order_by(Ativo.id).limit(consulta.limite).all()
        if consulta.atributos:
            resultado["atributos"] = consulta.atributos
        return {**resultado, "total": base.with_entities(total).scalar(), "equipamentos": [dict(linha._mapping) for linha in linhas]}

    numerador = func.count(case((and_(*(expressao(f) for f in consulta.filtros_numerador)), 1))) if consulta.filtros_numerador else None
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
        linhas = agrupada.order_by(ranking.asc() if consulta.ordem == "menor" else ranking.desc(), *grupos).limit(consulta.limite + 1).all()
        k = len(grupos)
        resultado["grupos"] = [{"valores": list(linha[:k]), **metricas(linha[k:])} for linha in linhas[:consulta.limite]]
        resultado["truncado"] = len(linhas) > consulta.limite
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
