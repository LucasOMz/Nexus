"""Configuração central via variáveis de ambiente (pydantic-settings).

Um único objeto `settings` é importado por todo o sistema, mantendo as
configurações em um ponto só e tipadas (Type hints obrigatórios).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Banco ---
    # SQLite no dev (zero dependência); PostgreSQL em produção.
    database_url: str = "sqlite:///./estoque.db"
    auto_create_tables: bool = True

    # --- Segurança ---
    jwt_secret: str = "troque-este-segredo-jwt"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    qr_hmac_secret: str = "troque-este-segredo-qr-hmac"
    # Assinatura do QR: quando False, a leitura aceita a etiqueta pelo ID do
    # payload mesmo com assinatura ausente/divergente (útil para não reimprimir
    # etiquetas já coladas). Padrão True para não afrouxar sem pedido explícito.
    qr_exigir_assinatura: bool = True
    # Segredos antigos aceitos na validação (separados por vírgula). Permite
    # trocar o QR_HMAC_SECRET sem invalidar as etiquetas já impressas.
    qr_hmac_secrets_anteriores: str = ""

    # --- Impressão ---
    print_agent_url: str = "http://127.0.0.1:9100"
    print_agent_timeout: int = 30
    cups_printer_default: str = "zebra"
    # Credenciais da fila compartilhada no LINUX (smbclient). Em branco, tenta
    # acesso anônimo. No Windows não são usadas — lá o spooler usa a conta do serviço.
    print_smb_usuario: str = ""
    print_smb_senha: str = ""

    # --- Chave mestra das licenças de software -----------------------------
    # Cifra as chaves de licença em repouso (app/core/segredos.py).
    #
    # ## Por que está AQUI, e não só no `os.environ`
    #
    # O `Settings` lê o `.env` para dentro do objeto — e **não** popula
    # `os.environ`. Um módulo que leia `os.environ.get("NEXUS_CHAVE_LICENCAS")`
    # recebe `None` numa instalação normal, mesmo com a variável no `.env`.
    #
    # Era exatamente o que acontecia: a cifra existia, os testes passavam
    # (eles escrevem em `os.environ` de verdade) e **cadastrar licença com
    # chave falhava na implantação**. Declarar aqui é o que liga a
    # configuração ao modo real de subir o sistema.
    #
    # `segredos.py` consulta este campo primeiro e cai para `os.environ`
    # depois — o fallback mantém funcionando quem define a variável no
    # ambiente (Docker, systemd, testes).
    #
    # O ALIAS é necessário: o Pydantic deriva o nome da variável do CAMPO
    # (`chave_licencas` → `CHAVE_LICENCAS`), e sem ele `NEXUS_CHAVE_LICENCAS`
    # no `.env` seria ignorada em silêncio — o mesmo tipo de falha que este
    # campo existe para corrigir.
    chave_licencas: str = Field(default="", validation_alias="NEXUS_CHAVE_LICENCAS")
    # Versão da chave em uso. Girar exige subir este número junto com a troca
    # do valor: os registros antigos carregam a versão com que foram cifrados.
    chave_licencas_versao: int = Field(default=1, validation_alias="NEXUS_CHAVE_LICENCAS_VERSAO")

    # --- Reporte de erro ---------------------------------------------------
    # Recurso TEMPORÁRIO (fase de implantação). Desligue com
    # REPORTE_ERRO_ATIVO=false no .env — a tela some e a API recusa envios.
    reporte_erro_ativo: bool = True

    # --- Agendador (sincronizacao automatica com o OCS) --------------------
    # Nos testes fica desligado (conftest.py), para nao abrir sessoes de
    # banco em paralelo com os testes.
    scheduler_ativo: bool = True

    # --- Notificacoes por e-mail -------------------------------------------
    # Intervalo, em segundos, entre ciclos do agendador de e-mail. Avisos de
    # inventario sao estado, nao evento em tempo real: cinco minutos evitam
    # consultar o banco para descobrir que nada mudou. O piso de 60s e
    # aplicado no proprio agendador.
    smtp_intervalo: int = 300

    # --- Backup ---
    # Pasta onde os backups são gravados (aponte para o compartilhamento de rede
    # montado no host, ex.: /backups). Vazio = "<media_dir>/../backups".
    backup_dir: str = ""
    # Retenção: quantos backups manter na pasta antes de apagar os mais antigos.
    backup_reter: int = 30

    # --- CORS ---
    # `NoDecode` é essencial: sem ele o pydantic-settings tenta interpretar o
    # valor do .env como JSON (por ser list[str]) e quebra com uma lista
    # separada por vírgula — ou seja, copiar o .env.example para .env
    # derrubava a aplicação. Com NoDecode o texto chega cru no validador abaixo.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:4545", "http://127.0.0.1:4545"]

    # --- App ---
    env: str = "development"
    seed_admin_email: str = "admin@empresa.com"
    seed_admin_password: str = "admin123"
    # Diretório para arquivos gerados (termos PDF, anexos de manutenção).
    media_dir: str = "./media"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("jwt_secret", "qr_hmac_secret", "chave_licencas", mode="after")
    @classmethod
    def _resolver_segredos(cls, v: str, info) -> str:
        """Resolve segredos que não foram definidos no ambiente.

        ## Por que no validador

        Este é o **único** ponto que roda antes de qualquer uso do segredo,
        seja para assinar um token, validar um QR ou cifrar uma licença.

        ## O que ele faz

        1. Valor definido no ambiente (que não seja o padrão do código) — usa
        2. Arquivo no volume de segredos — usa
        3. Nada — **gera** 256 bits e grava no volume

        Assim a stack sobe sem nenhuma variável e **sem** cair no padrão
        publicado no repositório (`troque-este-segredo-jwt`), que era o que o
        `:?` do compose existia para impedir — ao custo de bloquear a criação.
        """
        from app.core import segredos_instalacao

        return segredos_instalacao.obter(info.field_name, v)

    @property
    def cors_origin_list(self) -> list[str]:
        return self.cors_origins

    @property
    def eh_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @model_validator(mode="after")
    def _recusar_sqlite_em_producao(self):
        """SQLite não sobe em produção. Falha no boot, com o motivo.

        ## Por que uma guarda, e não só remover o suporte

        O SQLite continua existindo por baixo **para os testes** — a suíte
        inteira roda em `sqlite://` na memória, e trocá-la por PostgreSQL
        exigiria um banco de pé no CI, mais lento e mais frágil.

        O que não pode existir é **SQLite em produção**, e por um motivo
        concreto: dentro de um container o arquivo fica na camada efêmera.
        Recriar o container **apaga** ativos, usuários, fotos e histórico —
        sem erro, sem log, sem aviso. A pessoa descobre semanas depois.

        ## Por que falhar no boot

        A alternativa seria um aviso. Aviso em log de container ninguém lê.
        Falhar na subida obriga a corrigir **antes** de perder dado.

        `ENV=production` é o que separa os dois mundos. O compose já define.
        """
        if self.eh_sqlite and (self.env or "").lower() == "production":
            raise ValueError(
                "DATABASE_URL aponta para SQLite, mas ENV=production. "
                "Em container, o arquivo do SQLite vive na camada efêmera: "
                "recriar o container apaga todos os dados. "
                "Use DATABASE_URL=postgresql+psycopg://usuario:senha@host:5432/banco "
                "— ou, se a intenção for mesmo SQLite, defina ENV=development."
            )
        return self

    @property
    def segredos_qr(self) -> list[str]:
        """Segredos aceitos na validação, do mais novo para o mais antigo."""
        anteriores = [s.strip() for s in self.qr_hmac_secrets_anteriores.split(",") if s.strip()]
        return [self.qr_hmac_secret, *anteriores]

    @property
    def backup_path(self) -> str:
        """Caminho efetivo da pasta de backups."""
        if self.backup_dir:
            return self.backup_dir
        import os

        return os.path.abspath(os.path.join(self.media_dir, "..", "backups"))


@lru_cache
def get_settings() -> Settings:
    """Retorna uma instância única (cacheada) das configurações."""
    return Settings()


settings = get_settings()
