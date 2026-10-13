"""Inventário de software e licenças.

## O caminho por onde a chave sai

Existe **um único endpoint** que devolve a chave em claro:

    GET /licencas/{id}/revelar

Ele exige a permissão `licencas.ver_chave`, **grava auditoria a cada chamada**
e é o único que usa o schema `ChaveRevelada`. Todo o resto devolve
`LicencaOut`, que não tem o campo.

Ser um gargalo único é o ponto: um segredo que sai por dez lugares não é
controlável; um que sai por um, é.

## A chave nunca é gravada em claro

Na entrada ela vem como texto; o router cifra (`app/core/segredos.py`) e
**descarta o valor original**. As colunas guardam o cifrado, a versão da chave
mestra, as 4 últimas posições (para conferência) e um hash (para achar
duplicata sem decifrar).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core import segredos
from app.core.deps import (
    get_current_user,
    require_delete,
    require_module,
    require_write,
)
from app.core.planta import aplicar_filtro, exigir_planta_do_usuario, planta_ativa
from app.database import get_db
from app.models.core import Ativo, Usuario
from app.models.enums import SituacaoConformidade, SituacaoLicenca
from app.models.software import AtribuicaoLicenca, Licenca, Software
from app.schemas.software import (
    AtribuicaoIn,
    AtribuicaoOut,
    ChaveRevelada,
    LicencaIn,
    LicencaOut,
    LinhaConformidade,
    ResumoConformidade,
    ResumoFabricante,
    SoftwareIn,
    SoftwareOut,
)
from app.services import conformidade as conformidade_service
from app.services import ocs_software
from app.services.audit_service import audit, serialize_entity

log = logging.getLogger(__name__)

router = APIRouter(
    # SEM prefixo, de proposito: com ele, "/software/{id}" capturaria
    # "/software/licencas" e "/software/conformidade" - a rota de licencas
    # viraria erro 422 de conversao para int. Caminhos explicitos evitam isso.
    tags=["software"],
    dependencies=[Depends(require_module("software"))],
)

# Permissão própria para revelar. Ver a licença e ver a CHAVE são coisas
# diferentes: a maioria das pessoas precisa da primeira. Saber que existem 50
# licenças de Office é útil; ler a chave, não.
PERMISSAO_REVELAR = "licencas.ver_chave"


def exigir_permissao_de_revelacao(user: Usuario) -> None:
    """A permissão que separa 'ver a licença' de 'ler a chave'.

    ## De onde vem a permissão

    `permissoes_efetivas` — que já combina o padrão do papel com o que o
    administrador customizou no usuário. Ler `user.permissoes` cru perderia
    o padrão do papel e daria resultado diferente do resto do sistema.

    ## O que a ausência significa

    Sem a permissão, a resposta é 403 — e o botão na tela nem aparece. A
    chave continua saindo por um caminho único, auditado, e só para quem foi
    explicitamente autorizado.
    """
    from app.core.permissoes import permissoes_efetivas

    efetivas = permissoes_efetivas(user)
    concedidas = set(efetivas.get("permissoes_extra") or [])

    # Administrador sempre pode — é quem responde pela auditoria do
    # fabricante, e trancá-lo fora deixaria o sistema sem quem revele.
    papel = getattr(user.papel, "value", user.papel)
    if papel == "admin" or PERMISSAO_REVELAR in concedidas:
        return

    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        f"Sem permissão para revelar chaves de licença ({PERMISSAO_REVELAR}). "
        f"Peça ao administrador em Administração → Usuários.",
    )

def _aplicar_chave(destino: Licenca, texto: str | None, user: Usuario, db: Session,
                   acao: str) -> None:
    """Cifra e grava a chave, descartando o texto original.

    ## A chave não entra no `diff` da auditoria

    A auditoria é encadeada por hash: o que entra nela não sai mais. O
    `audit()` recebe a licença, e `serialize_entity` troca os campos de chave
    por `<protegido>` (ver `CAMPOS_PROTEGIDOS`).

    **Isto é o que impede o vazamento permanente** — não a cifra. A cifra
    protege o banco; a exclusão protege o histórico.
    """
    if texto is None:
        return

    texto = texto.strip()
    if not texto:
        return

    # Chave repetida costuma ser erro de digitação, e duas licenças com o
    # mesmo número fazem a conformidade contar duas vezes. O hash permite
    # detectar SEM decifrar nada.
    impressao = segredos.impressao_hash(texto)
    duplicada = (
        db.query(Licenca)
        .filter(Licenca.chave_hash == impressao, Licenca.deleted_at.is_(None),
                Licenca.id != (destino.id or 0))
        .first()
    )
    if duplicada:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Esta chave já está cadastrada na licença #{duplicada.id}.",
        )

    seg = segredos.cifrar(texto)
    if seg is None:
        return
    destino.chave_cifrada = seg.cifrado
    destino.chave_versao = seg.versao
    destino.chave_impressao = segredos.impressao(texto)
    destino.chave_hash = impressao



def _auditar(db: Session, user: Usuario, acao: str, entidade: str, entidade_id: int,
             antes: object | None = None, depois: object | None = None,
             extra: dict | None = None) -> None:
    """Grava auditoria com o diff SEMPRE passando por `serialize_entity`.

    ## Por que não montar o diff à mão

    `serialize_entity` é onde vive `CAMPOS_PROTEGIDOS` — a lista que troca
    chaves e senhas por `<protegido>`. Um `{c.name: getattr(obj, c.name)}`
    escrito direto no router **contorna essa lista** e grava o segredo.

    E a auditoria é encadeada por hash: o que entra nela não sai mais. Este
    helper existe para que não haja um segundo caminho.
    """
    diff: dict = {}
    # Aceita o objeto OU um dicionario ja serializado. No editar, o "antes"
    # precisa ser uma COPIA tirada antes das alteracoes - o objeto vivo ja
    # teria os valores novos, e o diff mostraria que nada mudou.
    if antes is not None:
        diff["antes"] = antes if isinstance(antes, dict) else serialize_entity(antes)
    if depois is not None:
        diff["depois"] = depois if isinstance(depois, dict) else serialize_entity(depois)
    if extra:
        diff.update(extra)
    audit(db, user, acao, entidade, entidade_id, diff=diff)




def _no_escopo(obj, planta: int | None, nome: str = "Registro"):
    """Confere se o objeto é visível na planta do usuário.

    ## Por que 404, e não 403

    Um 403 confirma que o registro **existe** — e isso já é informação sobre
    outra unidade ("existe a licença #42"). O 404 não distingue "não existe"
    de "não é seu", que é o comportamento correto aqui.

    ## A licença corporativa

    `planta_id` nulo significa **corporativo**: uma licença de volume da
    empresa toda não pertence a uma unidade. Escondendo-a de quem filtra por
    planta, o administrador de uma unidade não veria as licenças que a
    empresa já comprou — e compraria de novo.
    """
    if obj is None or getattr(obj, "deleted_at", None):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{nome} não encontrado.")

    if planta is None:
        return obj  # administrador na visão consolidada

    dono = getattr(obj, "planta_id", None)
    if dono is not None and dono != planta:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{nome} não encontrado.")
    return obj


def _licenca_no_escopo(db: Session, licenca_id: int, planta: int | None) -> Licenca:
    """A licença, conferindo o escopo pela própria planta dela."""
    return _no_escopo(db.get(Licenca, licenca_id), planta, "Licença")


def _planta_do_corpo(planta: int | None, user: Usuario) -> int | None:
    """Valida a planta vinda do corpo da requisição.

    ## O furo que isto fecha

    O `planta_id` do corpo era gravado direto: um usuário comum podia criar
    um software na planta de outra unidade só informando o id — e passaria a
    enxergá-lo depois, porque as listas filtram por planta.

    ## Duas checagens, não uma

    `exigir_planta_do_usuario` garante que **há** planta (usuário sem planta
    veria todas). Mas não basta: um usuário da unidade A informando o id da
    unidade B passaria. A segunda checagem é a que compara com a planta
    **dele**, e era a que faltava.

    Administrador continua livre — é quem move registro entre unidades.
    """
    exigir_planta_do_usuario(user, planta)

    papel = getattr(user.papel, "value", user.papel)
    if papel == "admin":
        return planta

    if planta is not None and planta != user.planta_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Você só pode criar registros na sua própria planta.",
        )
    return planta


# ---------------------------------------------------------------------------
# Software
# ---------------------------------------------------------------------------
@router.get("/softwares", response_model=list[SoftwareOut])
def listar_software(
    busca: str | None = Query(default=None),
    db: Session = Depends(get_db),
    planta: int | None = Depends(planta_ativa),
):
    q = db.query(Software).filter(Software.deleted_at.is_(None))
    q = aplicar_filtro(q, Software, planta)
    if busca:
        alvo = f"%{busca.lower()}%"
        q = q.filter(Software.nome.ilike(alvo) | Software.fabricante.ilike(alvo))
    return q.order_by(Software.nome).all()


@router.post("/softwares", response_model=SoftwareOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(require_write)])
def criar_software(dados: SoftwareIn, db: Session = Depends(get_db),
                   user: Usuario = Depends(get_current_user),
                   planta: int | None = Depends(planta_ativa)):
    dados.planta_id = _planta_do_corpo(dados.planta_id or planta, user)
    s = Software(**dados.model_dump())
    db.add(s)
    db.flush()
    _auditar(db, user, "criar", "software", s.id, depois=s)
    db.commit()
    db.refresh(s)
    return s


@router.get("/softwares/{software_id}", response_model=SoftwareOut)
def obter_software(software_id: int, db: Session = Depends(get_db),
                   user: Usuario = Depends(get_current_user),
                   planta: int | None = Depends(planta_ativa),
               ):
    s = _no_escopo(db.get(Software, software_id), planta, "Software")
    return s


@router.put("/softwares/{software_id}", response_model=SoftwareOut,
            dependencies=[Depends(require_write)])
def editar_software(software_id: int, dados: SoftwareIn, db: Session = Depends(get_db),
                    user: Usuario = Depends(get_current_user),
                    planta: int | None = Depends(planta_ativa),
                ):
    s = _no_escopo(db.get(Software, software_id), planta, "Software")
    antes = serialize_entity(s)
    for k, v in dados.model_dump().items():
        setattr(s, k, v)
    _auditar(db, user, "editar", "software", s.id, antes=antes, depois=s)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/softwares/{software_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_delete)])
def apagar_software(software_id: int, db: Session = Depends(get_db),
                    user: Usuario = Depends(get_current_user),
                    planta: int | None = Depends(planta_ativa),
                ):
    s = _no_escopo(db.get(Software, software_id), planta, "Software")

    vivas = [lic for lic in s.licencas if lic.deleted_at is None]
    if vivas:
        # Apagar o software levaria as licenças junto (cascade) — e com elas o
        # histórico de quanto foi pago. Melhor recusar e dizer o que fazer.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Há {len(vivas)} licença(s) deste software. Remova-as primeiro.",
        )
    s.deleted_at = datetime.now(timezone.utc)
    _auditar(db, user, "apagar", "software", s.id, antes=s)
    db.commit()


# ---------------------------------------------------------------------------
# Licença
# ---------------------------------------------------------------------------
def _out(lic: Licenca) -> LicencaOut:
    """Monta a saída calculando os derivados. A chave não está aqui."""
    return LicencaOut(
        **{c.name: getattr(lic, c.name) for c in Licenca.__table__.columns},
        chave_mascarada=lic.chave_mascarada,
        tem_chave=lic.tem_chave(),
        vencida=lic.vencida,
        dias_para_vencer=lic.dias_para_vencer,
        seats_usados=lic.seats_usados,
        seats_livres=lic.seats_livres,
    )


@router.get("/licencas", response_model=list[LicencaOut])
def listar_licencas(
    software_id: int | None = Query(default=None),
    situacao: SituacaoLicenca | None = Query(default=None),
    db: Session = Depends(get_db),
    planta: int | None = Depends(planta_ativa),
):
    q = db.query(Licenca).filter(Licenca.deleted_at.is_(None))
    q = aplicar_filtro(q, Licenca, planta)
    if software_id:
        q = q.filter(Licenca.software_id == software_id)
    if situacao:
        q = q.filter(Licenca.situacao == situacao)
    return [_out(lic) for lic in q.order_by(Licenca.validade.desc().nullslast()).all()]


@router.post("/licencas", response_model=LicencaOut,
             status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_write)])
def criar_licenca(dados: LicencaIn, db: Session = Depends(get_db),
                  user: Usuario = Depends(get_current_user),
                  planta: int | None = Depends(planta_ativa)):
    if not db.get(Software, dados.software_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Software não encontrado.")

    corpo = dados.model_dump()
    texto = corpo.pop("chave", None)
    corpo["planta_id"] = _planta_do_corpo(corpo.get("planta_id") or planta, user)

    lic = Licenca(**corpo)
    db.add(lic)
    db.flush()

    _aplicar_chave(lic, texto, user, db, "criar")

    # A auditoria recebe a licença já com a chave cifrada — e `serialize_entity`
    # a troca por `<protegido>`. O texto puro nunca chegou ao banco.
    _auditar(db, user, "criar", "licenca", lic.id, depois=lic)
    db.commit()
    db.refresh(lic)
    return _out(lic)


@router.get("/licencas/{licenca_id}", response_model=LicencaOut)
def obter_licenca(licenca_id: int, db: Session = Depends(get_db),
                  user: Usuario = Depends(get_current_user),
                  planta: int | None = Depends(planta_ativa),
              ):
    lic = _licenca_no_escopo(db, licenca_id, planta)
    return _out(lic)


@router.put("/licencas/{licenca_id}", response_model=LicencaOut,
            dependencies=[Depends(require_write)])
def editar_licenca(licenca_id: int, dados: LicencaIn, db: Session = Depends(get_db),
                   user: Usuario = Depends(get_current_user),
                   planta: int | None = Depends(planta_ativa),
               ):
    lic = _licenca_no_escopo(db, licenca_id, planta)

    antes = serialize_entity(lic)
    corpo = dados.model_dump()
    texto = corpo.pop("chave", None)
    for k, v in corpo.items():
        setattr(lic, k, v)

    # Chave vazia na edição significa "não mexer" — trocar por nada apagaria
    # o segredo por acidente de formulário.
    _aplicar_chave(lic, texto, user, db, "editar")

    _auditar(db, user, "editar", "licenca", lic.id, antes=antes, depois=lic)
    db.commit()
    db.refresh(lic)
    return _out(lic)


@router.delete("/licencas/{licenca_id}", status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(require_delete)])
def apagar_licenca(licenca_id: int, db: Session = Depends(get_db),
                   user: Usuario = Depends(get_current_user),
                   planta: int | None = Depends(planta_ativa),
               ):
    lic = _licenca_no_escopo(db, licenca_id, planta)
    lic.deleted_at = datetime.now(timezone.utc)
    _auditar(db, user, "apagar", "licenca", lic.id, antes=lic)
    db.commit()


# ---------------------------------------------------------------------------
# O ÚNICO caminho por onde a chave sai
# ---------------------------------------------------------------------------
@router.get("/licencas/{licenca_id}/revelar", response_model=ChaveRevelada)
def revelar_chave(licenca_id: int, db: Session = Depends(get_db),
                  user: Usuario = Depends(get_current_user),
                  planta: int | None = Depends(planta_ativa)):
    """Devolve a chave em claro. **Toda chamada é auditada.**

    ## Por que a auditoria aqui não é opcional

    Saber *quem leu a chave* é o que permite investigar um vazamento depois.
    Sem este registro, um uso irregular descoberto pelo fabricante não teria
    como ser rastreado até uma pessoa — e a empresa responderia por todos.

    O registro guarda **que** a chave foi revelada, por quem e quando. O valor
    não entra: a auditoria é imutável, e um segredo gravado nela está vazado
    para sempre.
    """
    exigir_permissao_de_revelacao(user)

    lic = _licenca_no_escopo(db, licenca_id, planta)
    if not lic.tem_chave():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Esta licença não tem chave cadastrada.")

    try:
        texto = segredos.decifrar(lic.chave_cifrada, lic.chave_versao)
    except segredos.ChaveMestraAusente as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except segredos.SegredoIlegivel as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    if not texto:  # pragma: no cover - decifrar devolveria None antes
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chave vazia.")

    # `depois` recebe a licença, e o valor NÃO entra no diff: só o campo
    # `chave_revelada`, que registra o evento sem registrar o segredo.
    _auditar(db, user, "revelar_chave", "licenca", lic.id,
             extra={"chave_revelada": True})
    db.commit()

    return ChaveRevelada(
        id=lic.id,
        chave=texto,
        revelada_em=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Atribuições
# ---------------------------------------------------------------------------
def _atribuicao_out(a: AtribuicaoLicenca) -> AtribuicaoOut:
    return AtribuicaoOut(
        **{c.name: getattr(a, c.name) for c in AtribuicaoLicenca.__table__.columns},
        ativo_patrimonio=a.ativo.patrimonio if a.ativo else None,
        usuario_nome=a.usuario.nome if a.usuario else None,
    )


@router.post("/licencas/{licenca_id}/atribuicoes", response_model=AtribuicaoOut,
             status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_write)])
def atribuir(licenca_id: int, dados: AtribuicaoIn, db: Session = Depends(get_db),
             user: Usuario = Depends(get_current_user),
             planta: int | None = Depends(planta_ativa),
         ):
    lic = _licenca_no_escopo(db, licenca_id, planta)

    if lic.seats_livres <= 0:
        # Atribuir além dos seats comprados é exatamente o que gera risco em
        # auditoria. O sistema recusa na hora, e não depois.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Os {lic.seats} seats desta licença já estão em uso. "
            "Compre mais ou libere uma atribuição.",
        )

    if dados.ativo_id and not db.get(Ativo, dados.ativo_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ativo não encontrado.")
    if dados.usuario_id and not db.get(Usuario, dados.usuario_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado.")

    a = AtribuicaoLicenca(licenca_id=lic.id, origem="manual", **dados.model_dump())
    db.add(a)
    db.flush()
    _auditar(db, user, "atribuir", "licenca", lic.id, depois=a)
    db.commit()
    db.refresh(a)
    return _atribuicao_out(a)


@router.delete("/licencas/{licenca_id}/atribuicoes/{atribuicao_id}",
               status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_delete)])
def liberar(licenca_id: int, atribuicao_id: int, db: Session = Depends(get_db),
            user: Usuario = Depends(get_current_user),
            planta: int | None = Depends(planta_ativa),
        ):
    _licenca_no_escopo(db, licenca_id, planta)
    a = db.get(AtribuicaoLicenca, atribuicao_id)
    if not a or a.deleted_at or a.licenca_id != licenca_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Atribuição não encontrada.")
    a.deleted_at = datetime.now(timezone.utc)
    _auditar(db, user, "liberar", "licenca", licenca_id, antes=a)
    db.commit()


# ---------------------------------------------------------------------------
# Conformidade
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Listagem de atribuições — as duas visões
# ---------------------------------------------------------------------------
@router.get("/licencas/{licenca_id}/atribuicoes", response_model=list[AtribuicaoOut])
def listar_atribuicoes_da_licenca(
    licenca_id: int,
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta: int | None = Depends(planta_ativa),
):
    """Quem usa esta licença, e quais seats estão livres.

    O escopo é conferido pela licença: uma atribuição não tem planta própria,
    ela herda a da licença. Sem isso, daria para listar quem usa a licença de
    outra unidade sabendo o id.
    """
    lic = _licenca_no_escopo(db, licenca_id, planta)

    return [
        _atribuicao_out(a)
        for a in (
            db.query(AtribuicaoLicenca)
            .filter(
                AtribuicaoLicenca.licenca_id == lic.id,
                AtribuicaoLicenca.deleted_at.is_(None),
            )
            .order_by(AtribuicaoLicenca.id)
            .all()
        )
    ]


@router.get("/atribuicoes", response_model=list[AtribuicaoOut])
def listar_atribuicoes(
    ativo_id: int | None = Query(default=None),
    usuario_id: int | None = Query(default=None),
    software_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta: int | None = Depends(planta_ativa),
):
    """A visão inversa: o que este ativo — ou esta pessoa — tem direito.

    ## Por que existe

    O caminho natural de quem opera é a partir do **equipamento** ou da
    **pessoa**, não da licença. Sem esta rota, responder *"posso formatar
    esta máquina?"* exigiria abrir licença por licença.

    ## Os filtros

    Todos opcionais e combináveis. Sem nenhum, devolve tudo o que a planta
    permite — o que é útil para auditoria e para exportar.

    O escopo vem da **licença**, que é quem tem planta: a atribuição não tem
    planta própria. Sem este filtro, a rota listaria atribuições de qualquer
    unidade.
    """
    q = (
        db.query(AtribuicaoLicenca)
        .join(Licenca, Licenca.id == AtribuicaoLicenca.licenca_id)
        .filter(
            AtribuicaoLicenca.deleted_at.is_(None),
            Licenca.deleted_at.is_(None),
        )
    )

    # Escopo por planta. Licença corporativa (`planta_id` nulo) vale em toda
    # unidade — é o que significa corporativo.
    if planta is not None:
        q = q.filter(
            (Licenca.planta_id.is_(None)) | (Licenca.planta_id == planta)
        )

    if ativo_id is not None:
        q = q.filter(AtribuicaoLicenca.ativo_id == ativo_id)
    if usuario_id is not None:
        q = q.filter(AtribuicaoLicenca.usuario_id == usuario_id)
    if software_id is not None:
        q = q.filter(Licenca.software_id == software_id)

    return [
        _atribuicao_out(a)
        for a in q.order_by(AtribuicaoLicenca.id.desc()).limit(500).all()
    ]


@router.get("/conformidade", response_model=ResumoConformidade)
def conformidade(db: Session = Depends(get_db),
                 user: Usuario = Depends(get_current_user),
                 planta: int | None = Depends(planta_ativa)):
    """Cruza o que foi comprado com o que está instalado.

    ## De onde vem o "instalado"

    De softwares_instalados, alimentada pelo OCS Inventory. Quando a tabela
    está vazia (OCS ainda não configurado), o cruzamento cai para as
    **atribuições** — o que o operador registrou como em uso. É menos exato e
    continua respondendo "quantos seats estão livres".

    ## Por que a tela abre por aqui

    Quem entra quer saber se está em risco, não quantos títulos existem.
    A ordenação põe excedente e sem-licença no topo.
    """
    # Uma montagem só, compartilhada com o CSV e o resumo por fabricante —
    # repetir faria os três divergirem no dia em que um fosse ajustado.
    linhas = _linhas_conformidade(db, planta)
    # A data REAL da coleta, não a hora desta consulta — ver
    # conformidade.ultima_coleta.
    r = conformidade_service.resumo(
        linhas, conformidade_service.ultima_coleta(db)
    )

    return ResumoConformidade(
        titulos=r["titulos"], excedente=r["excedente"], ocioso=r["ocioso"],
        sem_licenca=r["sem_licenca"], custo_mensal=r["custo_mensal"],
        linhas=[LinhaConformidade(**{k: v for k, v in x.items()
                                     if k in LinhaConformidade.model_fields})
                for x in linhas],
        atualizado_em=r["atualizado_em"],
    )


def _linhas_conformidade(db: Session, planta: int | None) -> list[dict]:
    """As linhas de conformidade, já com escopo de planta e explicação.

    Extraído porque **três** endpoints precisam do mesmo cálculo: a tela, o
    CSV e o resumo por fabricante. Repetir a montagem em cada um faria os
    três divergirem no dia em que um fosse ajustado.
    """
    qs = db.query(Software).filter(Software.deleted_at.is_(None))
    qs = aplicar_filtro(qs, Software, planta)
    softwares = qs.all()

    instalados = conformidade_service.instalados_por_nome(db, planta_id=planta)
    if not instalados:
        instalados = conformidade_service.instalados_das_atribuicoes(db)

    return conformidade_service.ordenar(
        conformidade_service.calcular(db, softwares, instalados)
    )

# ---------------------------------------------------------------------------
# Coleta no OCS Inventory
# ---------------------------------------------------------------------------
def _config_ocs(db: Session):
    """A configuração do OCS, ou None se ainda não houver."""
    from app.models.ocs import ConfiguracaoOCS

    return (
        db.query(ConfiguracaoOCS)
        .filter(ConfiguracaoOCS.deleted_at.is_(None))
        .first()
    )


@router.get("/ocs/resumo")
def ocs_resumo(db: Session = Depends(get_db),
               user: Usuario = Depends(get_current_user)):
    """O que já está gravado, sem refazer a coleta.

    A `taxa_reconhecimento` é o indicador de saúde do módulo: baixa significa
    que os padrões de reconhecimento estão fracos, e a conformidade vai
    mostrar muito software como "sem licença".

    Ler este número **antes** de concluir que há uso irregular evita caçar um
    problema de licença que é, na verdade, problema de cadastro.
    """
    return ocs_software.resumo_do_banco(db)


@router.post("/ocs/coletar", dependencies=[Depends(require_write)])
def ocs_coletar(
    limite: int | None = Query(default=None, ge=1, le=20000,
                               description="Máquinas a processar (para testar)"),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
):
    """Puxa a lista de programas de cada máquina no OCS.

    ## Operação pesada

    Uma chamada ao OCS **por máquina**. Num parque de 5.000 são 5.000
    requisições — por isso `limite` existe: dá para testar em 10 máquinas
    antes de rodar no parque inteiro.

    A lista de cada máquina é substituída, e não somada: programa
    desinstalado precisa sair do relatório, senão a conformidade acusaria
    instalações que não existem mais e o número só cresceria.
    """
    cfg = _config_ocs(db)
    if cfg is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "OCS Inventory não está configurado. Configure em "
            "Administração → OCS Inventory.",
        )

    r = ocs_software.coletar(db, cfg, limite=limite)
    audit(db, user, "coletar", "software_ocs", None, diff={"resumo": r.como_dict()})
    db.commit()
    return r.como_dict()


@router.post("/ocs/reconhecer", dependencies=[Depends(require_write)])
def ocs_reconhecer(db: Session = Depends(get_db),
                   user: Usuario = Depends(get_current_user)):
    """Recasa o já coletado com os padrões atuais.

    ## Por que não basta rodar a coleta de novo

    Ajustar um padrão em `Software` precisa refletir no que **já** está
    gravado. Sem este endpoint a correção só valeria na próxima coleta — e o
    operador concluiria que o ajuste não funcionou.

    Não toca no OCS: trabalha só no banco, e por isso é rápido mesmo com
    centenas de milhares de linhas.
    """
    mudados = ocs_software.aplicar_reconhecimento(db)
    audit(db, user, "reconhecer", "software_ocs", None, diff={"mudados": mudados})
    db.commit()
    return {"reconhecidos": mudados, **ocs_software.resumo_do_banco(db)}


@router.get("/licencas/{licenca_id}/historico")
def historico_da_licenca(
    licenca_id: int,
    limite: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta: int | None = Depends(planta_ativa),
):
    """Quem mexeu nesta licença, quando e o quê.

    ## De onde vem

    Da auditoria, que já registra tudo — criar, editar, atribuir, liberar e
    revelar chave. Este endpoint só filtra e dá o escopo.

    ## Por que não usar `/auditoria` direto

    Aquele exige **administrador**. Quem cuida das licenças não é
    necessariamente admin, e precisa saber que a licença mudou — quem
    atribuiu, quando, e se alguém revelou a chave.

    ## O valor da chave não aparece

    O diff da auditoria grava `<protegido>` no lugar do segredo — ver
    `CAMPOS_PROTEGIDOS`. A auditoria é imutável, então uma chave gravada nela
    estaria vazada para sempre.
    """
    # Confere o escopo: quem não enxerga a licença não vê o histórico dela.
    lic = _licenca_no_escopo(db, licenca_id, planta)

    from app.models.core import LogAuditoria
    from app.models.core import Usuario as _Usuario

    registros = (
        db.query(LogAuditoria, _Usuario.nome)
        .outerjoin(_Usuario, _Usuario.id == LogAuditoria.usuario_id)
        .filter(
            LogAuditoria.entidade == "licenca",
            LogAuditoria.entidade_id == lic.id,
        )
        .order_by(LogAuditoria.id.desc())
        .limit(limite)
        .all()
    )

    ROTULO = {
        "criar": "Licença criada",
        "editar": "Licença alterada",
        "apagar": "Licença removida",
        "atribuir": "Seat atribuído",
        "liberar": "Seat liberado",
        "revelar_chave": "Chave revelada",
    }

    return {
        "licenca_id": lic.id,
        "eventos": [
            {
                "id": log.id,
                "acao": getattr(log.acao, "value", log.acao),
                "descricao": ROTULO.get(
                    getattr(log.acao, "value", log.acao), log.acao
                ),
                "usuario": nome or "—",
                "quando": log.created_at,
                "ip": log.ip,
                # O diff já vem com `<protegido>` nos campos sensíveis.
                "diff": log.diff,
                # A revelação da chave é o evento que mais interessa a quem
                # audita: é o único em que um SEGREDO saiu do sistema.
                "relevante": getattr(log.acao, "value", log.acao) == "revelar_chave",
            }
            for log, nome in registros
        ],
    }


@router.get("/conformidade.csv")
def conformidade_csv(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta: int | None = Depends(planta_ativa),
):
    """O relatório de conformidade em CSV, com a explicação de cada linha.

    ## Por que exportar

    Quem decide compra de licença **leva o número para uma reunião** — e uma
    tela não vai junto. Sem exportar, alguém redigita, e o número redigitado
    deixa de ser o número do sistema.

    O CSV sai com a explicação e a ação recomendada: é o que permite decidir
    fora do sistema sem perder o contexto.
    """
    linhas = _linhas_conformidade(db, planta)
    conteudo = conformidade_service.para_csv(linhas)

    from fastapi.responses import Response

    return Response(
        content=conteudo,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="conformidade.csv"',
            # `no-store`: o arquivo tem nome de software e contagem do parque.
            "Cache-Control": "no-store",
        },
    )


@router.get("/conformidade/fabricantes", response_model=list[ResumoFabricante])
def conformidade_por_fabricante(
    db: Session = Depends(get_db),
    user: Usuario = Depends(get_current_user),
    planta: int | None = Depends(planta_ativa),
):
    """Custo e uso agrupados por fabricante.

    Responde **com quem renegociar**: um parque com o gasto concentrado num
    fornecedor só tem poder de negociação — e isso não aparece numa lista
    ordenada por nome de software.
    """
    linhas = _linhas_conformidade(db, planta)

    grupos: dict[str, dict] = {}
    for x in linhas:
        chave = (x.get("fabricante") or "Não informado").strip() or "Não informado"
        g = grupos.setdefault(chave, {
            "fabricante": chave, "titulos": 0, "seats": 0, "em_uso": 0,
            "custo_mensal": Decimal("0"), "excedente": 0, "ocioso": 0,
        })
        g["titulos"] += 1
        g["seats"] += x["licenciado"]
        g["em_uso"] += x["instalado"]
        g["custo_mensal"] += x.get("custo_mensal") or Decimal("0")
        if x["situacao"] == SituacaoConformidade.EXCEDENTE:
            g["excedente"] += 1
        elif x["situacao"] == SituacaoConformidade.OCIOSO:
            g["ocioso"] += 1

    total = sum((g["custo_mensal"] for g in grupos.values()), Decimal("0")) or Decimal("1")
    saida = []
    for g in grupos.values():
        g["participacao"] = round(float(g["custo_mensal"] / total) * 100, 1)
        saida.append(g)

    # O maior gasto primeiro — é ele que interessa para negociar.
    saida.sort(key=lambda g: g["custo_mensal"], reverse=True)
    return saida
