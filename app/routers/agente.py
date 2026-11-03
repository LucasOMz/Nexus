"""Endpoints dos agentes.

Dois públicos distintos, e a separação importa:

* `/agente/registrar` e `/agente/inventario` — chamados **pelo agente**, sem
  sessão de usuário. Autenticam por código de instalação e depois por token
  da máquina.

* `/admin/agentes/*` — chamados pela **tela**, com sessão de administrador.

Misturar os dois no mesmo arquivo é aceitável; misturar as **credenciais**
não é. O token de agente nunca serve para a área administrativa, e o JWT
administrativo nunca serve para enviar inventário.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin
from app.database import get_db
from app.models.agente import CodigoInstalacao, EquipamentoPendente, TokenAgente
from app.models.core import Usuario
from app.services import agente_service as servico

router = APIRouter(tags=["agente"])


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------


class RegistroEntrada(BaseModel):
    codigo: str = Field(min_length=4, max_length=64)
    serial: str | None = Field(default=None, max_length=120)
    hostname: str | None = Field(default=None, max_length=120)
    # O payload inteiro é opaco para o servidor no registro: serve para
    # preencher a fila de pendências quando a máquina não é reconhecida.
    basico: dict | None = None
    detalhes: dict | None = None


class RegistroSaida(BaseModel):
    ok: bool
    token: str | None = None
    ativo_id: int | None = None
    intervalo_horas: int = 12


@router.post("/agente/registrar", response_model=RegistroSaida)
def registrar(entrada: RegistroEntrada, db: Session = Depends(get_db)) -> RegistroSaida:
    """Troca o código de instalação pelo token da máquina.

    **Sem autenticação de usuário** — é o agente chegando pela primeira vez.
    A credencial é o código.

    Falhas devolvem HTTP com o motivo legível, porque o instalador mostra
    isso ao técnico: "serial não cadastrado" é acionável, "erro 500" não é.
    """
    payload = {
        "serial": entrada.serial,
        "hostname": entrada.hostname,
        "basico": entrada.basico or {},
        "detalhes": entrada.detalhes or {},
    }
    r = servico.registrar(
        db,
        codigo=entrada.codigo,
        serial=entrada.serial,
        hostname=entrada.hostname,
        payload=payload,
    )
    if not r["ok"]:
        raise HTTPException(r["status"], r["motivo"])
    return RegistroSaida(
        ok=True, token=r["token"], ativo_id=r["ativo_id"], intervalo_horas=12
    )


@router.post("/agente/inventario")
def inventario(
    payload: dict,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Recebe o inventário. Autentica pelo token da máquina no header.

    Lido do header à mão, e não por `Depends(oauth2_scheme)`: o esquema
    OAuth2 é o do usuário, e reaproveitá-lo faria o token de agente aparecer
    na documentação como se fosse sessão de pessoa.
    """
    cabecalho = request.headers.get("Authorization") or ""
    if not cabecalho.lower().startswith("bearer "):
        raise HTTPException(401, "token_ausente")
    token = servico.buscar_token(db, cabecalho[7:].strip())
    if token is None:
        raise HTTPException(401, "token_invalido")

    token.ultimo_ip = request.client.host if request.client else None
    r = servico.aplicar_inventario(db, token, payload)
    if not r["ok"]:
        raise HTTPException(r["status"], r["motivo"])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Administração
# ---------------------------------------------------------------------------


class CodigoEntrada(BaseModel):
    rotulo: str | None = Field(default=None, max_length=120)
    dias: int = Field(default=7, ge=1, le=365)
    usos_max: int = Field(default=1, ge=1, le=100000)


class CodigoSaida(BaseModel):
    id: int
    # Visível de novo na lista — ver a explicação no modelo.
    codigo: str | None = None
    prefixo: str
    rotulo: str | None = None
    usos_max: int
    usos_feitos: int
    expira_em: datetime
    revogado: bool
    util: bool
    criado_em: datetime | None = None


def _serializar(c: CodigoInstalacao) -> CodigoSaida:
    return CodigoSaida(
        id=c.id,
        codigo=c.codigo_valor,
        prefixo=c.prefixo,
        rotulo=c.rotulo,
        usos_max=c.usos_max,
        usos_feitos=c.usos_feitos or 0,
        expira_em=c.expira_em,
        revogado=c.revogado_em is not None,
        util=c.util,
        criado_em=getattr(c, "created_at", None),
    )


@router.post("/admin/agentes/codigos")
def criar_codigo(
    entrada: CodigoEntrada,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> dict:
    """Gera um código de instalação.

    **O valor aparece uma única vez**, nesta resposta. Não há como consultá-lo
    depois — o banco guarda só o hash. Se perder, gere outro.
    """
    registro, valor = servico.gerar_codigo(
        db,
        dias=entrada.dias,
        usos_max=entrada.usos_max,
        rotulo=entrada.rotulo,
        criado_por_id=user.id,
    )
    return {"codigo": valor, "registro": _serializar(registro).model_dump()}


@router.get("/admin/agentes/codigos", response_model=list[CodigoSaida])
def listar_codigos(
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> list[CodigoSaida]:
    linhas = db.query(CodigoInstalacao).order_by(CodigoInstalacao.id.desc()).limit(50).all()
    return [_serializar(c) for c in linhas]


@router.delete("/admin/agentes/codigos/{codigo_id}")
def revogar_codigo(
    codigo_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> dict:
    registro = db.get(CodigoInstalacao, codigo_id)
    if registro is None:
        raise HTTPException(404, "Código não encontrado.")
    registro.revogado_em = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


class TokenSaida(BaseModel):
    id: int
    ativo_id: int
    patrimonio: str | None = None
    hostname: str | None = None
    serial: str | None = None
    ultimo_uso_em: datetime | None = None
    ultimo_ip: str | None = None
    revogado: bool = False


@router.get("/admin/agentes/tokens", response_model=list[TokenSaida])
def listar_tokens(
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> list[TokenSaida]:
    from app.models.core import Ativo

    linhas = (
        db.query(TokenAgente, Ativo)
        .join(Ativo, Ativo.id == TokenAgente.ativo_id)
        .order_by(TokenAgente.ultimo_uso_em.desc().nullslast())
        .limit(200)
        .all()
    )
    return [
        TokenSaida(
            id=t.id,
            ativo_id=t.ativo_id,
            patrimonio=a.patrimonio,
            hostname=t.hostname,
            serial=t.serial,
            ultimo_uso_em=t.ultimo_uso_em,
            ultimo_ip=t.ultimo_ip,
            revogado=t.revogado_em is not None,
        )
        for t, a in linhas
    ]


@router.delete("/admin/agentes/tokens/{token_id}")
def revogar_token(
    token_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> dict:
    token = db.get(TokenAgente, token_id)
    if token is None:
        raise HTTPException(404, "Token não encontrado.")
    token.revogado_em = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


class PendenteSaida(BaseModel):
    id: int
    serial_bruto: str | None = None
    hostname: str | None = None
    mac: str | None = None
    ip: str | None = None
    motivo: str
    visto_em: datetime
    ultima_vez_em: datetime | None = None
    basico: dict | None = None


@router.get("/admin/agentes/pendentes", response_model=list[PendenteSaida])
def listar_pendentes(
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> list[PendenteSaida]:
    """A fila: máquinas que apareceram e não foram reconhecidas."""
    linhas = (
        db.query(EquipamentoPendente)
        .filter(EquipamentoPendente.resolvido_em.is_(None))
        .order_by(EquipamentoPendente.ultima_vez_em.desc().nullslast())
        .limit(200)
        .all()
    )
    saida = []
    for p in linhas:
        try:
            bruto = json.loads(p.payload_json or "{}")
        except (ValueError, TypeError):
            bruto = {}
        saida.append(
            PendenteSaida(
                id=p.id,
                serial_bruto=p.serial_bruto,
                hostname=p.hostname,
                mac=p.mac,
                ip=p.ip,
                motivo=p.motivo,
                visto_em=p.visto_em,
                ultima_vez_em=p.ultima_vez_em,
                basico=bruto.get("basico") or {},
            )
        )
    return saida


class ResolverEntrada(BaseModel):
    # Qual campo vira o identificador da máquina: o patrimônio que o técnico
    # digita, ou o serial corrigido.
    patrimonio: str | None = Field(default=None, max_length=80)
    numero_serie: str | None = Field(default=None, max_length=120)
    ignorar: bool = False


@router.post("/admin/agentes/pendentes/{pendente_id}")
def resolver_pendente(
    pendente_id: int,
    entrada: ResolverEntrada,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> dict:
    """Resolve uma pendência: cria o ativo com o identificador escolhido.

    **Não cria sozinho** — foi justamente a criação automática que faria
    quarenta placas brancas virarem uma só. Aqui alguém decidiu.
    """
    pendente = db.get(EquipamentoPendente, pendente_id)
    if pendente is None or pendente.resolvido_em is not None:
        raise HTTPException(404, "Pendência não encontrada.")

    if entrada.ignorar:
        pendente.resolvido_em = datetime.now(timezone.utc)
        pendente.resolvido_por_id = user.id
        db.commit()
        return {"ok": True, "ignorado": True}

    from app.core.planta import exigir_planta
    from app.models.core import Ativo
    from app.models.enums import Dominio, StatusAtivo, TipoItem

    try:
        bruto = json.loads(pendente.payload_json or "{}")
    except (ValueError, TypeError):
        bruto = {}
    basico = bruto.get("basico") or {}

    ativo = Ativo(
        planta_id=exigir_planta(db, None, "resolver pendência de agente"),
        dominio=Dominio.TI,
        tipo_item=TipoItem.ATIVO,
        status=StatusAtivo.ESTOQUE,
        patrimonio=(entrada.patrimonio or None),
        numero_serie=(entrada.numero_serie or pendente.serial_bruto or None),
        modelo=(basico.get("modelo") or None),
        marca=(basico.get("fabricante") or None),
    )
    db.add(ativo)
    db.flush()

    from app.models.ti import AtivoTI

    ficha = AtivoTI(ativo_id=ativo.id)
    ficha.hostname = pendente.hostname
    ficha.mac_address = pendente.mac
    ficha.ip = pendente.ip
    ficha.so = (basico.get("so") or None)
    ficha.cpu = (basico.get("cpu") or None)
    if basico.get("ram_gb"):
        ficha.ram_gb = int(basico["ram_gb"])
    if basico.get("armazenamento_gb"):
        ficha.armazenamento_gb = int(basico["armazenamento_gb"])
    db.add(ficha)

    pendente.resolvido_em = datetime.now(timezone.utc)
    pendente.resolvido_por_id = user.id
    pendente.ativo_criado_id = ativo.id
    db.commit()

    return {"ok": True, "ativo_id": ativo.id}


class MudancaSaida(BaseModel):
    campo: str
    rotulo: str | None = None
    de: object | None = None
    para: object | None = None


class HistoricoSaida(BaseModel):
    id: int
    quando: datetime
    origem: str
    mudancas: list[MudancaSaida] = []
    # Primeira coleta não tem diff: é a linha de base.
    linha_de_base: bool = False


@router.get("/admin/agentes/historico/{ativo_id}", response_model=list[HistoricoSaida])
def historico_do_ativo(
    ativo_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
) -> list[HistoricoSaida]:
    """Alterações de hardware detectadas para um ativo, da mais recente
    para a mais antiga.

    A primeira linha é a **base**: o retrato do primeiro contato. Ela não
    tem mudanças, e mostrá-la como "alteração" confundiria — daí o
    `linha_de_base`.
    """
    from app.models.agente import HistoricoInventario

    linhas = (
        db.query(HistoricoInventario)
        .filter(HistoricoInventario.ativo_id == ativo_id)
        .order_by(HistoricoInventario.quando.desc())
        .limit(100)
        .all()
    )

    saida = []
    for h in linhas:
        try:
            bruto = json.loads(h.mudancas_json or "{}")
        except (ValueError, TypeError):
            bruto = {}
        mudancas = [
            MudancaSaida(
                campo=chave,
                rotulo=(valor or {}).get("rotulo"),
                de=(valor or {}).get("de"),
                para=(valor or {}).get("para"),
            )
            for chave, valor in bruto.items()
        ]
        saida.append(
            HistoricoSaida(
                id=h.id,
                quando=h.quando,
                origem=h.origem,
                mudancas=mudancas,
                linha_de_base=not mudancas,
            )
        )
    return saida

class SenhaEntrada(BaseModel):
    senha: str = Field(default="", max_length=200)


@router.post("/agente/validar-senha")
def validar_senha(
    entrada: SenhaEntrada,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Confere a senha de fechamento informada pelo agente.

    Autenticado pelo **token da maquina**, nao por sessao de usuario: quem
    pergunta e o agente instalado, nao uma pessoa logada no painel.

    Sem rede o agente nao consegue validar e **nao fecha** — falhar fechado
    e o comportamento certo para uma trava.
    """
    cabecalho = request.headers.get("Authorization") or ""
    if not cabecalho.lower().startswith("bearer "):
        raise HTTPException(401, "token_ausente")
    if servico.buscar_token(db, cabecalho[7:].strip()) is None:
        raise HTTPException(401, "token_invalido")

    if servico.validar_senha_fechamento(db, entrada.senha):
        return {"ok": True}
    raise HTTPException(403, "senha_incorreta")


@router.get("/admin/agentes/senha")
def estado_senha(
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> dict:
    """Diz se existe senha de fechamento, sem revelar qual."""
    from app.services import manutencao

    cfg = manutencao.configuracao(db)
    return {"definida": bool(cfg.senha_fechamento_hash)}


@router.post("/admin/agentes/senha")
def salvar_senha(
    entrada: SenhaEntrada,
    db: Session = Depends(get_db),
    user: Usuario = Depends(require_admin),
) -> dict:
    """Define ou remove a senha de fechamento do agente.

    Enviar string vazia remove a senha — e o fechamento volta a ser livre.
    """
    servico.definir_senha_fechamento(db, entrada.senha.strip() or None)
    return {"ok": True, "definida": bool(entrada.senha.strip())}
