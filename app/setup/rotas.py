"""Assistente de configuração inicial.

Roda **apenas quando o sistema não está instalado** (não existe `.instalado`).
Depois disso, estas rotas respondem 404 — o assistente não pode ser reaberto,
senão quem alcançasse o endereço poderia apontar o sistema para um banco
próprio e assumir o controle.

Ponto importante do desenho: **o assistente não usa o banco do sistema.** Ele
abre uma conexão própria e temporária com o banco escolhido, cria a estrutura
lá, insere o administrador e só então grava o `.env`. A troca passa a valer no
próximo início — assim nunca existe um instante em que o sistema está apontando
para um banco meio configurado.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.setup import estado

log = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])

# Credenciais padrão que o sistema traz de fábrica. Servem de porteiro do
# assistente: quem instala conhece a documentação; quem apenas alcançou o
# endereço, não.
ROOT_EMAIL = "admin@empresa.com"
ROOT_SENHA = "admin123"

BANCOS = {
    "sqlite": {
        "rotulo": "SQLite (arquivo local)",
        "driver": None,
        "ajuda": "Zero configuração. Bom para um único servidor. O arquivo fica na pasta do sistema.",
    },
    "postgresql": {
        "rotulo": "PostgreSQL",
        "driver": "psycopg",
        "ajuda": "Recomendado para uso com vários usuários simultâneos.",
    },
    "mysql": {
        "rotulo": "MySQL / MariaDB",
        "driver": "pymysql",
        "ajuda": "Driver já instalado. Serve para MySQL 5.7+ e MariaDB 10.3+.",
    },
    "mssql": {
        "rotulo": "SQL Server",
        "driver": "pyodbc",
        "ajuda": "Driver instalado. Precisa também do ODBC Driver da Microsoft no sistema.",
    },
}

PORTAS_PADRAO = {"postgresql": 5432, "mysql": 3306, "mssql": 1433}


def _exigir_setup_aberto() -> None:
    if estado.instalado():
        raise HTTPException(404, "O sistema já está instalado.")


# ---------------------------------------------------------------------------
# Modelos de entrada
# ---------------------------------------------------------------------------
class BancoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo: str = "sqlite"
    # SQLite
    arquivo: str | None = None
    # Servidores
    servidor: str | None = None
    porta: int | None = None
    banco: str | None = None
    usuario: str | None = None
    senha: str | None = None
    # Cria a estrutura no destino (desligue para usar um banco já existente)
    criar_estrutura: bool = True


class AdminIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=2, max_length=160)
    email: str = Field(min_length=5, max_length=200)
    senha: str = Field(min_length=8, max_length=128)


class EmpresaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=2, max_length=160)
    rodape: str | None = Field(default=None, max_length=200)


class PlantaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(min_length=2, max_length=160)
    sigla: str = Field(min_length=2, max_length=20)


class ADIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ativo: bool = False
    servidor: str | None = None
    porta: int = 636
    base_dn: str | None = None
    conta_servico: str | None = None
    senha_servico: str | None = None
    filtro_usuario: str = "(sAMAccountName={usuario})"


class OCSIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ativo: bool = False
    servidor: str | None = None
    token: str | None = None


class AplicarIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_email: str
    root_senha: str
    empresa: EmpresaIn
    banco: BancoIn
    admin: AdminIn
    planta: PlantaIn
    ad: ADIn | None = None
    ocs: OCSIn | None = None
    logo: str | None = None
    favicon: str | None = None


# ---------------------------------------------------------------------------
# Montagem da URL de conexão
# ---------------------------------------------------------------------------
def montar_url(b: BancoIn) -> str:
    """Traduz os campos da tela na URL que o SQLAlchemy entende."""
    if b.tipo == "sqlite":
        caminho = (b.arquivo or "./estoque.db").strip()
        if "://" in caminho:
            raise ValueError("Para SQLite informe um caminho de arquivo, não um endereço.")
        return f"sqlite:///{caminho}"

    if b.tipo not in BANCOS:
        raise ValueError(f"Tipo de banco desconhecido: {b.tipo}")

    faltando = [c for c, v in (("servidor", b.servidor), ("banco", b.banco),
                               ("usuario", b.usuario)) if not (v or "").strip()]
    if faltando:
        raise ValueError(f"Preencha: {', '.join(faltando)}.")

    driver = BANCOS[b.tipo]["driver"]
    from urllib.parse import quote_plus

    usuario = quote_plus(b.usuario or "")
    senha = quote_plus(b.senha or "")
    porta = b.porta or PORTAS_PADRAO.get(b.tipo, "")
    credencial = f"{usuario}:{senha}" if senha else usuario
    url = f"{b.tipo}+{driver}://{credencial}@{b.servidor}:{porta}/{b.banco}"

    # O SQL Server não funciona sem dizer QUAL driver ODBC usar. Sem isso, a
    # conexão falha com "driver não especificado" — um erro que não ajuda em
    # nada. Preferimos o mais novo disponível na máquina.
    if b.tipo == "mssql":
        url += f"?driver={quote_plus(_driver_odbc())}&TrustServerCertificate=yes"
    return url


def _driver_odbc() -> str:
    """Nome do driver ODBC do SQL Server instalado nesta máquina.

    A Microsoft recomenda o 18; máquinas mais antigas têm o 17 ou apenas o
    "SQL Server", que já vem no Windows.
    """
    try:
        import pyodbc

        disponiveis = pyodbc.drivers()
    except Exception:  # noqa: BLE001 — sem pyodbc a conexão falha depois, com mensagem própria
        return "ODBC Driver 18 for SQL Server"

    for preferido in ("ODBC Driver 18 for SQL Server",
                      "ODBC Driver 17 for SQL Server",
                      "SQL Server"):
        if preferido in disponiveis:
            return preferido
    return disponiveis[0] if disponiveis else "ODBC Driver 18 for SQL Server"


def _conectar(b: BancoIn):
    """Abre uma conexão temporária. Devolve o motor — quem chamou o descarta."""
    # `montar_url` valida os campos e levanta ValueError; aqui ele vira uma
    # resposta 400 com a explicação, em vez de um erro interno.
    try:
        url = montar_url(b)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    argumentos = {"check_same_thread": False} if url.startswith("sqlite") else {}
    try:
        motor = create_engine(url, connect_args=argumentos, pool_pre_ping=True)
        with motor.connect():
            pass  # força a conexão de verdade: create_engine sozinho não conecta
    except ModuleNotFoundError as e:
        driver = BANCOS.get(b.tipo, {}).get("driver")
        raise HTTPException(
            400,
            f"O driver do {BANCOS.get(b.tipo, {}).get('rotulo', b.tipo)} não está instalado "
            f"(falta o módulo '{e.name}'). Instale com: pip install {driver}",
        ) from e
    except Exception as e:  # noqa: BLE001 — qualquer falha vira mensagem para a tela
        raise HTTPException(400, f"Não foi possível conectar: {e}") from e
    return motor


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
@router.get("/estado")
def situacao() -> dict:
    """Se o sistema está instalado e quais bancos estão disponíveis."""
    disponiveis = []
    for chave, info in BANCOS.items():
        driver = info["driver"]
        pronto = True
        if driver:
            try:
                __import__(driver)
            except ImportError:
                pronto = False
        disponiveis.append({
            "valor": chave, "rotulo": info["rotulo"],
            "ajuda": info["ajuda"], "driver_instalado": pronto,
            "porta_padrao": PORTAS_PADRAO.get(chave),
        })

    return {
        "instalado": estado.instalado(),
        "bancos": disponiveis,
        "root_email": ROOT_EMAIL,
        "pasta": str(estado.RAIZ),
    }


@router.post("/validar-root")
def validar_root(email: str = Form(...), senha: str = Form(...)) -> dict:
    """Porteiro do assistente: confere as credenciais padrão do sistema."""
    _exigir_setup_aberto()
    if email.strip().lower() != ROOT_EMAIL or senha != ROOT_SENHA:
        raise HTTPException(401, "Credenciais padrão incorretas. Consulte a documentação de instalação.")
    return {"ok": True, "mensagem": "Acesso liberado."}


@router.post("/testar-banco")
def testar_banco(b: BancoIn) -> dict:
    """Testa a conexão com o banco escolhido, **sem alterar nada**."""
    _exigir_setup_aberto()
    motor = _conectar(b)
    try:
        nomes = inspect(motor).get_table_names()
        with Session(motor) as s:
            if b.tipo == "sqlite":
                versao = s.execute(text("SELECT sqlite_version()")).scalar()
                rotulo = f"SQLite {versao}"
            elif b.tipo == "postgresql":
                versao = s.execute(text("SHOW server_version")).scalar()
                rotulo = f"PostgreSQL {versao}"
            else:
                rotulo = str(s.execute(text("SELECT version()")).scalar())[:80]

        ja_tem = [n for n in nomes if n in ("usuarios", "ativos", "plantas")]
        return {
            "ok": True,
            "servidor": rotulo,
            "tabelas_encontradas": len(nomes),
            "ja_configurado": bool(ja_tem),
            "mensagem": (
                f"Conectado. {rotulo}. "
                + (f"Este banco JÁ tem estrutura do sistema ({len(nomes)} tabelas)."
                   if ja_tem else "Banco vazio — pronto para receber o sistema.")
            ),
        }
    finally:
        motor.dispose()


@router.post("/testar-ad")
def testar_ad(ad: ADIn) -> dict:
    """Testa a conexão com o Active Directory, sem gravar nada."""
    _exigir_setup_aberto()
    if not ad.servidor or not ad.base_dn or not ad.conta_servico:
        raise HTTPException(400, "Informe servidor, Base DN e conta de serviço.")

    from types import SimpleNamespace

    from app.services.ldap_service import testar_conexao

    cfg = SimpleNamespace(
        ldap_servidor=ad.servidor, ldap_porta=ad.porta, ldap_tls=ad.porta == 636,
        ldap_base_dn=ad.base_dn, ldap_bind_dn=ad.conta_servico, ldap_bind_senha=ad.senha_servico,
        ldap_filtro_usuario=ad.filtro_usuario, ldap_grupo_acesso=None, ldap_grupos_aninhados=False,
        ldap_ignorar_certificado=False,
    )
    ok, mensagem = testar_conexao(cfg)
    return {"ok": ok, "mensagem": mensagem}


@router.post("/testar-ocs")
def testar_ocs(ocs: OCSIn) -> dict:
    """Testa a conexão com o OCS Inventory, sem gravar nada."""
    _exigir_setup_aberto()
    if not ocs.servidor or not ocs.token:
        raise HTTPException(400, "Informe o endereço e o token do OCS.")

    from types import SimpleNamespace

    from app.core.cripto import cifrar
    from app.services import ocs_service

    # O serviço espera o token já cifrado (é assim que ele fica no banco).
    cfg = SimpleNamespace(
        servidor=ocs.servidor, token=cifrar(ocs.token), verificar_ssl=True, timeout_s=20,
    )
    ok, mensagem = ocs_service.testar_conexao(cfg)
    return {"ok": ok, "mensagem": mensagem}


@router.post("/arquivo-marca")
async def enviar_marca(
    tipo: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    """Recebe o logo ou o favicon da empresa."""
    _exigir_setup_aberto()
    if tipo not in ("logo", "favicon"):
        raise HTTPException(400, "Tipo inválido.")

    permitidos = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/svg+xml",
                  "image/x-icon", "image/vnd.microsoft.icon"}
    if file.content_type not in permitidos:
        raise HTTPException(400, "Envie uma imagem (PNG, JPG, WEBP, GIF, SVG ou ICO).")

    conteudo = await file.read()
    if len(conteudo) > 2 * 1024 * 1024:
        raise HTTPException(400, "A imagem é grande demais (limite de 2 MB).")
    if not conteudo:
        raise HTTPException(400, "O arquivo está vazio.")

    relativo = estado.salvar_arquivo_marca(file.filename or "imagem.png", conteudo)
    return {"ok": True, "caminho": relativo}


@router.get("/marca/{arquivo}")
def ver_marca(arquivo: str):
    """Serve logo/favicon enviados — precisa funcionar antes de instalar."""
    caminho = estado.caminho_marca(arquivo)
    if caminho is None:
        raise HTTPException(404, "Arquivo não encontrado.")
    return FileResponse(caminho)


@router.post("/aplicar")
def aplicar(body: AplicarIn) -> dict:
    """Executa o setup: cria a estrutura, o administrador e grava o `.env`.

    **Nada do sistema atual é usado aqui.** A conexão com o banco escolhido é
    própria e temporária; a troca vale no próximo início.
    """
    _exigir_setup_aberto()

    if body.root_email.strip().lower() != ROOT_EMAIL or body.root_senha != ROOT_SENHA:
        raise HTTPException(401, "Sessão do assistente inválida. Recarregue a página.")
    if body.banco.tipo == "sqlite" and body.logo and not estado.caminho_marca(body.logo):
        raise HTTPException(400, "O logo enviado não foi encontrado.")

    passos: list[str] = []
    motor = _conectar(body.banco)
    avisos: list[str] = []

    try:
        # --- 1. Estrutura -------------------------------------------------
        from app.models import Base

        if body.banco.criar_estrutura:
            existentes = set(inspect(motor).get_table_names())
            Base.metadata.create_all(motor)
            novas = len(set(inspect(motor).get_table_names()) - existentes)
            passos.append(f"Estrutura criada ({novas} tabela(s)).")
        else:
            passos.append("Estrutura existente mantida.")

        # --- 2. Dados iniciais --------------------------------------------
        from app.core.cripto import cifrar
        from app.core.security import hash_password
        from app.models.core import ConfiguracaoSistema, Planta, Usuario
        from app.models.ocs import ConfiguracaoOCS

        with Session(motor) as s:
            if s.query(Usuario).filter(Usuario.email == body.admin.email).first():
                raise HTTPException(
                    409,
                    f"Já existe um usuário com o e-mail {body.admin.email} neste banco. "
                    "Escolha outro endereço ou um banco vazio.",
                )

            # Planta inicial
            planta = s.query(Planta).filter(Planta.sigla == body.planta.sigla).first()
            if planta is None:
                planta = Planta(nome=body.planta.nome, sigla=body.planta.sigla, ativa=True)
                s.add(planta)
                s.flush()
                passos.append(f"Planta criada: {planta.nome} ({planta.sigla}).")

            # Administrador — entra em TODAS as plantas (planta_id nulo).
            admin = Usuario(
                nome=body.admin.nome,
                email=body.admin.email,
                senha_hash=hash_password(body.admin.senha),
                papel="admin",
                origem="local",
                ativo=True,
                planta_id=None,
            )
            s.add(admin)
            passos.append(f"Administrador criado: {admin.email}.")

            # Marca da empresa
            cfg = s.get(ConfiguracaoSistema, 1) or ConfiguracaoSistema(id=1)
            cfg.empresa_nome = body.empresa.nome
            cfg.empresa_logo = body.logo
            cfg.empresa_favicon = body.favicon
            cfg.empresa_rodape = body.empresa.rodape
            s.add(cfg)
            passos.append(f"Empresa definida: {body.empresa.nome}.")

            # AD (opcional)
            if body.ad and body.ad.ativo:
                cfg.ldap_ativo = True
                cfg.ldap_servidor = body.ad.servidor
                cfg.ldap_porta = body.ad.porta
                cfg.ldap_tls = body.ad.porta == 636
                cfg.ldap_base_dn = body.ad.base_dn
                cfg.ldap_bind_dn = body.ad.conta_servico
                if body.ad.senha_servico:
                    cfg.ldap_bind_senha = cifrar(body.ad.senha_servico)
                cfg.ldap_filtro_usuario = body.ad.filtro_usuario
                passos.append("Integração com o AD ativada.")
            else:
                cfg.ldap_ativo = False

            # OCS (opcional)
            if body.ocs and body.ocs.ativo:
                ocs_cfg = s.get(ConfiguracaoOCS, 1) or ConfiguracaoOCS(id=1)
                ocs_cfg.ativo = True
                ocs_cfg.servidor = (body.ocs.servidor or "").rstrip("/")
                if body.ocs.token:
                    ocs_cfg.token = cifrar(body.ocs.token)
                s.add(ocs_cfg)
                passos.append("Integração com o OCS ativada.")

            s.commit()

        # --- 3. .env ------------------------------------------------------
        url = montar_url(body.banco)
        novos = {
            "DATABASE_URL": url,
            "JWT_SECRET": estado.segredo_novo(),
            "QR_HMAC_SECRET": estado.segredo_novo(),
        }
        # Não sobrescreve segredos já definidos à mão: trocá-los invalidaria
        # sessões abertas e as etiquetas QR já impressas.
        atuais = estado.ler_env()
        if atuais.get("JWT_SECRET"):
            novos.pop("JWT_SECRET")
            avisos.append("O JWT_SECRET existente foi mantido.")
        if atuais.get("QR_HMAC_SECRET"):
            novos.pop("QR_HMAC_SECRET")
            avisos.append("O QR_HMAC_SECRET existente foi mantido (as etiquetas já impressas continuam válidas).")

        estado.gravar_env(novos)
        passos.append("Arquivo .env atualizado.")

    finally:
        motor.dispose()

    from app import __version__

    estado.marcar_instalado({
        "versao": __version__,
        "banco": body.banco.tipo,
        "empresa": body.empresa.nome,
    })
    passos.append("Instalação concluída.")

    return {
        "ok": True,
        "passos": passos,
        "avisos": avisos,
        "precisa_reiniciar": True,
        "mensagem": "Configuração concluída. Reinicie o sistema para entrar.",
    }
