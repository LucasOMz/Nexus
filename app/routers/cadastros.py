"""CRUD das entidades de cadastro (lookups) e de usuários.

Estas tabelas alimentam os formulários de ativos/produtos em ambos os domínios.
Leitura: qualquer autenticado. Escrita: admin|ti (usuários: apenas admin).
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin, require_escrita, require_exclusao
from app.core.security import hash_password
from app.database import get_db
from app.models.core import Categoria, Departamento, Fornecedor, Localizacao, Usuario
from app.models.enums import Dominio
from app.schemas.common import (
    CategoriaCreate,
    CategoriaOut,
    DepartamentoCreate,
    DepartamentoOut,
    FornecedorCreate,
    FornecedorOut,
    LocalizacaoCreate,
    LocalizacaoOut,
    UsuarioCreate,
    UsuarioOut,
    UsuarioUpdate,
)
from app.services.audit_service import audit

router = APIRouter(tags=["cadastros"])

# Escrita/exclusão de cadastros exigem o módulo "cadastros" + a permissão.
cad_write = require_escrita("cadastros")
cad_delete = require_exclusao("cadastros")


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Departamento
# ---------------------------------------------------------------------------
@router.get("/departamentos", response_model=list[DepartamentoOut])
def list_departamentos(db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    return db.query(Departamento).filter(Departamento.deleted_at.is_(None)).order_by(Departamento.nome).all()


@router.post("/departamentos", response_model=DepartamentoOut, status_code=201)
def create_departamento(
    body: DepartamentoCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(cad_write)
):
    obj = Departamento(**body.model_dump())
    db.add(obj)
    db.flush()
    audit(db, user, "create", "departamento", obj.id, ip=_ip(request), diff=body.model_dump())
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/departamentos/{dep_id}", response_model=DepartamentoOut)
def update_departamento(
    dep_id: int, body: DepartamentoCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(cad_write)
):
    obj = db.get(Departamento, dep_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Departamento não encontrado")
    for k, v in body.model_dump().items():
        setattr(obj, k, v)
    audit(db, user, "update", "departamento", obj.id, ip=_ip(request), diff=body.model_dump())
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/departamentos/{dep_id}", status_code=204)
def delete_departamento(
    dep_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(cad_delete)
):
    obj = db.get(Departamento, dep_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Departamento não encontrado")
    obj.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "departamento", obj.id, ip=_ip(request))
    db.commit()


# ---------------------------------------------------------------------------
# Localização
# ---------------------------------------------------------------------------
@router.get("/localizacoes", response_model=list[LocalizacaoOut])
def list_localizacoes(db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    return db.query(Localizacao).filter(Localizacao.deleted_at.is_(None)).order_by(Localizacao.nome).all()


@router.post("/localizacoes", response_model=LocalizacaoOut, status_code=201)
def create_localizacao(
    body: LocalizacaoCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(cad_write)
):
    obj = Localizacao(**body.model_dump())
    db.add(obj)
    db.flush()
    audit(db, user, "create", "localizacao", obj.id, ip=_ip(request), diff=body.model_dump())
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/localizacoes/{loc_id}", response_model=LocalizacaoOut)
def update_localizacao(
    loc_id: int, body: LocalizacaoCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(cad_write)
):
    obj = db.get(Localizacao, loc_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Localização não encontrada")
    for k, v in body.model_dump().items():
        setattr(obj, k, v)
    audit(db, user, "update", "localizacao", obj.id, ip=_ip(request), diff=body.model_dump())
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/localizacoes/{loc_id}", status_code=204)
def delete_localizacao(
    loc_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(cad_delete)
):
    obj = db.get(Localizacao, loc_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Localização não encontrada")
    obj.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "localizacao", obj.id, ip=_ip(request))
    db.commit()


# ---------------------------------------------------------------------------
# Fornecedor
# ---------------------------------------------------------------------------
@router.get("/fornecedores", response_model=list[FornecedorOut])
def list_fornecedores(db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    return db.query(Fornecedor).filter(Fornecedor.deleted_at.is_(None)).order_by(Fornecedor.nome).all()


@router.post("/fornecedores", response_model=FornecedorOut, status_code=201)
def create_fornecedor(
    body: FornecedorCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(cad_write)
):
    obj = Fornecedor(**body.model_dump())
    db.add(obj)
    db.flush()
    audit(db, user, "create", "fornecedor", obj.id, ip=_ip(request), diff=body.model_dump())
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/fornecedores/{for_id}", response_model=FornecedorOut)
def update_fornecedor(
    for_id: int, body: FornecedorCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(cad_write)
):
    obj = db.get(Fornecedor, for_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Fornecedor não encontrado")
    for k, v in body.model_dump().items():
        setattr(obj, k, v)
    audit(db, user, "update", "fornecedor", obj.id, ip=_ip(request), diff=body.model_dump())
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/fornecedores/{for_id}", status_code=204)
def delete_fornecedor(
    for_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(cad_delete)
):
    obj = db.get(Fornecedor, for_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Fornecedor não encontrado")
    obj.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "fornecedor", obj.id, ip=_ip(request))
    db.commit()


# ---------------------------------------------------------------------------
# Categoria
# ---------------------------------------------------------------------------
@router.get("/categorias", response_model=list[CategoriaOut])
def list_categorias(
    dominio: Dominio | None = Query(default=None),
    db: Session = Depends(get_db),
    _: Usuario = Depends(get_current_user),
):
    q = db.query(Categoria).filter(Categoria.deleted_at.is_(None))
    if dominio is not None:
        # NULL (comum) OU do domínio solicitado.
        q = q.filter((Categoria.dominio.is_(None)) | (Categoria.dominio == dominio))
    return q.order_by(Categoria.nome).all()


@router.post("/categorias", response_model=CategoriaOut, status_code=201)
def create_categoria(
    body: CategoriaCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(cad_write)
):
    obj = Categoria(**body.model_dump())
    db.add(obj)
    db.flush()
    audit(db, user, "create", "categoria", obj.id, ip=_ip(request), diff=body.model_dump())
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/categorias/{cat_id}", response_model=CategoriaOut)
def update_categoria(
    cat_id: int, body: CategoriaCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(cad_write)
):
    obj = db.get(Categoria, cat_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Categoria não encontrada")
    for k, v in body.model_dump().items():
        setattr(obj, k, v)
    audit(db, user, "update", "categoria", obj.id, ip=_ip(request), diff=body.model_dump())
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/categorias/{cat_id}", status_code=204)
def delete_categoria(
    cat_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(cad_delete)
):
    obj = db.get(Categoria, cat_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Categoria não encontrada")
    obj.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "categoria", obj.id, ip=_ip(request))
    db.commit()


# ---------------------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------------------
@router.get("/usuarios", response_model=list[UsuarioOut])
def list_usuarios(db: Session = Depends(get_db), _: Usuario = Depends(get_current_user)):
    return db.query(Usuario).filter(Usuario.deleted_at.is_(None)).order_by(Usuario.nome).all()


@router.post("/usuarios", response_model=UsuarioOut, status_code=201)
def create_usuario(
    body: UsuarioCreate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)
):
    """Cadastra um usuário. **É o administrador quem libera o acesso.**

    Duas formas de conta:

    * **Rede (AD)** — informe o `login_ad`. A senha não é gravada: quem valida
      é o diretório. É o caso do técnico que entra com usuário e senha de rede.
    * **Local** — informe a `senha`; ela é validada pelo próprio sistema.

    Em nenhuma delas o acesso é automático: sem este cadastro, alguém com senha
    de rede válida não entra.
    """
    if db.query(Usuario).filter(Usuario.email == body.email, Usuario.deleted_at.is_(None)).first():
        raise HTTPException(409, "E-mail já cadastrado")

    login_ad = (body.login_ad or "").strip() or None
    if login_ad:
        repetido = (
            db.query(Usuario)
            .filter(func.lower(Usuario.login_ad) == login_ad.lower(), Usuario.deleted_at.is_(None))
            .first()
        )
        if repetido is not None:
            raise HTTPException(409, f"O usuário de rede '{login_ad}' já está cadastrado para {repetido.nome}.")

    if not login_ad and not body.senha:
        raise HTTPException(400, "Informe uma senha (conta local) ou o usuário de rede (conta do AD).")

    # `exigir_mfa` e instrucao de CADASTRO, nao coluna: sai do dump e vira a
    # flag `mfa_obrigatorio` abaixo.
    data = body.model_dump(exclude={"senha", "login_ad", "exigir_mfa"})
    # Conta do AD: a senha local é SEMPRE aleatória e inútil — quem autentica é
    # o diretório. Mesmo que venha uma senha no cadastro, ela não é gravada:
    # guardá-la deixaria uma credencial utilizável que ninguém deveria ter.
    senha_hash = hash_password(secrets.token_urlsafe(32)) if login_ad else hash_password(body.senha)

    obj = Usuario(
        **data,
        login_ad=login_ad,
        origem="ad" if login_ad else "local",
        senha_hash=senha_hash,
        # --- Primeiro acesso ---------------------------------------------
        # Senha local é definida pelo ADMINISTRADOR e entregue à pessoa: ela é
        # conhecida por outra pessoa, então o sistema exige a troca antes de
        # liberar qualquer coisa. Numa conta de AD não há o que trocar aqui; a
        # senha é da rede.
        senha_temporaria=not login_ad,
        # Conta nova (local ou de rede) precisa registrar a segunda etapa no
        # primeiro acesso. Quem já entra com senha de rede tem a identidade
        # confirmada, mas não a posse do aparelho — MFA cobre justamente isso.
        mfa_obrigatorio=bool(body.exigir_mfa),
    )
    db.add(obj)
    db.flush()
    audit(db, user, "create", "usuario", obj.id, ip=_ip(request),
          diff={**data, "login_ad": login_ad, "senha": "***"})
    db.commit()
    db.refresh(obj)
    return obj


@router.put("/usuarios/{usr_id}", response_model=UsuarioOut)
def update_usuario(
    usr_id: int, body: UsuarioUpdate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)
):
    obj = db.get(Usuario, usr_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Usuário não encontrado")
    data = body.model_dump(exclude_unset=True)
    if "senha" in data:
        data["senha_hash"] = hash_password(data.pop("senha"))
    for k, v in data.items():
        setattr(obj, k, v)
    audit(db, user, "update", "usuario", obj.id, ip=_ip(request), diff={k: ("***" if k == "senha" else v) for k, v in data.items()})
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/usuarios/{usr_id}", status_code=204)
def delete_usuario(
    usr_id: int, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)
):
    obj = db.get(Usuario, usr_id)
    if obj is None or obj.deleted_at is not None:
        raise HTTPException(404, "Usuário não encontrado")
    if obj.id == user.id:
        raise HTTPException(400, "Você não pode excluir a si mesmo")
    obj.deleted_at = datetime.now(timezone.utc)
    audit(db, user, "delete", "usuario", obj.id, ip=_ip(request))
    db.commit()
