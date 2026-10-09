"""Configuração central via variáveis de ambiente (pydantic-settings).

Um único objeto `settings` é importado por todo o sistema, mantendo as
configurações em um ponto só e tipadas (Type hints obrigatórios).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
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

    # --- Reporte de erro ---------------------------------------------------
    # Recurso TEMPORÁRIO (fase de implantação). Desligue com
    # REPORTE_ERRO_ATIVO=false no .env — a tela some e a API recusa envios.
    reporte_erro_ativo: bool = True

    # --- Agendador (sincronizacao automatica com o OCS) --------------------
    # Nos testes fica desligado (conftest.py), para nao abrir sessoes de
    # banco em paralelo com os testes.
    scheduler_ativo: bool = True

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
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:8000", "http://127.0.0.1:8000"]

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

    @property
    def cors_origin_list(self) -> list[str]:
        return self.cors_origins

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
