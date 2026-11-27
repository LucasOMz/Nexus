"""Configuração do sistema (Administração → Autenticação AD/LDAP)."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from ldap3.core.exceptions import LDAPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.cripto import cifrar, decifrar, esta_cifrado
from app.core.deps import require_admin
from app.database import get_db
from app.models.core import ConfiguracaoSistema, Usuario
from app.schemas.auth import PoliticaSessao
from app.services import sessoes
from app.services.audit_service import audit
from app.services.config_service import obter_config
from app.services.ia_externa import DestinoExterno, ProvedorExterno, testar_destino
from app.services.ldap_service import autenticar, testar_conexao, validar_transporte_ldap
from app.services.ollama import config_efetiva, listar_modelos, normalizar_url
from app.services.retencao_chat import limpar_expirados

router = APIRouter(prefix="/admin/config", tags=["configuracao"])

# Campos que o frontend pode enviar.
# Campos simples (nao-LDAP) que o PUT grava direto.
_CAMPOS_SIMPLES = ("intervalo_software_horas",)

_CAMPOS_LOGRADOS = (
    "ldap_ativo", "ldap_servidor", "ldap_porta", "ldap_tls", "ldap_permitir_sem_tls", "ldap_base_dn",
    "ldap_bind_dn", "ldap_filtro_usuario", "ldap_grupo_acesso", "ldap_grupo_admin",
    "ldap_provisionar", "ldap_grupos_aninhados", "ldap_ignorar_certificado", "ldap_admin_por_cargo",
)
_CAMPOS_TRANSPORTE_LDAP = (
    "ldap_ativo", "ldap_servidor", "ldap_porta", "ldap_tls", "ldap_permitir_sem_tls", "ldap_ignorar_certificado",
)


class ConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ldap_ativo: bool | None = None
    ldap_servidor: str | None = None
    ldap_porta: int = Field(default=636, ge=1, le=65535)
    ldap_tls: bool = True
    ldap_permitir_sem_tls: bool = False
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
    def limpar_endereco_ldap(cls, valor: str | None) -> str | None:
        return (valor or "").strip() or None


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


class PoliticaChat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chat_ativo: bool
    historico_dias: int | None = Field(ge=1, le=3650)


@router.put("/politica-sessao", response_model=PoliticaSessao)
def salvar_politica_sessao(
    body: PoliticaSessao, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
) -> PoliticaSessao:
    cfg = obter_config(db)
    db.refresh(cfg, attribute_names=["sessao_inatividade_minutos"], with_for_update=True)
    anterior = cfg.sessao_inatividade_minutos or sessoes.INATIVIDADE_PADRAO_MINUTOS
    if anterior != body.inatividade_minutos:
        # Uma ampliação do limite não pode reativar tokens já vencidos.
        sessoes.revogar_inativas(db, min(anterior, body.inatividade_minutos))
        cfg.sessao_inatividade_minutos = body.inatividade_minutos
        audit(db, user, "update", "configuracao", cfg.id, ip=request.client.host if request.client else None,
              diff={"sessao_inatividade_minutos": body.inatividade_minutos})
        db.commit()
    return body


@router.get("/ollama/politica", response_model=PoliticaChat)
def ler_politica_chat(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)) -> PoliticaChat:
    config = config_efetiva(db)
    return PoliticaChat(chat_ativo=config.chat_ativo, historico_dias=config.historico_dias)


@router.put("/ollama/politica", response_model=PoliticaChat)
def salvar_politica_chat(
    body: PoliticaChat, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
) -> PoliticaChat:
    cfg = obter_config(db)
    cfg.ollama_chat_ativo = body.chat_ativo
    cfg.ollama_historico_dias = body.historico_dias
    db.flush()
    removidos = limpar_expirados(db, body.historico_dias)
    audit(db, user, "update", "configuracao", cfg.id,
          ip=request.client.host if request.client else None,
          diff={"ollama_chat_ativo": body.chat_ativo, "ollama_historico_dias": body.historico_dias,
                "mensagens_expiradas_removidas": removidos})
    db.commit()
    return body


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


class ConfigIAExterna(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provedor: ProvedorExterno
    modelo: str = Field(min_length=1, max_length=250)
    token: SecretStr | None = None


class ConfigAgenteIA(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provedor: Literal["ollama"]


def _estado_agente_ia(cfg: ConfiguracaoSistema | None) -> dict:
    return {
        "provedor": cfg.ia_provedor_externo if cfg and cfg.ia_externa_ativa else "ollama",
        "provedor_externo": cfg.ia_provedor_externo if cfg else None,
        "modelo_externo": cfg.ia_modelo_externo if cfg else None,
        "token_salvo": bool(cfg and decifrar(cfg.ia_token_externo)),
    }


@router.get("/agente-ia")
def ler_agente_ia(db: Session = Depends(get_db), _: Usuario = Depends(require_admin)) -> dict:
    return _estado_agente_ia(db.get(ConfiguracaoSistema, 1))


@router.put("/agente-ia")
def selecionar_ollama(
    body: ConfigAgenteIA, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
) -> dict:
    cfg = obter_config(db)
    if cfg.ia_externa_ativa:
        cfg.ia_externa_ativa = False
        audit(db, user, "update", "configuracao", cfg.id, ip=request.client.host if request.client else None,
              diff={"provedor_ia": body.provedor})
        db.commit()
    return _estado_agente_ia(cfg)


def _destino_para_teste(db: Session, body: ConfigIAExterna) -> DestinoExterno:
    token = body.token.get_secret_value().strip() if body.token else ""
    cfg = db.get(ConfiguracaoSistema, 1)
    if not token and cfg and cfg.ia_provedor_externo == body.provedor:
        token = decifrar(cfg.ia_token_externo) or ""
    if not token or len(token) > 512 or any(not 33 <= ord(c) <= 126 for c in token):
        raise HTTPException(422, "Informe uma chave de API válida do provedor selecionado.")
    db.rollback()
    return DestinoExterno(body.provedor, body.modelo, token)


@router.post("/agente-ia/externa/testar")
def testar_ia_externa(body: ConfigIAExterna, db: Session = Depends(get_db), _: Usuario = Depends(require_admin)) -> dict:
    testar_destino(_destino_para_teste(db, body))
    return {"ok": True}


@router.put("/agente-ia/externa")
def salvar_ia_externa(
    body: ConfigIAExterna, request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
) -> dict:
    destino = _destino_para_teste(db, body)
    testar_destino(destino)
    cfg = obter_config(db)
    cfg.ia_provedor_externo = destino.provedor
    cfg.ia_modelo_externo = destino.modelo
    cfg.ia_token_externo = cifrar(destino.token)
    cfg.ia_externa_ativa = True
    audit(db, user, "update", "configuracao", cfg.id, ip=request.client.host if request.client else None,
          diff={"provedor_ia": destino.provedor, "modelo_ia": destino.modelo})
    db.commit()
    return _estado_agente_ia(cfg)


@router.delete("/agente-ia/externa")
def remover_ia_externa(
    request: Request, db: Session = Depends(get_db), user: Usuario = Depends(require_admin),
) -> dict:
    cfg = obter_config(db)
    cfg.ia_externa_ativa = False
    cfg.ia_provedor_externo = cfg.ia_modelo_externo = cfg.ia_token_externo = None
    audit(db, user, "update", "configuracao", cfg.id, ip=request.client.host if request.client else None,
          diff={"provedor_ia": "ollama", "chave_externa_removida": True})
    db.commit()
    return _estado_agente_ia(cfg)


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
    if any(campo in dados for campo in _CAMPOS_TRANSPORTE_LDAP) and dados != {"ldap_ativo": False}:
        db.refresh(cfg, attribute_names=_CAMPOS_TRANSPORTE_LDAP, with_for_update=True)
        tls = dados.get("ldap_tls", cfg.ldap_tls)
        if tls and ("ldap_tls" in dados or "ldap_permitir_sem_tls" in dados):
            dados["ldap_permitir_sem_tls"] = False
        try:
            validar_transporte_ldap(
                dados.get("ldap_servidor", cfg.ldap_servidor),
                tls,
                dados.get("ldap_permitir_sem_tls", cfg.ldap_permitir_sem_tls),
                dados.get("ldap_ignorar_certificado", cfg.ldap_ignorar_certificado),
            )
        except LDAPException as exc:
            raise HTTPException(422, str(exc)) from exc
        if tls != cfg.ldap_tls and cfg.ldap_porta == (636 if cfg.ldap_tls else 389):
            dados.setdefault("ldap_porta", 636 if tls else 389)

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
        "permitir_sem_tls": cfg.ldap_permitir_sem_tls,
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
