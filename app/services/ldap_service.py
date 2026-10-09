"""Autenticação via LDAP / Active Directory.

Fluxo (o recomendado para AD):

1. Bind com a **conta de serviço** (somente leitura).
2. Busca o usuário na Base DN usando `ldap_filtro_usuario`.
3. Faz um **segundo bind com o DN do usuário e a senha digitada** — é isso que
   valida a senha de verdade.
4. Confere se o usuário pertence ao **grupo de acesso** configurado
   (ex.: `YM_ESTOQUE_TI`). Suporta grupos **aninhados** (regra de correspondência
   do AD) e também correspondência por CN, para o admin poder digitar só o nome.

A senha do usuário nunca é armazenada em lugar nenhum.
"""
from __future__ import annotations

import ssl
from dataclasses import dataclass, field

from ldap3 import SUBTREE, Connection, Server, Tls
from ldap3.core.exceptions import LDAPException

from app.core.cripto import decifrar
from app.models.core import ConfiguracaoSistema

# Regra de correspondência do AD para grupos aninhados (LDAP_MATCHING_RULE_IN_CHAIN).
_MATCHING_RULE_CHAIN = "1.2.840.113556.1.4.1941"


@dataclass
class ResultadoLDAP:
    """Resultado de uma tentativa de autenticação LDAP."""

    ok: bool
    mensagem: str
    dn: str | None = None
    email: str | None = None
    nome: str | None = None
    login: str | None = None
    grupos: list[str] = field(default_factory=list)
    no_grupo_acesso: bool = False
    admin: bool = False


def _normalizar(valor: str | None) -> str:
    return (valor or "").strip().lower()


def _server(cfg: ConfiguracaoSistema) -> Server:
    tls = None
    if cfg.ldap_tls:
        validate = ssl.CERT_NONE if cfg.ldap_ignorar_certificado else ssl.CERT_REQUIRED
        tls = Tls(validate=validate)
    return Server(
        cfg.ldap_servidor,
        port=cfg.ldap_porta,
        use_ssl=bool(cfg.ldap_tls),
        tls=tls,
        connect_timeout=8,
    )


def _conectar(cfg: ConfiguracaoSistema) -> Connection:
    """Abre conexão e faz bind com a conta de serviço."""
    conn = Connection(
        _server(cfg),
        user=cfg.ldap_bind_dn,
        password=decifrar(cfg.ldap_bind_senha),
        auto_bind=False,
        receive_timeout=15,
    )
    return conn


def _descricao_erro(conn: Connection) -> str:
    resultado = getattr(conn, "result", None) or {}
    return resultado.get("message") or resultado.get("description") or "falha na conexão LDAP"


def testar_conexao(cfg: ConfiguracaoSistema) -> tuple[bool, str]:
    """Testa servidor + conta de serviço. Não valida senha de usuário."""
    if not cfg.ldap_servidor or not cfg.ldap_bind_dn:
        return False, "Informe o servidor e a conta de serviço."
    conn = None
    try:
        conn = _conectar(cfg)
        if not conn.bind():
            return False, f"Falha ao autenticar a conta de serviço: {_descricao_erro(conn)}"

        detalhe = ""
        if cfg.ldap_base_dn:
            if conn.search(cfg.ldap_base_dn, "(objectClass=*)", search_scope=SUBTREE, size_limit=1, attributes=[]):
                detalhe = " Base DN acessível."
            else:
                return False, f"Base DN inacessível: {_descricao_erro(conn)}"

        if cfg.ldap_grupo_acesso:
            dn_grupo = _resolver_dn_grupo(conn, cfg, cfg.ldap_grupo_acesso)
            if dn_grupo:
                detalhe += f" Grupo '{cfg.ldap_grupo_acesso}' encontrado."
            else:
                return False, f"Grupo de acesso '{cfg.ldap_grupo_acesso}' não encontrado na Base DN."

        return True, f"Conectado em {cfg.ldap_servidor}:{cfg.ldap_porta}.{detalhe}"
    except LDAPException as exc:
        return False, f"Erro de LDAP: {exc}"
    except OSError as exc:
        return False, f"Não foi possível conectar em {cfg.ldap_servidor}:{cfg.ldap_porta} ({exc})"
    finally:
        if conn is not None:
            try:
                conn.unbind()
            except Exception:  # noqa: BLE001 - encerramento best-effort
                pass


def _atributo(entrada, nome: str):
    try:
        valor = entrada[nome].value
    except (KeyError, LDAPException):
        return None
    if isinstance(valor, list):
        return valor[0] if valor else None
    return valor


def _atributo_lista(entrada, nome: str) -> list[str]:
    try:
        valor = entrada[nome].value
    except (KeyError, LDAPException):
        return []
    if valor is None:
        return []
    if isinstance(valor, list):
        return [str(v) for v in valor]
    return [str(valor)]


def _resolver_dn_grupo(conn: Connection, cfg: ConfiguracaoSistema, grupo: str) -> str | None:
    """Aceita tanto o DN completo quanto só o nome (CN) do grupo."""
    if "=" in grupo and "," in grupo:
        return grupo  # já parece um DN
    filtro = f"(&(objectClass=group)(cn={grupo}))"
    base = cfg.ldap_base_dn or ""
    if conn.search(base, filtro, search_scope=SUBTREE, attributes=["distinguishedName"], size_limit=1):
        if conn.entries:
            return str(conn.entries[0].entry_dn)
    return None


def _grupos_do_usuario(conn: Connection, cfg: ConfiguracaoSistema, entrada, dn_usuario: str) -> list[str]:
    """Grupos do usuário: `memberOf` (direto) + grupos aninhados, se habilitado."""
    grupos = set(_atributo_lista(entrada, "memberOf"))

    if cfg.ldap_grupos_aninhados and cfg.ldap_base_dn:
        # Busca todos os grupos que contêm o usuário, inclusive por herança.
        filtro = f"(&(objectClass=group)(member:{_MATCHING_RULE_CHAIN}:={dn_usuario}))"
        try:
            if conn.search(cfg.ldap_base_dn, filtro, search_scope=SUBTREE, attributes=["distinguishedName"]):
                grupos.update(str(e.entry_dn) for e in conn.entries)
        except LDAPException:
            # Servidor sem suporte à regra do AD (ex.: OpenLDAP) — segue com memberOf.
            pass
    return sorted(grupos)


def _grupo_confere(grupos: list[str], alvo: str) -> bool:
    """Compara por DN ou pelo CN/nome curto."""
    alvo_norm = _normalizar(alvo)
    for dn in grupos:
        if _normalizar(dn) == alvo_norm:
            return True
        # Compara também o CN (primeiro componente do DN).
        primeiro = dn.split(",")[0]
        if "=" in primeiro and _normalizar(primeiro.split("=", 1)[1]) == alvo_norm:
            return True
    return False


def autenticar(cfg: ConfiguracaoSistema, usuario: str, senha: str) -> ResultadoLDAP:
    """Autentica um usuário no AD e verifica o grupo de acesso."""
    if not cfg.ldap_ativo:
        return ResultadoLDAP(False, "Autenticação LDAP está desativada.")
    if not cfg.ldap_servidor or not cfg.ldap_base_dn:
        return ResultadoLDAP(False, "Servidor/Base DN do LDAP não configurados.")
    if not usuario or not senha:
        return ResultadoLDAP(False, "Informe usuário e senha.")

    conn = None
    try:
        conn = _conectar(cfg)
        if not conn.bind():
            return ResultadoLDAP(False, f"Falha na conta de serviço: {_descricao_erro(conn)}")

        # 1) Localiza o usuário.
        filtro = cfg.ldap_filtro_usuario.replace("{usuario}", usuario)
        atributos = ["distinguishedName", "sAMAccountName", "userPrincipalName", "mail", "displayName", "cn", "memberOf"]
        if not conn.search(cfg.ldap_base_dn, filtro, search_scope=SUBTREE, attributes=atributos, size_limit=2):
            return ResultadoLDAP(False, "Usuário não encontrado no diretório.")
        if not conn.entries:
            return ResultadoLDAP(False, "Usuário não encontrado no diretório.")

        entrada = conn.entries[0]
        dn_usuario = str(entrada.entry_dn)
        login = _atributo(entrada, "sAMAccountName") or usuario
        nome = _atributo(entrada, "displayName") or _atributo(entrada, "cn") or login
        email = _atributo(entrada, "mail") or _atributo(entrada, "userPrincipalName") or f"{login}@local"

        # 2) Grupos (antes de reusar a conexão para o bind do usuário).
        grupos = _grupos_do_usuario(conn, cfg, entrada, dn_usuario)
        conn.unbind()
        conn = None

        # 3) Valida a senha com um bind usando o DN do próprio usuário.
        conn_user = Connection(_server(cfg), user=dn_usuario, password=senha, auto_bind=False, receive_timeout=15)
        try:
            if not conn_user.bind():
                return ResultadoLDAP(False, "Usuário ou senha inválidos.")
        finally:
            try:
                conn_user.unbind()
            except Exception:  # noqa: BLE001
                pass

        # 4) O AD só confirma QUEM é a pessoa. Quem pode entrar, e com qual
        #    perfil, é decidido no cadastro do sistema — não por grupo do AD.
        return ResultadoLDAP(
            True, "Autenticado.", dn=dn_usuario, email=email, nome=nome, login=login,
            grupos=grupos, no_grupo_acesso=True, admin=False,
        )
    except LDAPException as exc:
        return ResultadoLDAP(False, f"Erro de LDAP: {exc}")
    except OSError as exc:
        return ResultadoLDAP(False, f"Não foi possível conectar ao servidor LDAP ({exc})")
    finally:
        if conn is not None:
            try:
                conn.unbind()
            except Exception:  # noqa: BLE001
                pass


def buscar_usuario(cfg: ConfiguracaoSistema, login: str) -> tuple[bool, str, dict]:
    """Consulta os dados de uma pessoa no AD, **sem validar senha**.

    Usado na tela de cadastro: o administrador digita o usuário de rede e o
    sistema preenche nome e e-mail. Não autentica ninguém — apenas lê o
    diretório com a conta de serviço.

    Devolve `(ok, mensagem, dados)`.
    """
    if not cfg.ldap_servidor:
        return False, "O servidor do AD não está configurado.", {}
    if not cfg.ldap_base_dn:
        return False, "A Base DN não está configurada.", {}
    if not login or not login.strip():
        return False, "Informe o usuário de rede.", {}

    termo = login.strip()
    conn = None
    try:
        conn = _conectar(cfg)
        if conn is None or not conn.bind():
            return False, f"Falha na conta de serviço: {_descricao_erro(conn)}", {}

        filtro = cfg.ldap_filtro_usuario.replace("{usuario}", termo)
        atributos = [
            "distinguishedName", "sAMAccountName", "userPrincipalName", "mail",
            "displayName", "cn", "department", "title", "physicalDeliveryOfficeName",
        ]
        if not conn.search(cfg.ldap_base_dn, filtro, search_scope=SUBTREE,
                           attributes=atributos, size_limit=2):
            return False, f"'{termo}' não foi encontrado no diretório.", {}
        if not conn.entries:
            return False, f"'{termo}' não foi encontrado no diretório.", {}

        entrada = conn.entries[0]
        nome_login = _atributo(entrada, "sAMAccountName") or termo
        return True, "Encontrado.", {
            "login": nome_login,
            "nome": _atributo(entrada, "displayName") or _atributo(entrada, "cn") or nome_login,
            "email": _atributo(entrada, "mail") or _atributo(entrada, "userPrincipalName"),
            "departamento": _atributo(entrada, "department"),
            "cargo": _atributo(entrada, "title"),
            "local": _atributo(entrada, "physicalDeliveryOfficeName"),
            "dn": str(entrada.entry_dn),
        }
    except LDAPException as exc:
        return False, f"Erro de LDAP: {exc}", {}
    except OSError as exc:
        return False, f"Não foi possível conectar ao servidor LDAP ({exc})", {}
    finally:
        if conn is not None:
            try:
                conn.unbind()
            except Exception:  # noqa: BLE001
                pass
