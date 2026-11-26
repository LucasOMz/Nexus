"""Configuração do sistema (Administração → Autenticação AD/LDAP)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.cripto import cifrar, decifrar, esta_cifrado
from app.core.deps import require_admin
from app.database import get_db
from app.models.core import Usuario
from app.services.audit_service import audit
from app.services.config_service import obter_config
from app.services.ldap_service import autenticar, testar_conexao
from app.services.ollama import config_efetiva, listar_modelos, normalizar_url

router = APIRouter(prefix="/admin/config", tags=["configuracao"])

# Campos que o frontend pode enviar.
# Campos simples (nao-LDAP) que o PUT grava direto.
_CAMPOS_SIMPLES = ("intervalo_software_horas",)

_CAMPOS_LOGRADOS = (
    "ldap_ativo", "ldap_servidor", "ldap_porta", "ldap_tls", "ldap_base_dn",
    "ldap_bind_dn", "ldap_filtro_usuario", "ldap_grupo_acesso", "ldap_grupo_admin",
    "ldap_provisionar", "ldap_grupos_aninhados", "ldap_ignorar_certificado", "ldap_admin_por_cargo",
)


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ldap_ativo: bool | None = None
    ldap_servidor: str | None = None
    ldap_porta: int = Field(default=636, ge=1, le=65535)
    ldap_tls: bool = True
    ldap_base_dn: str | None = None
    ldap_bind_dn: str | None = None
    # Se enviado, substitui a senha guardada. Vazio/NULL = mantém a atual.
    ldap_bind_senha: str | None = None
    ldap_filtro_usuario: str | None = None
    ldap_grupo_acesso: str | None = None
    ldap_grupo_admin: str | None = None
    ldap_provisionar: bool | None = None
    ldap_grupos_aninhados: bool | None = None
    ldap_ignorar_certificado: bool = False
    ldap_admin_por_cargo: bool | None = None
    # De quantas em quantas horas o agente envia a lista de programas.
    # 1 a 168 (uma semana). O agente consulta a cada ciclo.
    intervalo_software_horas: int | None = Field(default=None, ge=1, le=168)

    @field_validator("ldap_servidor")
    @classmethod
    def validar_endereco_ldaps(cls, valor: str | None) -> str | None:
        if valor:
            valor = valor.strip()
            if "://" in valor and not valor.lower().startswith("ldaps://"):
                raise ValueError("Informe o nome DNS do servidor ou use ldaps://.")
        return valor


class TesteLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usuario: str
    senha: str


class BuscaAD(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usuario: str


class EnderecoOllama(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    url: str = Field(min_length=1, max_length=500)


class SalvarOllama(EnderecoOllama):
    modelo: str = Field(min_length=1, max_length=250)


@router.get("/ollama")
def ler_ollama(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)) -> dict:
    config = config_efetiva(db)
    return {"url": config.url, "modelo": config.modelo, "origem": config.origem}


@router.post("/ollama/testar")
def testar_ollama(body: EnderecoOllama, db: Session = Depends(get_db), _: Usuario = Depends(require_admin)) -> dict:
    db.rollback()
    return {"modelos": listar_modelos(body.url)}


@router.put("/ollama")
def salvar_ollama(
    body: SalvarOllama, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
) -> dict:
    url = str(normalizar_url(body.url)).rstrip("/")
    db.rollback()
    if body.modelo not in listar_modelos(url):
        raise HTTPException(422, "O modelo selecionado não está disponível nesse servidor Ollama.")

    cfg = obter_config(db)
    cfg.ollama_url = url
    cfg.ollama_modelo = body.modelo
    audit(db, user, "update", "configuracao", cfg.id,
          ip=request.client.host if request.client else None,
          diff={"ollama_url": url, "ollama_modelo": body.modelo})
    db.commit()
    return {"url": url, "modelo": body.modelo, "origem": "administracao"}


@router.post("/buscar-ad")
def buscar_ad(
    body: BuscaAD,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
) -> dict:
    """Busca os dados de uma pessoa no AD pelo usuário de logon.

    Serve à tela de cadastro: o administrador digita `joao.silva` e o sistema
    devolve o nome completo e o e-mail. **Não autentica ninguém** — apenas lê o
    diretório com a conta de serviço. Quem libera o acesso continua sendo o
    administrador, ao salvar o cadastro.
    """
    from app.services.ldap_service import buscar_usuario

    cfg = obter_config(db)
    if not cfg.ldap_servidor:
        return {"ok": False, "mensagem": "O servidor do AD não está configurado "
                                         "(Administração → Autenticação).", "dados": {}}

    ok, mensagem, dados = buscar_usuario(cfg, body.usuario)
    if not ok:
        return {"ok": False, "mensagem": mensagem, "dados": {}}

    # Ajuda o administrador: avisa se essa pessoa já tem cadastro aqui.
    ja_existe = None
    if dados.get("login"):
        u = (
            db.query(Usuario)
            .filter(
                func.lower(Usuario.login_ad) == dados["login"].lower(),
                Usuario.deleted_at.is_(None),
            )
            .first()
        )
        if u is not None:
            ja_existe = {"id": u.id, "nome": u.nome, "papel": u.papel.value, "ativo": u.ativo}

    return {"ok": True, "mensagem": mensagem, "dados": dados, "ja_cadastrado": ja_existe}


def _serializar(cfg) -> dict[str, Any]:
    dados = {campo: getattr(cfg, campo) for campo in _CAMPOS_LOGRADOS}
    # Quantas horas entre coletas de software. O agente lê isto na resposta
    # do inventário; a tela mostra para poder editar.
    dados["intervalo_software_horas"] = getattr(cfg, "intervalo_software_horas", 1) or 1
    dados["ldap_bind_senha_definida"] = bool(cfg.ldap_bind_senha)
    dados["ldap_bind_senha_cifrada"] = esta_cifrado(cfg.ldap_bind_senha)
    dados["ldap_ultimo_teste_ok"] = cfg.ldap_ultimo_teste_ok
    dados["ldap_ultimo_teste_msg"] = cfg.ldap_ultimo_teste_msg
    # A senha nunca é devolvida.
    return dados


@router.get("")
def ler_config(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)) -> dict:
    return _serializar(obter_config(db))


@router.put("")
def salvar_config(
    body: ConfigUpdate, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)
) -> dict:
    cfg = obter_config(db)
    dados = body.model_dump(exclude_unset=True)
    if not body.ldap_tls or body.ldap_ignorar_certificado:
        raise HTTPException(422, "O Active Directory exige LDAPS com validação do certificado.")

    if "ldap_bind_senha" in dados:
        senha = dados.pop("ldap_bind_senha")
        # Vazio = mantém a senha atual (o frontend nunca recebe o valor real).
        if senha:
            cfg.ldap_bind_senha = cifrar(senha)

    for chave, valor in dados.items():
        if hasattr(cfg, chave):
            setattr(cfg, chave, valor)

    audit(db, user, "update", "configuracao", cfg.id,
          ip=request.client.host if request.client else None,
          diff={k: ("***" if "senha" in k else v) for k, v in dados.items()})
    db.commit()
    db.refresh(cfg)
    return _serializar(cfg)


@router.post("/testar-ldap")
def testar(request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)) -> dict:
    """Testa servidor + conta de serviço + existência do grupo de acesso."""
    from datetime import datetime, timezone

    cfg = obter_config(db)
    ok, mensagem = testar_conexao(cfg)
    cfg.ldap_ultimo_teste_ok = datetime.now(timezone.utc).isoformat(timespec="seconds") if ok else None
    cfg.ldap_ultimo_teste_msg = mensagem
    audit(db, user, "testar_ldap", "configuracao", cfg.id,
          ip=request.client.host if request.client else None, diff={"ok": ok})
    db.commit()
    return {"ok": ok, "mensagem": mensagem}


@router.post("/testar-login")
def testar_login(
    body: TesteLogin, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin)
) -> dict:
    """Testa as credenciais de um usuário e a participação no grupo de acesso."""
    cfg = obter_config(db)
    resultado = autenticar(cfg, body.usuario, body.senha)
    audit(db, user, "testar_login_ldap", "configuracao", cfg.id,
          ip=request.client.host if request.client else None,
          diff={"usuario": body.usuario, "ok": resultado.ok, "grupo": cfg.ldap_grupo_acesso})
    db.commit()
    return {
        "ok": resultado.ok,
        "mensagem": resultado.mensagem,
        "nome": resultado.nome,
        "email": resultado.email,
        "login": resultado.login,
        "no_grupo_acesso": resultado.no_grupo_acesso,
        "grupo_configurado": cfg.ldap_grupo_acesso,
        "admin": resultado.admin,
        "grupos": resultado.grupos[:50],
    }


@router.get("/diagnostico")
def diagnostico(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)) -> dict:
    """Informações úteis para conferir a configuração (sem expor segredos)."""
    cfg = obter_config(db)
    from app.config import settings

    return {
        "ldap_ativo": cfg.ldap_ativo,
        "intervalo_software_horas": getattr(cfg, "intervalo_software_horas", 1) or 1,
        "servidor": cfg.ldap_servidor,
        "porta": cfg.ldap_porta,
        "tls": cfg.ldap_tls,
        "base_dn": cfg.ldap_base_dn,
        "conta_servico": cfg.ldap_bind_dn,
        "senha_servico_guardada": bool(cfg.ldap_bind_senha),
        "senha_servico_decifravel": bool(decifrar(cfg.ldap_bind_senha)) if cfg.ldap_bind_senha else False,
        "filtro": cfg.ldap_filtro_usuario,
        "grupo_acesso": cfg.ldap_grupo_acesso,
        "grupo_admin": cfg.ldap_grupo_admin,
        "provisionar": cfg.ldap_provisionar,
        "grupos_aninhados": cfg.ldap_grupos_aninhados,
        "ignorar_certificado": cfg.ldap_ignorar_certificado,
        "ca_privada_configurada": bool(settings.ldap_ca_file),
        "admin_local": settings.seed_admin_email,
        "qr_exigir_assinatura": settings.qr_exigir_assinatura,
        "segredos_qr_aceitos": len(settings.segredos_qr),
        "pasta_backups": settings.backup_path,
    }
