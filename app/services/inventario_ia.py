"""Consultas de inventário aceitas pelo chat, executadas pelo Nexus."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, case, cast, func, or_, String
from sqlalchemy.orm import Session

from app.core.planta import aplicar_filtro
from app.models.core import Ativo, Categoria, Departamento, Localizacao, Planta
from app.models.enums import Dominio, TipoItem
from app.models.impressora import AtivoImpressora
from app.models.ti import AtivoTI

Campo = Literal[
    "planta", "departamento", "localizacao", "categoria", "tipo_equipamento", "dominio", "status",
    "patrimonio", "numero_serie", "hostname", "marca", "modelo", "inventario_em", "data_aquisicao", "data_garantia",
]
Grupo = Literal["planta", "departamento", "localizacao", "categoria", "tipo_equipamento", "dominio", "status", "marca", "modelo"]
DATAS = {"inventario_em", "data_aquisicao", "data_garantia"}
OPERADORES_DATA = {"desde", "antes_de"}
FUSO_INVENTARIO = "America/Sao_Paulo"


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
    ordem: Literal["maior", "menor"] = "maior"
    limite: int = Field(default=15, ge=1, le=30)

    @model_validator(mode="after")
    def validar_operacao(self) -> ConsultaInventario:
        if len(set(self.agrupar_por)) != len(self.agrupar_por) or (self.operacao == "listar" and self.agrupar_por):
            raise ValueError("Use agrupamentos distintos apenas em contagens ou percentuais.")
        if bool(self.filtros_numerador) != (self.operacao == "percentual"):
            raise ValueError("Informe filtros_numerador apenas ao calcular um percentual.")
        return self


def _lookup_no_escopo(modelo, chave):
    return and_(modelo.id == chave, modelo.deleted_at.is_(None),
                or_(modelo.planta_id.is_(None), modelo.planta_id == Ativo.planta_id))


def executar_consulta(db: Session, consulta: ConsultaInventario, planta_id: int | None, dominios: tuple[str, ...]) -> dict:
    hostname = func.coalesce(func.nullif(func.trim(AtivoTI.hostname), ""), AtivoImpressora.hostname)
    cat = func.lower(Categoria.nome)
    classe = case(
        (Ativo.dominio == Dominio.IMPRESSORA, "impressora"),
        (or_(func.upper(hostname).regexp_match(r"^N[A-Z]{3}[0-9]{4}([.]|$)"), cat.contains("notebook"), cat.contains("laptop")), "notebook"),
        (or_(func.upper(hostname).regexp_match(r"^D[A-Z]{3}[0-9]{4}([.]|$)"), cat.contains("desktop")), "desktop"),
        (or_(func.upper(hostname).regexp_match(r"^R[A-Z]{3}[0-9]{4}([.]|$)"), cat.contains("raspberry")), "raspberry"),
        (or_(cat.contains("computador"), cat.in_(("pc", "pcs"))), "computador"),
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
        if filtro.campo == "tipo_equipamento" and operador == "igual" and valor.lower() == "computador":
            return coluna.in_(("computador", "desktop", "notebook", "raspberry"))
        if filtro.campo == "planta" and operador == "igual":
            return or_(func.lower(coluna) == valor.lower(), func.lower(Planta.sigla) == valor.lower())
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
        .filter(Ativo.deleted_at.is_(None), Ativo.tipo_item == TipoItem.ATIVO, Ativo.dominio.in_(dominios))
        .filter(*(expressao(filtro) for filtro in consulta.filtros))
    )
    base = aplicar_filtro(base, Ativo, planta_id)
    total = func.count(Ativo.id)
    resultado: dict = {"operacao": consulta.operacao, "agrupar_por": consulta.agrupar_por}
    if consulta.operacao == "listar":
        colunas = ("patrimonio", "hostname", "modelo", "planta", "departamento", "status")
        linhas = base.with_entities(Ativo.id, *(campos[c].label(c) for c in colunas)).order_by(Ativo.id).limit(consulta.limite).all()
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
